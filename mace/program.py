"""Paired program representation for MACE.

Given a source file with exactly one ``# TARGET_A`` marker, build

    P+ : the original program
    P- : the same program with A replaced by ``pass``

and instrument both at the A program point so that the local state and the
return value can be inspected.  The instrumented programs run inside the
isolated child process (see ``sandbox.py``); this module contains the static
side plus the execution harness used by that child.

Accepted language: a deterministic Python subset (ints, lists, dicts, if,
simple loops, user-defined pure functions).  Anything outside it is rejected
with an explicit reason instead of being silently mis-analysed.
"""
from __future__ import annotations

import ast
import copy
import sys
from dataclasses import dataclass, field
from typing import Any, Dict, List, Sequence

from .terms import MAX_LIST, normalize, sort_of

ALLOWED_BUILTINS = {
    "len", "range", "sorted", "min", "max", "sum", "abs", "enumerate", "zip",
    "list", "tuple", "dict", "set", "int", "bool", "reversed", "any", "all",
    "divmod", "str", "isinstance", "locals",
}
ALLOWED_METHODS = {
    "append", "insert", "pop", "extend", "reverse", "sort", "count", "index",
    "remove", "clear", "copy", "get", "items", "keys", "values", "setdefault",
}
STMT_OK = (
    ast.FunctionDef, ast.Assign, ast.AugAssign, ast.AnnAssign, ast.If, ast.For,
    ast.While, ast.Return, ast.Break, ast.Continue, ast.Pass, ast.Expr,
)
EXPR_OK = (
    ast.Name, ast.Load, ast.Store, ast.Constant, ast.List, ast.Tuple, ast.Dict,
    ast.Subscript, ast.Slice, ast.BinOp, ast.UnaryOp, ast.BoolOp, ast.Compare,
    ast.IfExp, ast.Call, ast.arguments, ast.arg, ast.Attribute,
)
OP_OK = (
    ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod, ast.Pow, ast.BitAnd,
    ast.BitOr, ast.BitXor, ast.LShift, ast.RShift, ast.USub, ast.UAdd, ast.Not,
    ast.And, ast.Or, ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE,
    ast.In, ast.NotIn, ast.Is, ast.IsNot,
)


class AnalysisError(Exception):
    """The program is outside the supported subset."""


def find_target_line(source: str) -> int:
    lines = source.splitlines()
    sites = [i for i, line in enumerate(lines, 1) if "# TARGET_A" in line]
    if len(sites) != 1:
        raise AnalysisError(f"expected exactly one '# TARGET_A' marker, found {len(sites)}")
    return sites[0]


def defined_functions(tree: ast.Module) -> Dict[str, ast.FunctionDef]:
    return {n.name: n for n in tree.body if isinstance(n, ast.FunctionDef)}


def _parent_map(tree: ast.Module) -> Dict[ast.AST, ast.AST]:
    parents: Dict[ast.AST, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[child] = node
    return parents


def target_statement(tree: ast.Module, line: int) -> ast.stmt:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)) and node.lineno == line:
            if isinstance(node, ast.Assign) and len(node.targets) > 1:
                raise AnalysisError("chained assignment at A is not supported")
            return node
    raise AnalysisError(f"line {line} does not hold a simple assignment")


def _inside_loop(tree: ast.Module, line: int) -> bool:
    for node in ast.walk(tree):
        if isinstance(node, (ast.For, ast.While)) and node.lineno <= line <= (node.end_lineno or node.lineno):
            return True
    return False


def validate_subset(tree: ast.Module) -> List[str]:
    """Return a list of unsupported constructs (empty means accepted)."""
    problems: List[str] = []
    functions = set(defined_functions(tree))
    parents = _parent_map(tree)
    allowed_attr = {id(cast.func) for cast in ast.walk(tree)
                    if isinstance(cast, ast.Call) and isinstance(cast.func, ast.Attribute)
                    and cast.func.attr in ALLOWED_METHODS
                    and isinstance(cast.func.value, ast.Name)}
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and not isinstance(parents.get(node), ast.Module):
            problems.append(f"nested function definition at line {node.lineno}")
        if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
            continue  # docstring
        if isinstance(node, (ast.stmt, ast.expr, ast.arguments, ast.arg,
                             ast.operator, ast.boolop, ast.unaryop, ast.cmpop,
                             ast.expr_context)) and not isinstance(node, STMT_OK + EXPR_OK + OP_OK):
            problems.append(f"unsupported syntax {type(node).__name__} at line {getattr(node, 'lineno', '?')}")
            continue
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, bool, str, type(None))):
                problems.append(f"unsupported literal at line {node.lineno}")
        elif isinstance(node, ast.Call):
            func = node.func
            if isinstance(func, ast.Name):
                if func.id not in ALLOWED_BUILTINS and func.id not in functions:
                    problems.append(f"call to disallowed function {func.id!r} at line {node.lineno}")
            elif isinstance(func, ast.Attribute):
                if func.attr not in ALLOWED_METHODS:
                    problems.append(f"call to disallowed method {func.attr!r} at line {node.lineno}")
                if not isinstance(func.value, ast.Name):
                    problems.append(f"method call on a non-name at line {node.lineno}")
            else:
                problems.append(f"indirect call at line {node.lineno}")
        elif isinstance(node, ast.Attribute):
            # Bare attribute access is only allowed as the callee of an allowed method.
            if id(node) not in allowed_attr:
                problems.append(f"attribute access {node.attr!r} at line {node.lineno}")
        elif isinstance(node, ast.Name) and node.id.startswith("__"):
            problems.append(f"dunder name {node.id!r} at line {node.lineno}")
    return sorted(set(problems))


def _capture_statement(template: ast.stmt) -> ast.stmt:
    call = ast.Call(func=ast.Name(id="__mace_record__", ctx=ast.Load()),
                    args=[ast.Call(func=ast.Name(id="locals", ctx=ast.Load()),
                                   args=[], keywords=[])], keywords=[])
    stmt = ast.Expr(value=call)
    return ast.copy_location(stmt, template)


def _inject_after(tree: ast.Module, line: int) -> ast.Module:
    """Insert the snapshot capture right after every statement on ``line``."""
    def walk_body(body: List[ast.stmt]) -> List[ast.stmt]:
        out: List[ast.stmt] = []
        for stmt in body:
            out.append(stmt)
            if getattr(stmt, "lineno", None) == line:
                out.append(_capture_statement(stmt))
            for name, value in ast.iter_fields(stmt):
                if isinstance(value, list) and value and isinstance(value[0], ast.stmt):
                    setattr(stmt, name, walk_body(value))
        return out
    tree.body = walk_body(tree.body)
    return ast.fix_missing_locations(tree)


def _replace_with_pass(tree: ast.Module, line: int) -> ast.Module:
    class Replace(ast.NodeTransformer):
        def visit(self, node):
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)) \
                    and getattr(node, "lineno", None) == line:
                return ast.copy_location(ast.Pass(), node)
            return self.generic_visit(node)
    tree = Replace().visit(tree)
    return ast.fix_missing_locations(tree)


def _restricted_builtins() -> Dict[str, Any]:
    import builtins as bt
    return {name: getattr(bt, name) for name in ALLOWED_BUILTINS if hasattr(bt, name)}


def _sanitize(value: Any) -> Any:
    """Best-effort JSON-safe copy; unsupported values become a marker string."""
    sort = sort_of(value)
    if sort is not None:
        if isinstance(value, (list, dict)) and len(value) > MAX_LIST:
            return "<oversize>"
        return normalize(value)
    if isinstance(value, tuple):
        return [_sanitize(v) for v in value]
    return f"<{type(value).__name__}>"


def _capture(local_vars: Dict[str, Any]) -> Dict[str, Any]:
    snap: Dict[str, Any] = {}
    for name, value in local_vars.items():
        if name.startswith("__"):
            continue
        sort = sort_of(value)
        if sort is None:
            continue
        if isinstance(value, (list, dict)) and len(value) > MAX_LIST:
            continue
        snap[name] = normalize(value)
    return snap


def _make_namespace(tree: ast.Module, store: Dict[str, Any]) -> Dict[str, Any]:
    def record(local_vars):
        store["snap"] = _capture(local_vars)

    namespace: Dict[str, Any] = {
        "__mace_record__": record,
        "__name__": "__mace_program__",
        "__builtins__": _restricted_builtins(),
    }
    exec(compile(tree, "<mace-paired>", "exec"), namespace)  # noqa: S102 - trusted harness in child process
    return namespace


@dataclass
class PairInfo:
    source: str
    target_line: int
    entry: str
    arg_names: List[str]
    plus_tree: ast.Module = field(repr=False, default=None)   # type: ignore[assignment]
    minus_tree: ast.Module = field(repr=False, default=None)  # type: ignore[assignment]
    function_names: List[str] = field(default_factory=list)
    problems: List[str] = field(default_factory=list)

    @property
    def supported(self) -> bool:
        return not self.problems


def build_pair(source: str, entry: str = "program") -> PairInfo:
    tree = ast.parse(source)
    line = find_target_line(source)
    problems = validate_subset(tree)
    functions = defined_functions(tree)
    if entry not in functions:
        problems.append(f"entry function {entry!r} is not defined")
    if _inside_loop(tree, line):
        problems.append("target A is inside a loop; the instrumented snapshot would be ambiguous")
    if problems:
        return PairInfo(source, line, entry, [], None, None, sorted(functions), problems)

    target_statement(tree, line)  # raises for non-assignment
    entry_node = functions[entry]
    if not (entry_node.lineno <= line <= (entry_node.end_lineno or entry_node.lineno)):
        raise AnalysisError("target A is not inside the entry function")
    arg_names = [a.arg for a in entry_node.args.args]

    plus = _inject_after(copy.deepcopy(tree), line)
    minus = _replace_with_pass(copy.deepcopy(tree), line)
    minus = _inject_after(minus, line)
    return PairInfo(source, line, entry, arg_names, plus, minus, sorted(functions), [])


def run_pair(pair: PairInfo, cases: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Execute every case on P+ and P-.  Called inside the sandbox child."""
    plus_store: Dict[str, Any] = {}
    minus_store: Dict[str, Any] = {}
    plus_ns = _make_namespace(pair.plus_tree, plus_store)
    minus_ns = _make_namespace(pair.minus_tree, minus_store)
    plus_fn = plus_ns[pair.entry]
    minus_fn = minus_ns[pair.entry]
    results: List[Dict[str, Any]] = []
    for case in cases:
        args = [case[name] for name in pair.arg_names]
        row: Dict[str, Any] = {"args": {name: copy.deepcopy(v) for name, v in zip(pair.arg_names, args)}}
        for tag, fn, store in (("plus", plus_fn, plus_store), ("minus", minus_fn, minus_store)):
            local_args = copy.deepcopy(args)
            store.pop("snap", None)
            try:
                value = fn(*local_args)
                row[f"out_{tag}"] = _sanitize(value)
                row[f"snap_{tag}"] = store.get("snap", {})
                row[f"err_{tag}"] = None
            except Exception as exc:  # noqa: BLE001 - report, do not crash the batch
                row[f"out_{tag}"] = None
                row[f"snap_{tag}"] = store.get("snap", {})
                row[f"err_{tag}"] = f"{type(exc).__name__}: {exc}"
        row["outputs_equal"] = (row["err_plus"] is None and row["err_minus"] is None
                                and row["out_plus"] == row["out_minus"])
        row["a_has_local_effect"] = row["snap_plus"] != row["snap_minus"]
        results.append(row)
    return results


def run_traced(pair: PairInfo, case: Dict[str, Any], max_records: int = 4000) -> Dict[str, Any]:
    """Run one case on both versions, recording the entry function's locals per line.

    The trace is what lets the report say *where* a difference died, rather than
    only that the final outputs agree.  Called inside the sandbox child only.
    """
    traces: Dict[str, List[Dict[str, Any]]] = {"plus": [], "minus": []}
    plus_store: Dict[str, Any] = {}
    minus_store: Dict[str, Any] = {}
    plus_fn = _make_namespace(pair.plus_tree, plus_store)[pair.entry]
    minus_fn = _make_namespace(pair.minus_tree, minus_store)[pair.entry]
    args = [case[name] for name in pair.arg_names]

    def make_tracer(sink: List[Dict[str, Any]]):
        def tracer(frame, event, arg):  # noqa: ARG001 - settrace signature
            if event != "call" or frame.f_code.co_name != pair.entry:
                return None

            def local_tracer(frm, evt, _arg):
                if evt == "line" and len(sink) < max_records:
                    sink.append({"line": frm.f_lineno,
                                 "locals": _safe_locals(frm.f_locals, pair.arg_names)})
                return local_tracer

            sink.append({"line": frame.f_lineno,
                         "locals": _safe_locals(frame.f_locals, pair.arg_names),
                         "enter": True})
            return local_tracer

        return tracer

    out: Dict[str, Any] = {"args": {name: copy.deepcopy(v) for name, v in zip(pair.arg_names, args)}}
    for tag, fn in (("plus", plus_fn), ("minus", minus_fn)):
        local_args = copy.deepcopy(args)
        previous = sys.gettrace()
        sys.settrace(make_tracer(traces[tag]))
        try:
            value = fn(*local_args)
            out[f"out_{tag}"] = _sanitize(value)
            out[f"err_{tag}"] = None
        except Exception as exc:  # noqa: BLE001 - report, do not crash
            out[f"out_{tag}"] = None
            out[f"err_{tag}"] = f"{type(exc).__name__}: {exc}"
        finally:
            sys.settrace(previous)
    out["traces"] = traces
    return out


def _safe_locals(local_vars: Dict[str, Any], arg_names: Sequence[str]) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for name, value in local_vars.items():
        if name in ("__mace_record__",) or name.startswith("__"):
            continue
        try:
            out[name] = _sanitize(value)
        except Exception:  # noqa: BLE001 - unserialisable locals are simply omitted
            continue
    return out


def build_callables(pair: PairInfo) -> Dict[str, Any]:
    """Expose the program's own functions to the term evaluator (child only)."""
    store: Dict[str, Any] = {}
    namespace = _make_namespace(pair.plus_tree, store)
    return {name: namespace[name] for name in pair.function_names
            if name in namespace and callable(namespace[name])}


ANNOTATION_SORTS = {"int": "int", "bool": "bool", "list": "list[int]", "dict": "dict[int,int]"}


def declared_signatures(source: str) -> Dict[str, Dict[str, Any]]:
    """Function signatures from type annotations, when present and complete."""
    tree = ast.parse(source)
    out: Dict[str, Dict[str, Any]] = {}
    for node in tree.body:
        if not isinstance(node, ast.FunctionDef):
            continue
        params = []
        for arg in node.args.args:
            ann = arg.annotation
            name = ann.id if isinstance(ann, ast.Name) else None
            params.append(ANNOTATION_SORTS.get(name or "", "?"))
        ret = node.returns
        ret_name = ret.id if isinstance(ret, ast.Name) else None
        ret_sort = ANNOTATION_SORTS.get(ret_name or "", "?")
        complete = "?" not in params and ret_sort != "?"
        out[node.name] = {"params": params, "ret": ret_sort, "annotated": complete}
    return out
