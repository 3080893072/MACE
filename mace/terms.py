"""Typed, non-executing term language used by MACE semantic contracts.

Why a custom language
---------------------
The LLM is allowed to *propose* relations, but its output must never be
turned into executable Python.  Every expression is parsed with
``ast.parse(..., mode="eval")`` and then walked node by node by this
module.  There is no ``eval``/``compile`` on model-provided text anywhere.

Sorts (v1)
----------
    bool          True / False
    int           Python int that is not a bool
    list[int]     list of ints
    dict[int,int] dict with int keys and int values

Supported syntax
----------------
    literals             3, True, False, [1, 2], {0: 1, 1: 2}
    names                variables from the declared environment
    arithmetic           + - * // %  (int only); unary -
    boolean              and or not
    comparisons          == != (any sort), < <= > >= (int)
    conditional          a if c else b
    indexing             xs[i] (list), d[k] (dict)
    whitelisted calls    len, min, max, sum, abs, sorted, distinct, count
    program calls        f(args...) for functions of the analysed program
                         with a declared signature (never arbitrary code)

Everything else raises TermError -> the contract is reported as UNKNOWN or
invalid, never silently accepted.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Mapping, Sequence

BOOL = "bool"
INT = "int"
LINT = "list[int]"
DINT = "dict[int,int]"

SORTS = (BOOL, INT, LINT, DINT)

MAX_LIST = 4096
MAX_DEPTH = 60


class TermError(Exception):
    """Raised for any expression that is outside the supported language."""


# --------------------------------------------------------------------------
# Value helpers
# --------------------------------------------------------------------------
def is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def sort_of(value: Any) -> str | None:
    if isinstance(value, bool):
        return BOOL
    if is_int(value):
        return INT
    if isinstance(value, list) and all(is_int(v) for v in value):
        return LINT
    if isinstance(value, dict) and all(is_int(k) and is_int(v) for k, v in value.items()):
        return DINT
    return None


def normalize(value: Any) -> Any:
    """Convert a runtime value to JSON-safe form, or raise TermError."""
    sort = sort_of(value)
    if sort is None:
        raise TermError(f"value of unsupported sort: {type(value).__name__}")
    if sort == LINT:
        if len(value) > MAX_LIST:
            raise TermError("list too large")
        return [int(v) for v in value]
    if sort == DINT:
        if len(value) > MAX_LIST:
            raise TermError("dict too large")
        return {int(k): int(v) for k, v in value.items()}
    return value


# --------------------------------------------------------------------------
# Signatures
# --------------------------------------------------------------------------
@dataclass(frozen=True)
class Signature:
    params: tuple[str, ...]
    ret: str


# name -> (one frozenset of accepted sorts per parameter, return sort, note)
BUILTIN_SIGNATURES: Dict[str, tuple[tuple[frozenset, ...], str, str]] = {
    "len": ((frozenset({LINT, DINT}),), INT, "length"),
    "min": ((frozenset({LINT}),), INT, "minimum"),
    "max": ((frozenset({LINT}),), INT, "maximum"),
    "sum": ((frozenset({LINT}),), INT, "sum"),
    "abs": ((frozenset({INT}),), INT, "absolute value"),
    "sorted": ((frozenset({LINT, DINT}),), LINT, "ascending list; dict -> sorted keys"),
    "vals": ((frozenset({DINT}),), LINT, "values ordered by sorted key"),
    "distinct": ((frozenset({LINT}),), INT, "number of distinct elements"),
    "count": ((frozenset({LINT}), frozenset({INT})), INT, "number of occurrences of a value"),
}

BUILTIN_CALLABLES: Dict[str, Callable[..., Any]] = {
    "len": lambda x: len(x) if sort_of(x) is not None else _bad("len"),
    "min": lambda *a: min(a[0]) if len(a) == 1 else min(a),
    "max": lambda *a: max(a[0]) if len(a) == 1 else max(a),
    "sum": lambda xs: sum(xs),
    "abs": lambda x: abs(x),
    "sorted": lambda x: sorted(x),
    "vals": lambda d: [d[k] for k in sorted(d)],
    "distinct": lambda xs: len(set(xs)),
    "count": lambda xs, v: sum(1 for x in xs if x == v),
}


def _bad(name: str):
    raise TermError(f"invalid argument for {name}")


# --------------------------------------------------------------------------
# Type inference (also the validator: unsupported nodes raise)
# --------------------------------------------------------------------------
def infer(node: ast.expr, env: Mapping[str, str],
          functions: Mapping[str, Signature] | None = None, _depth: int = 0) -> str:
    """Return the sort of ``node`` under the variable environment ``env``."""
    if _depth > MAX_DEPTH:
        raise TermError("expression too deep")
    functions = functions or {}
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return BOOL
        if is_int(node.value):
            return INT
        raise TermError(f"unsupported literal {node.value!r}")
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise TermError(f"unknown variable: {node.id}")
        return env[node.id]
    if isinstance(node, ast.UnaryOp):
        if isinstance(node.op, ast.Not):
            _expect(node.operand, BOOL, env, functions, _depth)
            return BOOL
        if isinstance(node.op, ast.USub):
            _expect(node.operand, INT, env, functions, _depth)
            return INT
        raise TermError(f"unsupported unary op {type(node.op).__name__}")
    if isinstance(node, ast.BinOp):
        if isinstance(node.op, ast.Add):
            left = infer(node.left, env, functions, _depth + 1)
            right = infer(node.right, env, functions, _depth + 1)
            if left == INT and right == INT:
                return INT
            if left == LINT and right == LINT:
                return LINT
            raise TermError(f"cannot add {left} and {right}")
        if isinstance(node.op, (ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod)):
            _expect(node.left, INT, env, functions, _depth)
            _expect(node.right, INT, env, functions, _depth)
            return INT
        raise TermError(f"unsupported binary op {type(node.op).__name__}")
    if isinstance(node, ast.BoolOp):
        for value in node.values:
            _expect(value, BOOL, env, functions, _depth)
        return BOOL
    if isinstance(node, ast.Compare):
        if len(node.ops) != 1 or len(node.comparators) != 1:
            raise TermError("chained comparisons are not supported")
        left = infer(node.left, env, functions, _depth + 1)
        right = infer(node.comparators[0], env, functions, _depth + 1)
        op = node.ops[0]
        if isinstance(op, (ast.Eq, ast.NotEq)):
            if left != right:
                raise TermError(f"comparison of {left} with {right}")
            return BOOL
        if isinstance(op, (ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
            if left != INT or right != INT:
                raise TermError("ordering comparison needs int operands")
            return BOOL
        raise TermError(f"unsupported comparison {type(op).__name__}")
    if isinstance(node, ast.IfExp):
        _expect(node.test, BOOL, env, functions, _depth)
        then = infer(node.body, env, functions, _depth + 1)
        other = infer(node.orelse, env, functions, _depth + 1)
        if then != other:
            raise TermError(f"conditional branches differ: {then} vs {other}")
        return then
    if isinstance(node, ast.List):
        for element in node.elts:
            _expect(element, INT, env, functions, _depth)
        return LINT
    if isinstance(node, ast.Dict):
        for key, value in zip(node.keys, node.values):
            if key is None:
                raise TermError("dict unpacking is not supported")
            _expect(key, INT, env, functions, _depth)
            _expect(value, INT, env, functions, _depth)
        return DINT
    if isinstance(node, ast.Subscript):
        if isinstance(node.slice, ast.Slice):
            raise TermError("slices are not supported")
        container = infer(node.value, env, functions, _depth + 1)
        _expect(node.slice, INT, env, functions, _depth + 1)
        if container == LINT:
            return INT
        if container == DINT:
            return INT
        raise TermError(f"cannot index {container}")
    if isinstance(node, ast.Call):
        if not isinstance(node.func, ast.Name):
            raise TermError("only direct calls to named functions are allowed")
        name = node.func.id
        if node.keywords:
            raise TermError("keyword arguments are not supported")
        arg_sorts = [infer(a, env, functions, _depth + 1) for a in node.args]
        if name in functions:
            sig = functions[name]
            if len(arg_sorts) != len(sig.params):
                raise TermError(f"{name} expects {len(sig.params)} arguments")
            for got, want in zip(arg_sorts, sig.params):
                if got != want:
                    raise TermError(f"{name} argument sort {got}, expected {want}")
            return sig.ret
        if name in ("min", "max"):
            # Python's min/max take either a list or two integers; the prompt
            # names the builtin without an arity, and models write both forms.
            if len(arg_sorts) == 1:
                if arg_sorts[0] != LINT:
                    raise TermError(f"{name}: argument sort {arg_sorts[0]}, expected list[int]")
                return INT
            if len(arg_sorts) == 2:
                if arg_sorts != [INT, INT]:
                    raise TermError(f"{name}: two arguments must both be int")
                return INT
            raise TermError(f"{name} expects 1 or 2 arguments")
        if name not in BUILTIN_SIGNATURES:
            raise TermError(f"unknown function: {name}")
        accepted, ret, _ = BUILTIN_SIGNATURES[name]
        if len(arg_sorts) != len(accepted):
            raise TermError(f"{name} expects {len(accepted)} arguments")
        for got, allowed in zip(arg_sorts, accepted):
            if got not in allowed:
                raise TermError(f"{name}: argument sort {got}, expected one of {sorted(allowed)}")
        return ret
    raise TermError(f"unsupported expression node: {type(node).__name__}")


def _expect(node, sort, env, functions, depth):
    got = infer(node, env, functions, depth + 1)
    if got != sort:
        raise TermError(f"expected {sort}, got {got}")


# --------------------------------------------------------------------------
# Evaluation
# --------------------------------------------------------------------------
def evaluate(expr: str, env: Mapping[str, Any],
             functions: Mapping[str, Signature] | None = None,
             callables: Mapping[str, Callable[..., Any]] | None = None,
             declared_env: Mapping[str, str] | None = None) -> Any:
    """Parse, type-check and evaluate ``expr`` in ``env``.

    ``declared_env`` defaults to the sorts inferred from ``env``'s values and is
    what the type checker uses (so a name bound to the wrong sort is rejected
    before evaluation, not after).
    """
    tree = parse(expr, env if declared_env is None else declared_env, functions)
    return eval_node(tree, env, functions or {}, callables or {}, 0)


def evaluate_checked(checked: "Checked", env: Mapping[str, Any],
                     functions: Mapping[str, Signature] | None = None,
                     callables: Mapping[str, Callable[..., Any]] | None = None) -> Any:
    """Evaluate an already parsed and type-checked expression."""
    return eval_node(checked.tree, env, functions or {}, callables or {}, 0)


def parse(expr: str, env: Mapping[str, str],
          functions: Mapping[str, Signature] | None = None) -> ast.expr:
    if not isinstance(expr, str) or not expr.strip():
        raise TermError("empty expression")
    try:
        tree = ast.parse(expr.strip(), mode="eval")
    except SyntaxError as exc:
        raise TermError(f"syntax error: {exc.msg}") from None
    infer(tree.body, env, functions)
    return tree.body


def eval_node(node: ast.expr, env: Mapping[str, Any],
              functions: Mapping[str, Signature],
              callables: Mapping[str, Callable[..., Any]], depth: int) -> Any:
    if depth > MAX_DEPTH:
        raise TermError("evaluation too deep")
    if isinstance(node, ast.Constant):
        value = node.value
        if isinstance(value, bool) or is_int(value):
            return value
        raise TermError("unsupported literal")
    if isinstance(node, ast.Name):
        if node.id not in env:
            raise TermError(f"unknown variable at evaluation: {node.id}")
        return env[node.id]
    if isinstance(node, ast.UnaryOp):
        operand = eval_node(node.operand, env, functions, callables, depth + 1)
        if isinstance(node.op, ast.Not):
            return not operand
        return -operand
    if isinstance(node, ast.BinOp):
        left = eval_node(node.left, env, functions, callables, depth + 1)
        right = eval_node(node.right, env, functions, callables, depth + 1)
        if isinstance(node.op, ast.Add) and isinstance(left, list) and isinstance(right, list):
            if len(left) + len(right) > MAX_LIST:
                raise TermError("concatenated list too large")
            return left + right
        if not (is_int(left) and is_int(right)):
            raise TermError("arithmetic on non-int")
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.FloorDiv):
            if right == 0:
                raise TermError("division by zero")
            return left // right
        if isinstance(node.op, ast.Mod):
            if right == 0:
                raise TermError("modulo by zero")
            return left % right
        raise TermError("unsupported binary op")
    if isinstance(node, ast.BoolOp):
        values = [eval_node(v, env, functions, callables, depth + 1) for v in node.values]
        if not all(isinstance(v, bool) for v in values):
            raise TermError("boolean op on non-bool")
        return all(values) if isinstance(node.op, ast.And) else any(values)
    if isinstance(node, ast.Compare):
        left = eval_node(node.left, env, functions, callables, depth + 1)
        right = eval_node(node.comparators[0], env, functions, callables, depth + 1)
        op = node.ops[0]
        if isinstance(op, ast.Eq):
            return left == right
        if isinstance(op, ast.NotEq):
            return left != right
        if not (is_int(left) and is_int(right)):
            raise TermError("ordering comparison on non-int")
        return {ast.Lt: left < right, ast.LtE: left <= right,
                ast.Gt: left > right, ast.GtE: left >= right}[type(op)]
    if isinstance(node, ast.IfExp):
        test = eval_node(node.test, env, functions, callables, depth + 1)
        if not isinstance(test, bool):
            raise TermError("conditional test is not bool")
        branch = node.body if test else node.orelse
        return eval_node(branch, env, functions, callables, depth + 1)
    if isinstance(node, ast.List):
        return [eval_node(e, env, functions, callables, depth + 1) for e in node.elts]
    if isinstance(node, ast.Dict):
        out = {}
        for key, value in zip(node.keys, node.values):
            k = eval_node(key, env, functions, callables, depth + 1)
            v = eval_node(value, env, functions, callables, depth + 1)
            if not (is_int(k) and is_int(v)):
                raise TermError("dict literal needs int keys and values")
            out[k] = v
        return out
    if isinstance(node, ast.Subscript):
        container = eval_node(node.value, env, functions, callables, depth + 1)
        index = eval_node(node.slice, env, functions, callables, depth + 1)
        if not is_int(index):
            raise TermError("index is not int")
        if isinstance(container, dict):
            if index not in container:
                raise TermError("missing dict key")
            return container[index]
        if not isinstance(container, list):
            raise TermError("indexing non-list")
        if not (-len(container) <= index < len(container)):
            raise TermError("index out of range")
        return container[index]
    if isinstance(node, ast.Call):
        name = node.func.id
        args = [eval_node(a, env, functions, callables, depth + 1) for a in node.args]
        if name in functions:
            if name not in callables:
                raise TermError(f"program function {name} is not callable here")
            result = callables[name](*args)
            if sort_of(result) != functions[name].ret:
                raise TermError(f"{name} returned an unexpected sort")
            return normalize(result)
        if name not in BUILTIN_CALLABLES:
            raise TermError(f"unknown function {name}")
        result = BUILTIN_CALLABLES[name](*args)
        return normalize(result)
    raise TermError(f"unsupported node at evaluation: {type(node).__name__}")


# --------------------------------------------------------------------------
# Convenience
# --------------------------------------------------------------------------
@dataclass
class Checked:
    """A validated expression together with its inferred sort."""
    expr: str
    sort: str
    tree: ast.expr = field(repr=False, default=None)  # type: ignore[assignment]

    @classmethod
    def build(cls, expr: str, env: Mapping[str, str],
              functions: Mapping[str, Signature] | None = None) -> "Checked":
        tree = parse(expr, env, functions)
        return cls(expr=expr.strip(), sort=infer(tree, env, functions), tree=tree)


def signature_table(raw: Mapping[str, Any] | None) -> Dict[str, Signature]:
    """Convert JSON {'f': {'params': [...], 'ret': 'int'}} to Signature objects."""
    out: Dict[str, Signature] = {}
    for name, spec in (raw or {}).items():
        params = tuple(spec.get("params", []))
        ret = spec.get("ret", INT)
        for sort in params + (ret,):
            if sort not in SORTS:
                raise TermError(f"unknown sort {sort} in signature of {name}")
        out[name] = Signature(params=params, ret=ret)
    return out
