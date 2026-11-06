"""Execution primitives for the benchmark pilot.

Everything the scorer needs is produced by actually running P+ and P-, never
by reading a hand-written formula.  This module is deliberately independent of
``mace``: it does not import the engine under evaluation.
"""
from __future__ import annotations

import ast
import copy
import io
import itertools
import json
import tokenize
import traceback
from typing import Any, Dict, FrozenSet, Iterable, List, Sequence, Set, Tuple


class EngineError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Source transformations
# ---------------------------------------------------------------------------

def strip_op_comments(source: str) -> str:
    """Remove ``# OP_X`` comments while preserving every line number."""
    out = []
    for line in source.splitlines():
        if "# OP_" in line:
            line = line.split("# OP_", 1)[0].rstrip()
        out.append(line)
    return "\n".join(out) + "\n"


def target_line(source: str) -> int:
    lines = source.splitlines()
    hits = [i for i, line in enumerate(lines, 1) if "# TARGET_A" in line]
    if len(hits) != 1:
        raise EngineError(f"expected one # TARGET_A marker, found {len(hits)}")
    return hits[0]


def replace_target_with_pass(source: str) -> str:
    """Textual deletion of the single-line target assignment.

    Only valid for the controlled sources, where A is a one-line assignment.
    """
    line_no = target_line(source)
    lines = source.splitlines()
    raw = lines[line_no - 1]
    indent = raw[: len(raw) - len(raw.lstrip())]
    lines[line_no - 1] = f"{indent}pass  # P-: A deleted"
    return "\n".join(lines) + "\n"


def _disable_if_lines(tree: ast.Module, lines: Set[int]) -> ast.Module:
    class Disable(ast.NodeTransformer):
        def visit_If(self, node: ast.If):  # noqa: N802 - ast API name
            if node.lineno in lines:
                return ast.copy_location(ast.Pass(), node)
            return self.generic_visit(node)

    tree = Disable().visit(tree)
    return ast.fix_missing_locations(tree)


def variant_source(source: str, disabled_lines: Iterable[int]) -> str:
    """Human-readable variant (used in logs); execution uses the AST form."""
    tree = _disable_if_lines(ast.parse(source), set(disabled_lines))
    return ast.unparse(tree) + "\n"


def _inject_capture(tree: ast.Module, line: int) -> ast.Module:
    """Insert ``__bench_record__(locals())`` after every statement on ``line``."""
    def walk(body: List[ast.stmt]) -> List[ast.stmt]:
        out: List[ast.stmt] = []
        for stmt in body:
            out.append(stmt)
            if getattr(stmt, "lineno", None) == line:
                call = ast.Expr(value=ast.Call(
                    func=ast.Name(id="__bench_record__", ctx=ast.Load()),
                    args=[ast.Call(func=ast.Name(id="locals", ctx=ast.Load()),
                                   args=[], keywords=[])],
                    keywords=[]))
                out.append(ast.copy_location(call, stmt))
            for field_name, value in ast.iter_fields(stmt):
                if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                    setattr(stmt, field_name, walk(value))
        return out

    tree.body = walk(tree.body)
    return ast.fix_missing_locations(tree)


# ---------------------------------------------------------------------------
# Canonical observable values
# ---------------------------------------------------------------------------

def canonical(value: Any) -> Any:
    """Type-aware, JSON-safe canonical form; bool and int stay distinct."""
    if value is None:
        return ["none"]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", value]
    if isinstance(value, float):
        return ["float", repr(value)]
    if isinstance(value, str):
        return ["str", value]
    if isinstance(value, (list, tuple)):
        return ["seq", [canonical(v) for v in value]]
    if isinstance(value, dict):
        items = sorted((canonical(k), canonical(v)) for k, v in value.items())
        return ["dict", items]
    if isinstance(value, (set, frozenset)):
        return ["set", sorted(canonical(v) for v in value)]
    return ["obj", f"{type(value).__name__}:{value!r}"]


def error_signature(exc: BaseException) -> Tuple[str, str]:
    return type(exc).__name__, str(exc)


def observation(out: Any, err: Any, exc: BaseException | None) -> Any:
    if exc is not None:
        return ["raise", *error_signature(exc)]
    return ["return", canonical(out)]


def observations_equal(plus: Dict[str, Any], minus: Dict[str, Any]) -> bool:
    return plus["observation"] == minus["observation"]


def _clean_snapshot(local_vars: Dict[str, Any]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, value in local_vars.items():
        if name.startswith("__"):
            continue
        out[name] = canonical(value)
    return out


# ---------------------------------------------------------------------------
# Program execution
# ---------------------------------------------------------------------------

class Compiled:
    def __init__(self, source: str, capture_line: int | None = None):
        self.source = source
        self.store: Dict[str, Any] = {}
        tree = ast.parse(source)
        if capture_line is not None:
            tree = _inject_capture(tree, capture_line)
        self.namespace: Dict[str, Any] = {
            "__bench_record__": lambda local_vars: self.store.__setitem__(
                "snap", _clean_snapshot(local_vars)),
        }
        exec(compile(tree, "<benchmark-pilot>", "exec"), self.namespace)  # noqa: S102

    def call(self, entry: str, args: Dict[str, Any]) -> Dict[str, Any]:
        self.store.pop("snap", None)
        fn = self.namespace[entry]
        try:
            value = fn(**args)
            return {"observation": observation(value, None, None),
                    "snap": self.store.get("snap")}
        except Exception as exc:  # noqa: BLE001 - an exception is an observation
            return {"observation": observation(None, None, exc),
                    "snap": self.store.get("snap"),
                    "traceback": traceback.format_exc(limit=4)}


def compile_source(source: str, capture_line: int | None = None) -> Compiled:
    return Compiled(source, capture_line)


def run_source_cases(compiled: Compiled, entry: str,
                     cases: Sequence[Tuple[str, Dict[str, Any]]]) -> Dict[str, Dict[str, Any]]:
    return {case_id: compiled.call(entry, args) for case_id, args in cases}


# ---------------------------------------------------------------------------
# Test execution
# ---------------------------------------------------------------------------

def run_tests(source: str, tests: Sequence[Dict[str, Any]], entry: str = "program",
              capture_line: int | None = None) -> Dict[str, Dict[str, Any]]:
    """Execute each existing test against one version of the program."""
    results: Dict[str, Dict[str, Any]] = {}
    for test in tests:
        compiled = compile_source(source, capture_line)
        ns = compiled.namespace
        try:
            exec(compile(test["source"], f"<test:{test['name']}>", "exec"), ns)
            test_fn = ns[test["name"]]
            test_fn()
            results[test["name"]] = {"passed": True, "error": None}
        except AssertionError as exc:
            results[test["name"]] = {"passed": False, "error": f"AssertionError: {exc}"}
        except Exception as exc:  # noqa: BLE001
            results[test["name"]] = {
                "passed": False,
                "error": f"{type(exc).__name__}: {exc}",
                "traceback": traceback.format_exc(limit=4),
            }
    return results


# ---------------------------------------------------------------------------
# Intervention variants over controlled sources
# ---------------------------------------------------------------------------

def run_variant_pairs(source_plus: str, source_minus: str, entry: str,
                      op_lines: Dict[str, int],
                      disabled_sets: Iterable[FrozenSet[str]],
                      cases: Sequence[Tuple[str, Dict[str, Any]]]
                      ) -> Dict[FrozenSet[str], Dict[str, Any]]:
    """For each disabled-operation subset, run the *paired* variants.

    ``disabled_sets`` contains operation names; every If statement named in a
    subset is replaced by ``pass`` in both P+ and P-.  The comparison is always
    between the two versions with the same intervention applied, which is the
    only way to tell whether the intervention exposes the deletion.
    """
    out: Dict[FrozenSet[str], Dict[str, Any]] = {}
    for disabled in disabled_sets:
        lines = {op_lines[op] for op in disabled}
        plus_variant = ast.unparse(_disable_if_lines(ast.parse(source_plus), lines)) + "\n"
        minus_variant = ast.unparse(_disable_if_lines(ast.parse(source_minus), lines)) + "\n"
        plus_rows = run_source_cases(compile_source(plus_variant), entry, cases)
        minus_rows = run_source_cases(compile_source(minus_variant), entry, cases)
        equal = {cid: plus_rows[cid]["observation"] == minus_rows[cid]["observation"]
                 for cid, _ in cases}
        out[frozenset(disabled)] = {
            "plus": plus_rows,
            "minus": minus_rows,
            "equal": equal,
            "source_plus": plus_variant,
            "source_minus": minus_variant,
        }
    return out


# ---------------------------------------------------------------------------
# Minimal sufficient sets
# ---------------------------------------------------------------------------

def subsets(ops: Sequence[str]) -> List[FrozenSet[str]]:
    out: List[FrozenSet[str]] = []
    for r in range(len(ops) + 1):
        for combo in itertools.combinations(ops, r):
            out.append(frozenset(combo))
    return out


def minimal_sets(sets: Iterable[FrozenSet[str]]) -> List[FrozenSet[str]]:
    """Non-empty inclusion-minimal members of ``sets``."""
    minimal: List[FrozenSet[str]] = []
    for s in sorted({frozenset(x) for x in sets if x},
                    key=lambda x: (len(x), sorted(x))):
        if not any(t < s for t in minimal):
            minimal.append(s)
    return minimal


# ---------------------------------------------------------------------------
# Guard evaluation (submission expressions)
# ---------------------------------------------------------------------------

_ALLOWED_GUARD_NODES = (
    ast.Expression, ast.BoolOp, ast.BinOp, ast.UnaryOp, ast.Compare,
    ast.Name, ast.Load, ast.Constant,
    ast.And, ast.Or, ast.Not,
    ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod,
    ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
)


class GuardError(EngineError):
    pass


def validate_guard(expr: str, arg_names: Sequence[str]) -> ast.Expression:
    if not isinstance(expr, str):
        raise GuardError(f"guard expression must be a string, not {type(expr).__name__}")
    try:
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, ValueError, TypeError) as exc:
        raise GuardError(f"syntax error: {exc}") from None
    for node in ast.walk(tree):
        if not isinstance(node, _ALLOWED_GUARD_NODES):
            raise GuardError(
                f"unsupported construct {type(node).__name__} in guard")
        if isinstance(node, ast.Name) and node.id not in arg_names:
            raise GuardError(f"guard mentions unknown argument {node.id!r}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, bool)):
            raise GuardError("guard constants must be int or bool")
    return tree


def eval_guard(expr: str, arg_names: Sequence[str], args: Dict[str, Any]) -> bool:
    tree = validate_guard(expr, arg_names)
    value = eval(compile(tree, "<guard>", "eval"),  # noqa: S307 - validated AST
                 {"__builtins__": {}}, dict(args))
    if not isinstance(value, bool):
        raise GuardError("guard expression did not evaluate to a bool")
    return value


# ---------------------------------------------------------------------------
# JSON helpers
# ---------------------------------------------------------------------------

def setlist(sets: Iterable[FrozenSet[str]]) -> List[List[str]]:
    return sorted((sorted(s) for s in sets), key=lambda x: (len(x), x))


def to_jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


def read_json(path: str) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def write_json(path: str, value: Any) -> None:
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(to_jsonable(value), handle, ensure_ascii=False, indent=2)
        handle.write("\n")
