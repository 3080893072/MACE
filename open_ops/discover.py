"""Deterministic operation-level masking discovery for the controlled tasks.

The module answers a narrower question than Full MACE:

    Given P+, P- and a finite legal input domain, which downstream operation
    sets independently, cooperatively, or coexisting-ly mask the deletion of A?

It does **not** read ``attribution.json`` or ``# OP_X`` comments.  Candidate
operations are obtained by a backward slice from the function's return value.
A candidate is a top-level statement that writes a live variable (or an ``if``
whose body does), plus any earlier statement that writes a variable read by
such a statement.  This is what connects an upstream control assignment to a
downstream overwrite.

The implementation is a deterministic baseline.  It reuses the benchmark's
paired executor and guard evaluator, but it does not claim to be a new MACE
algorithm.
"""
from __future__ import annotations

import ast
import itertools
import time
from dataclasses import dataclass, field, replace
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Set, Tuple

from benchmark_pilot import engine

MAX_CANDIDATES = 12


class UnsupportedProgram(ValueError):
    """The source is outside the small supported statement subset."""


# ---------------------------------------------------------------------------
# Operations and results
# ---------------------------------------------------------------------------

def _node_key(node: ast.AST) -> Tuple[str, int, int, Optional[int], Optional[int]]:
    return (
        type(node).__name__,
        int(getattr(node, "lineno", -1)),
        int(getattr(node, "col_offset", -1)),
        getattr(node, "end_lineno", None),
        getattr(node, "end_col_offset", None),
    )


@dataclass(frozen=True)
class Operation:
    key: str
    kind: str
    line: int
    end_line: int
    col: int
    end_col: Optional[int]
    text: str
    reads: FrozenSet[str]
    writes: FrozenSet[str]
    provenance: Tuple[str, ...] = ()
    contract_refs: Tuple[str, ...] = ()
    control_reads: FrozenSet[str] = frozenset()

    def node_key(self) -> Tuple[str, int, int, Optional[int], Optional[int]]:
        node_type = {
            "if": "If",
            "assign": "Assign",
            "annassign": "AnnAssign",
            "augassign": "AugAssign",
            "expr": "Expr",
        }.get(self.kind)
        if node_type is None:
            raise KeyError(f"unsupported operation kind {self.kind!r}")
        return (node_type, self.line, self.col, self.end_line, self.end_col)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "key": self.key,
            "kind": self.kind,
            "line": self.line,
            "end_line": self.end_line,
            "text": self.text,
            "reads": sorted(self.reads),
            "writes": sorted(self.writes),
            "provenance": list(self.provenance),
            "contract_refs": list(self.contract_refs),
            "control_reads": sorted(self.control_reads),
        }


@dataclass
class Relation:
    kind: str
    operations: Tuple[Operation, ...]
    witness_case: str
    witness_input: Dict[str, Any]
    condition: Optional[str]
    condition_check: Dict[str, Any]
    checks: Dict[str, Any]
    status: str
    condition_status: str = "UNKNOWN"
    evidence_scope: str = "single_witness_plus_finite_domain_condition"
    evidence: Dict[str, Any] = field(default_factory=dict)

    @property
    def source_lines(self) -> List[int]:
        return [op.line for op in self.operations]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "kind": self.kind,
            "source_lines": self.source_lines,
            "operations": [op.to_dict() for op in self.operations],
            "witness": {"case_id": self.witness_case, "input": self.witness_input},
            "condition": self.condition,
            "condition_check": self.condition_check,
            "condition_status": self.condition_status,
            "checks": self.checks,
            "evidence": self.evidence,
            "status": self.status,
            "evidence_scope": self.evidence_scope,
        }


@dataclass
class DiscoveryResult:
    task_id: str
    status: str
    reason: str
    target_line: int
    candidates: Tuple[Operation, ...] = ()
    relations: Tuple[Relation, ...] = ()
    stats: Dict[str, Any] = field(default_factory=dict)
    unsupported: Tuple[str, ...] = ()
    candidate_source: str = "ast_backward_slice"
    contract: Dict[str, Any] = field(default_factory=dict)
    budget: Dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "task_id": self.task_id,
            "status": self.status,
            "reason": self.reason,
            "target_line": self.target_line,
            "candidate_source": self.candidate_source,
            "candidates": [op.to_dict() for op in self.candidates],
            "relations": [rel.to_dict() for rel in self.relations],
            "stats": self.stats,
            "unsupported": list(self.unsupported),
            "contract": self.contract,
            "budget": self.budget,
        }


# ---------------------------------------------------------------------------
# AST candidate extraction
# ---------------------------------------------------------------------------

def _names(node: Optional[ast.AST]) -> Set[str]:
    if node is None:
        return set()
    return {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}


def _root_names(node: ast.AST) -> Set[str]:
    """Root local names of an attribute/subscript target (``self.x`` -> self)."""
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, ast.Attribute):
        return _root_names(node.value)
    if isinstance(node, ast.Subscript):
        return _root_names(node.value)
    return set()


def _target_names(node: ast.AST) -> Set[str]:
    if isinstance(node, ast.Name):
        return {node.id}
    if isinstance(node, (ast.Tuple, ast.List)):
        out: Set[str] = set()
        for item in node.elts:
            out |= _target_names(item)
        return out
    if isinstance(node, (ast.Attribute, ast.Subscript)):
        # A field/item assignment mutates an existing object.  Track the root
        # name as an indirect state effect; execution still decides whether
        # that effect is observable or masking.
        return _root_names(node)
    raise UnsupportedProgram(
        f"assignment target {type(node).__name__} is not a supported target")


# Methods that can mutate an existing object without rebinding it.  This is a
# conservative syntactic list, not a type inference claim.  Anything selected
# here is still only a *candidate*; the execution verifier must confirm it.
_MUTATING_METHODS = {
    "append", "extend", "insert", "remove", "pop", "clear", "sort", "reverse",
    "add", "discard", "update", "setdefault", "popitem",
    "difference_update", "intersection_update",
}


def _check_no_nested_defs(stmt: ast.stmt) -> None:
    for child in ast.walk(stmt):
        if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)):
            if child is not stmt:
                raise UnsupportedProgram("nested function/class definitions are not supported")


def _io(stmt: ast.stmt) -> Tuple[Set[str], Set[str]]:
    """Return (reads, writes) for one statement, conservatively.

    ``If`` is one operation unit: disabling it removes the whole conditional.
    Nested statements are analysed for their reads/writes, but are not emitted
    as separate candidates.  This avoids double-counting an ``if`` and the
    assignment in its body.
    """
    _check_no_nested_defs(stmt)

    if isinstance(stmt, ast.Pass):
        return set(), set()

    if isinstance(stmt, ast.Assign):
        writes: Set[str] = set()
        for target in stmt.targets:
            writes |= _target_names(target)
        return _names(stmt.value), writes

    if isinstance(stmt, ast.AnnAssign):
        writes = _target_names(stmt.target) if stmt.value is not None else set()
        return _names(stmt.value), writes

    if isinstance(stmt, ast.AugAssign):
        target = _target_names(stmt.target)
        return _names(stmt.target) | _names(stmt.value), target

    if isinstance(stmt, ast.If):
        reads = _names(stmt.test)
        writes: Set[str] = set()
        for branch in (stmt.body, stmt.orelse):
            for child in branch:
                if isinstance(child, ast.Return):
                    raise UnsupportedProgram("early return inside a conditional is not supported")
                child_reads, child_writes = _io(child)
                reads |= child_reads
                writes |= child_writes
        return reads, writes

    if isinstance(stmt, ast.Return):
        raise UnsupportedProgram("early/multiple returns are not supported")

    if isinstance(stmt, ast.Expr):
        if isinstance(stmt.value, ast.Constant):
            return set(), set()
        if isinstance(stmt.value, ast.Call):
            call = stmt.value
            reads = _names(call)
            writes: Set[str] = set()
            if isinstance(call.func, ast.Attribute) \
                    and call.func.attr in _MUTATING_METHODS:
                writes |= _root_names(call.func.value)
            return reads, writes
        raise UnsupportedProgram(
            "expression statements with possible side effects are not supported")

    raise UnsupportedProgram(
        f"statement {type(stmt).__name__} is outside the supported subset")


def _find_function(tree: ast.Module, entry: str) -> ast.FunctionDef:
    hits = [n for n in tree.body
            if isinstance(n, ast.FunctionDef) and n.name == entry]
    if len(hits) != 1:
        raise UnsupportedProgram(f"expected exactly one top-level function {entry!r}")
    return hits[0]


def _top_level_statements(func: ast.FunctionDef) -> List[ast.stmt]:
    # A leading docstring is not an operation.
    out: List[ast.stmt] = []
    for i, stmt in enumerate(func.body):
        if i == 0 and isinstance(stmt, ast.Expr) and isinstance(stmt.value, ast.Constant) \
                and isinstance(stmt.value.value, str):
            continue
        out.append(stmt)
    return out


def find_candidates(source_plus: str, source_minus: str, entry: str,
                    target_line: int) -> Tuple[List[Operation], List[str]]:
    """Find downstream operations by a backward live-variable slice.

    Returns ``(candidates, unsupported_reasons)``.  It never reads private
    labels; candidate keys are line/column based.
    """
    tree = ast.parse(source_plus)
    func = _find_function(tree, entry)
    statements = _top_level_statements(func)

    target_index = None
    for i, stmt in enumerate(statements):
        if getattr(stmt, "lineno", None) == target_line:
            target_index = i
            break
    if target_index is None:
        raise UnsupportedProgram(f"target line {target_line} is not a top-level statement")
    target = statements[target_index]
    if not isinstance(target, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
        raise UnsupportedProgram("target A must be a simple assignment")
    if int(getattr(target, "end_lineno", target.lineno)) != target_line:
        raise UnsupportedProgram("target A must be a one-line assignment")

    returns = [i for i, stmt in enumerate(statements) if isinstance(stmt, ast.Return)]
    if len(returns) != 1:
        raise UnsupportedProgram("exactly one top-level return is required")
    return_index = returns[0]
    if return_index != len(statements) - 1:
        raise UnsupportedProgram("statements after the final return are not supported")
    return_stmt = statements[return_index]
    if return_stmt.value is None:
        raise UnsupportedProgram("a return value is required")
    live = _names(return_stmt.value)

    # Operations after A, excluding the final return and no-op statements.
    units: List[Tuple[ast.stmt, Operation]] = []
    for stmt in statements[target_index + 1:return_index]:
        reads, writes = _io(stmt)
        if not writes:
            continue
        kind = type(stmt).__name__.lower()
        text = ast.get_source_segment(source_plus, stmt) or type(stmt).__name__
        op = Operation(
            key=f"op_L{stmt.lineno}_C{stmt.col_offset}_{kind}",
            kind=kind,
            line=int(stmt.lineno),
            end_line=int(getattr(stmt, "end_lineno", stmt.lineno)),
            col=int(stmt.col_offset),
            end_col=getattr(stmt, "end_col_offset", None),
            text=text,
            reads=frozenset(reads),
            writes=frozenset(writes),
        )
        units.append((stmt, op))

    selected: List[Operation] = []
    for stmt, op in reversed(units):
        if op.writes & live:
            selected.append(op)
            if isinstance(stmt, ast.If):
                # An if-body write is conditional: on the branch where the
                # test is false, the old value still reaches later uses.  Do
                # not kill it from the live set (may-write analysis).
                live = live | set(op.reads)
            else:
                live = (live - set(op.writes)) | set(op.reads)
    selected.reverse()

    # Validate that every candidate node still exists in P-.  The controlled
    # P- replaces only the target line, so line/column keys must match.
    minus_tree = ast.parse(source_minus)
    minus_func = _find_function(minus_tree, entry)
    minus_keys = {_node_key(n) for n in minus_func.body
                  if isinstance(n, ast.stmt) and getattr(n, "lineno", None) is not None}
    missing = [op.key for op in selected if op.node_key() not in minus_keys]
    if missing:
        raise UnsupportedProgram(
            "candidate locations differ between P+ and P-: " + ", ".join(missing))

    return selected, []


def _candidate_operation(stmt: ast.stmt, source: str,
                         parent: str = "function") -> Operation:
    reads, writes = _io(stmt)
    kind = type(stmt).__name__.lower()
    text = ast.get_source_segment(source, stmt) or type(stmt).__name__
    reason: List[str] = ["expanded_ast"]
    if isinstance(stmt, ast.If):
        reason.append("control_dependency")
    elif isinstance(stmt, ast.Expr):
        reason.append("indirect_state")
    elif writes & reads:
        reason.append("data_dependency")
    else:
        reason.append("overwrite_write")
    if parent != "function":
        reason.append("nested_control_body")
    control_reads = frozenset(_names(stmt.test)) if isinstance(stmt, ast.If) else frozenset()
    return Operation(
        key=f"op_L{stmt.lineno}_C{stmt.col_offset}_{kind}",
        kind=kind,
        line=int(stmt.lineno),
        end_line=int(getattr(stmt, "end_lineno", stmt.lineno)),
        col=int(stmt.col_offset),
        end_col=getattr(stmt, "end_col_offset", None),
        text=text,
        reads=frozenset(reads),
        writes=frozenset(writes),
        provenance=tuple(reason),
        control_reads=control_reads,
    )


def find_candidates_expanded(source_plus: str, source_minus: str, entry: str,
                             target_line: int
                             ) -> Tuple[List[Operation], List[str]]:
    """Collect data, control, overwrite, and indirect-state candidates.

    Unlike :func:`find_candidates`, this walker also emits statements nested
    inside conditionals (for example the assignment inside an ``if`` body).
    That matters for real code where the masking write is guarded.  It is
    deliberately conservative: every emitted candidate is only a hypothesis,
    and the execution verifier decides whether it is a masking operation.

    Unsupported constructs are returned as reasons rather than silently
    dropping their statements.  A caller must surface those reasons.
    """
    tree = ast.parse(source_plus)
    func = _find_function(tree, entry)
    top = _top_level_statements(func)
    returns = [stmt for stmt in top if isinstance(stmt, ast.Return)]
    if len(returns) != 1:
        raise UnsupportedProgram("exactly one top-level return is required")
    if returns[0] is not top[-1]:
        raise UnsupportedProgram("statements after the final return are not supported")
    final_return_line = int(returns[0].lineno)

    unsupported: List[str] = []
    found: List[Operation] = []

    def written_by(stmts: Sequence[ast.stmt]) -> Set[str]:
        out: Set[str] = set()
        for child in stmts:
            try:
                _, child_writes = _io(child)
            except UnsupportedProgram:
                continue
            out |= child_writes
        return out

    def walk(stmts: Sequence[ast.stmt], parent: str) -> None:
        for stmt in stmts:
            line = int(getattr(stmt, "lineno", -1))
            if isinstance(stmt, ast.Pass):
                continue
            if isinstance(stmt, ast.Return):
                if line != final_return_line:
                    unsupported.append(f"early return at line {line}")
                continue
            if isinstance(stmt, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                unsupported.append(
                    f"nested definition at line {line}: {type(stmt).__name__}")
                continue
            if isinstance(stmt, ast.If):
                # An ``if/elif`` chain that writes the same variable in both
                # branches is a container, not one operation: disabling the
                # whole chain can leave the variable unbound.  Descend and let
                # the branch statements be the operation units.  For an
                # ordinary ``if`` the whole conditional is one unit, matching
                # the original controlled-task baseline.
                common = written_by(stmt.body) & written_by(stmt.orelse)
                if common:
                    walk(stmt.body, "if")
                    walk(stmt.orelse, "if")
                else:
                    if line > target_line:
                        try:
                            found.append(_candidate_operation(
                                stmt, source_plus, parent))
                        except UnsupportedProgram as exc:
                            unsupported.append(f"if at line {line}: {exc}")
                continue
            if isinstance(stmt, (ast.Assign, ast.AnnAssign, ast.AugAssign,
                                 ast.Expr)):
                if line > target_line:
                    try:
                        op = _candidate_operation(stmt, source_plus, parent)
                    except UnsupportedProgram as exc:
                        unsupported.append(f"line {line}: {exc}")
                    else:
                        if op.writes:
                            found.append(op)
                continue
            if isinstance(stmt, (ast.For, ast.AsyncFor, ast.While, ast.Try,
                                 ast.TryStar, ast.With, ast.AsyncWith,
                                 ast.Match, ast.Raise, ast.Delete,
                                 ast.Assert, ast.Global, ast.Nonlocal)):
                unsupported.append(
                    f"statement at line {line} is outside the supported subset: "
                    f"{type(stmt).__name__}")
                continue
            unsupported.append(
                f"statement at line {line} is outside the supported subset: "
                f"{type(stmt).__name__}")

    walk(top, "function")

    # Calls into methods defined elsewhere in the module are cross-function
    # effects: the method body is never walked, so a masking write inside it
    # cannot become a candidate.  Record these explicitly instead of reporting
    # the absence of a relation as a complete negative result.
    class_methods: Dict[str, str] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef):
            for item in node.body:
                if isinstance(item, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    class_methods.setdefault(item.name, node.name)
    seen_calls: Set[Tuple[int, str]] = set()
    for call in ast.walk(func):
        if not isinstance(call, ast.Call):
            continue
        if not isinstance(call.func, ast.Attribute):
            continue
        method = call.func.attr
        line = int(getattr(call, "lineno", -1))
        if line <= target_line or method not in class_methods:
            continue
        marker = (line, method)
        if marker in seen_calls:
            continue
        seen_calls.add(marker)
        unsupported.append(
            f"cross-function method effect at line {line}: "
            f"{class_methods[method]}.{method}() body was not searched")

    # Keep source order and stable positions; the same statement cannot be
    # emitted twice even if a nested walk reaches it from two paths.
    unique: Dict[Tuple[str, int, int, Optional[int], Optional[int]], Operation] = {}
    for op in found:
        unique.setdefault(op.node_key(), op)
    selected = sorted(unique.values(), key=lambda op: (op.line, op.col))

    minus_tree = ast.parse(source_minus)
    minus_func = _find_function(minus_tree, entry)
    minus_keys = {_node_key(n) for n in ast.walk(minus_func)
                  if isinstance(n, ast.stmt)}
    missing = [op.key for op in selected if op.node_key() not in minus_keys]
    if missing:
        raise UnsupportedProgram(
            "candidate locations differ between P+ and P-: " + ", ".join(missing))
    return selected, unsupported


# ---------------------------------------------------------------------------
# Intervention and execution
# ---------------------------------------------------------------------------

class _Disable(ast.NodeTransformer):
    def __init__(self, keys: Set[Tuple[str, int, int, Optional[int], Optional[int]]]):
        self.keys = keys
        self.seen: Set[Tuple[str, int, int, Optional[int], Optional[int]]] = set()

    def visit(self, node: ast.AST) -> ast.AST:
        if isinstance(node, ast.stmt):
            key = _node_key(node)
            if key in self.keys:
                self.seen.add(key)
                # Replacing an enclosing statement also removes every nested
                # statement, so those keys are satisfied without a separate
                # visit.  This is what lets the matrix include both an ``if``
                # and an assignment in its body without a spurious failure.
                for child in ast.walk(node):
                    if isinstance(child, ast.stmt):
                        child_key = _node_key(child)
                        if child_key in self.keys:
                            self.seen.add(child_key)
                return ast.copy_location(ast.Pass(), node)
        return super().visit(node)


def disable_operations(source: str, operations: Sequence[Operation],
                       disabled_keys: Iterable[str]) -> str:
    keys = {op.node_key() for op in operations if op.key in set(disabled_keys)}
    tree = ast.parse(source)
    transformer = _Disable(keys)
    tree = transformer.visit(tree)
    if transformer.seen != keys:
        missing = keys - transformer.seen
        raise UnsupportedProgram(f"could not locate operations in variant: {sorted(missing)}")
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"


def _run_rows(source: str, entry: str, cases: Sequence[Tuple[str, Dict[str, Any]]],
              counter: Dict[str, int], capture_line: Optional[int] = None
              ) -> Dict[str, Dict[str, Any]]:
    compiled = engine.compile_source(source, capture_line=capture_line)
    counter["compilations"] += 1
    rows: Dict[str, Dict[str, Any]] = {}
    for cid, args in cases:
        rows[cid] = compiled.call(entry, args)
        counter["case_executions"] += 1
    return rows


@dataclass
class _Matrix:
    all_keys: Tuple[str, ...]
    rows: Dict[FrozenSet[str], Dict[str, Any]]
    base_equal: Dict[str, bool]
    local_effect: Dict[str, bool]

    def _valid(self, disabled: FrozenSet[str]) -> Dict[str, bool]:
        return self.rows[disabled]["valid"]

    def _raw_equal(self, disabled: FrozenSet[str]) -> Dict[str, bool]:
        return self.rows[disabled]["equal"]

    def masked(self, disabled: FrozenSet[str]) -> Dict[str, bool]:
        """Valid on both sides and observationally equal."""
        return {cid: self._valid(disabled)[cid] and self._raw_equal(disabled)[cid]
                for cid in self._valid(disabled)}

    def masked_strict(self, disabled: FrozenSet[str]) -> Dict[str, bool]:
        """P+ returns and both sides observe the same result.

        Two identical crashes are not evidence that an operation masks A, so
        the sufficiency checks (``only_masked`` / minimality) require a legal
        P+ execution.  Exposure checks separately allow a P+ crash, because a
        crash can itself be the observable difference.
        """
        row = self.rows[frozenset(disabled)]
        return {
            cid: (row["plus"][cid]["observation"][0] == "return"
                  and row["equal"][cid])
            for cid in row["equal"]
        }

    def exposes(self, disabled: FrozenSet[str]) -> Dict[str, bool]:
        """Valid on both sides and observationally different."""
        return {cid: self._valid(disabled)[cid] and not self._raw_equal(disabled)[cid]
                for cid in self._valid(disabled)}

    def only_masked(self, enabled: FrozenSet[str],
                    prerequisites: Iterable[str] = ()) -> Dict[str, bool]:
        disabled = frozenset(set(self.all_keys) - set(enabled)
                             - set(prerequisites))
        return self.masked_strict(disabled)

    def disabled_masked(self, disabled: FrozenSet[str]) -> Dict[str, bool]:
        return self.masked(frozenset(disabled))

    def disabled_exposes(self, disabled: FrozenSet[str]) -> Dict[str, bool]:
        return self.exposes(frozenset(disabled))

    def observation(self, disabled: FrozenSet[str], case_id: str,
                    side: str) -> Dict[str, Any]:
        row = self.rows[frozenset(disabled)][side][case_id]
        return row["observation"]

    def snapshot_captured(self, disabled: FrozenSet[str], case_id: str,
                          side: str) -> bool:
        row = self.rows[frozenset(disabled)][side][case_id]
        return row.get("snap") is not None


def _build_matrix(task: Dict[str, Any], candidates: Sequence[Operation],
                  cases: Sequence[Tuple[str, Dict[str, Any]]],
                  counter: Dict[str, int]) -> _Matrix:
    source_plus = task["program"]["source"]
    source_minus = task["deletion"]["p_minus_source"]
    entry = task["entry"]
    target_line = int(task["program"]["target_A"]["line"])
    all_keys = tuple(op.key for op in candidates)

    plus_rows = _run_rows(source_plus, entry, cases, counter, capture_line=target_line)
    minus_rows = _run_rows(source_minus, entry, cases, counter, capture_line=target_line)

    def executed(observation: Sequence[Any]) -> bool:
        """An intervention observation exists even if the call raised.

        A raise is an observable outcome.  A legal *base* witness still has to
        return under P+; only the intervention rows may turn a return into a
        raise (that is exactly how some deletions are exposed).
        """
        return observation[0] in ("return", "raise")

    def executed_pair(p: Dict[str, Any], m: Dict[str, Any], cid: str) -> bool:
        return (executed(p[cid]["observation"])
                and executed(m[cid]["observation"]))

    def valid_pair(p: Dict[str, Any], m: Dict[str, Any], cid: str) -> bool:
        # Base rows: the input must be legal under P+, i.e. P+ returns.
        # P- is allowed to raise, which is one form of exposure.
        return (p[cid]["observation"][0] == "return"
                and executed(m[cid]["observation"]))

    def equal_pair(p: Dict[str, Any], m: Dict[str, Any], cid: str) -> bool:
        return p[cid]["observation"] == m[cid]["observation"]

    base_valid = {cid: valid_pair(plus_rows, minus_rows, cid) for cid, _ in cases}
    base_equal = {
        cid: base_valid[cid] and equal_pair(plus_rows, minus_rows, cid)
        for cid, _ in cases
    }
    local_effect = {
        cid: (base_valid[cid]
              and plus_rows[cid]["snap"] is not None
              and minus_rows[cid]["snap"] is not None
              and plus_rows[cid]["snap"] != minus_rows[cid]["snap"])
        for cid, _ in cases
    }

    rows: Dict[FrozenSet[str], Dict[str, Any]] = {}
    rows[frozenset()] = {
        "plus": plus_rows, "minus": minus_rows,
        "equal": {cid: equal_pair(plus_rows, minus_rows, cid) for cid, _ in cases},
        "valid": base_valid,
    }
    for disabled in engine.subsets(all_keys):
        if not disabled:
            continue
        counter["variants"] += 2
        plus_variant = disable_operations(source_plus, candidates, disabled)
        minus_variant = disable_operations(source_minus, candidates, disabled)
        p = _run_rows(plus_variant, entry, cases, counter)
        m = _run_rows(minus_variant, entry, cases, counter)
        rows[disabled] = {
            "plus": p, "minus": m,
            "equal": {cid: equal_pair(p, m, cid) for cid, _ in cases},
            "valid": {cid: executed_pair(p, m, cid) for cid, _ in cases},
        }
    return _Matrix(all_keys, rows, base_equal, local_effect)


# ---------------------------------------------------------------------------
# Condition synthesis and independent checking
# ---------------------------------------------------------------------------

def _atom_values(cases: Sequence[Tuple[str, Dict[str, Any]]],
                 arg_names: Sequence[str]) -> Dict[str, List[Any]]:
    values: Dict[str, List[Any]] = {}
    for name in arg_names:
        vals = []
        for _, args in cases:
            v = args.get(name)
            if isinstance(v, (bool, int)) and not isinstance(v, float):
                if v not in vals:
                    vals.append(v)
        if vals:
            values[name] = sorted(vals)
    return values


def _const(value: Any) -> str:
    """Format an int/bool for the restricted guard language."""
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, int):
        # The guard checker has no unary minus; keep negative constants as a
        # subtraction term instead of emitting ``-1``.
        return str(value) if value >= 0 else f"(0 - {abs(value)})"
    raise TypeError(f"unsupported constant {value!r}")


def _atoms(cases: Sequence[Tuple[str, Dict[str, Any]]],
           arg_names: Sequence[str]) -> List[str]:
    values = _atom_values(cases, arg_names)
    out: List[str] = []
    for name, vals in values.items():
        for v in vals:
            out.append(f"{name} == {_const(v)}")
            out.append(f"{name} != {_const(v)}")
        for v in vals:
            out.append(f"{name} <= {_const(v)}")
            out.append(f"{name} < {_const(v)}")
            out.append(f"{name} >= {_const(v)}")
            out.append(f"{name} > {_const(v)}")
    # Preserve order, drop duplicates.
    seen: Set[str] = set()
    unique: List[str] = []
    for atom in out:
        if atom not in seen:
            seen.add(atom)
            unique.append(atom)
    return unique


def _eval_atom(atom: str, arg_names: Sequence[str],
               args: Dict[str, Any]) -> bool:
    return bool(engine.eval_guard(atom, arg_names, args))


def _tree_expr(node: Any) -> str:
    if isinstance(node, bool):
        return "True" if node else "False"
    atom, left, right = node
    ls = _tree_expr(left)
    rs = _tree_expr(right)
    if ls == "True" and rs == "False":
        return f"({atom})"
    if ls == "False" and rs == "True":
        return f"(not ({atom}))"
    if ls == "True":
        return f"(({atom}) or {rs})"
    if rs == "True":
        return f"((not ({atom})) or {ls})"
    if ls == "False":
        return f"((not ({atom})) and {rs})"
    if rs == "False":
        return f"(({atom}) and {ls})"
    return f"((({atom}) and {ls}) or ((not ({atom})) and {rs}))"


def _exact(expr: str, cases: Sequence[Tuple[str, Dict[str, Any]]],
           arg_names: Sequence[str], labels: Dict[str, bool]) -> bool:
    try:
        engine.validate_guard(expr, arg_names)
    except Exception:  # noqa: BLE001
        return False
    for cid, args in cases:
        try:
            if _eval_atom(expr, arg_names, args) != labels[cid]:
                return False
        except Exception:  # noqa: BLE001
            return False
    return True


def _fallback_dnf(cases: Sequence[Tuple[str, Dict[str, Any]]],
                  arg_names: Sequence[str], labels: Dict[str, bool]) -> Optional[str]:
    positives = [(cid, args) for cid, args in cases if labels[cid]]
    if not positives:
        return "False"
    terms: List[str] = []
    for _, args in positives:
        parts: List[str] = []
        for name in arg_names:
            value = args.get(name)
            if not isinstance(value, (bool, int)):
                return None
            parts.append(f"{name} == {_const(value)}")
        terms.append(" and ".join(parts) if parts else "True")
    expr = " or ".join(f"({term})" for term in terms)
    if len(expr) > 4000:
        return None
    return expr


def synthesize_condition(cases: Sequence[Tuple[str, Dict[str, Any]]],
                         arg_names: Sequence[str],
                         labels: Dict[str, bool]) -> Optional[str]:
    """Return a boolean expression that fits ``labels`` on the finite domain.

    A decision tree is tried first; a canonical per-case DNF is the exact
    fallback.  The result is accepted only after evaluating it on every case,
    never merely because it is true on one witness.
    """
    if not cases:
        return None
    if all(labels[cid] for cid, _ in cases):
        return "True"
    if not any(labels[cid] for cid, _ in cases):
        return "False"

    atoms = _atoms(cases, arg_names)
    vectors: Dict[str, Tuple[bool, ...]] = {}
    for atom in atoms:
        try:
            vec = tuple(_eval_atom(atom, arg_names, args) for _, args in cases)
        except Exception:  # noqa: BLE001
            continue
        if any(vec) and not all(vec):
            vectors[atom] = vec

    labels_tuple = tuple(labels[cid] for cid, _ in cases)

    def build(indices: List[int], depth: int) -> Any:
        ys = {labels_tuple[i] for i in indices}
        if len(ys) == 1:
            return next(iter(ys))
        if depth >= 24 or not vectors:
            return sum(labels_tuple[i] for i in indices) * 2 >= len(indices)
        best = None
        for atom, vec in vectors.items():
            left = [i for i in indices if vec[i]]
            right = [i for i in indices if not vec[i]]
            if not left or not right:
                continue
            def impurity(group: List[int]) -> float:
                if not group:
                    return 0.0
                p = sum(labels_tuple[i] for i in group) / len(group)
                return 2.0 * p * (1.0 - p)
            score = (impurity(left) * len(left) + impurity(right) * len(right)) / len(indices)
            rank = (score, len(atom), atom)
            if best is None or rank < best[0]:
                best = (rank, atom, left, right)
        if best is None:
            return sum(labels_tuple[i] for i in indices) * 2 >= len(indices)
        _, atom, left, right = best
        return (atom, build(left, depth + 1), build(right, depth + 1))

    tree = build(list(range(len(cases))), 0)
    if isinstance(tree, bool):
        expr = "True" if tree else "False"
    else:
        expr = _tree_expr(tree)
    if _exact(expr, cases, arg_names, labels):
        return expr

    fallback = _fallback_dnf(cases, arg_names, labels)
    if fallback is not None and _exact(fallback, cases, arg_names, labels):
        return fallback
    return None


def check_condition(condition: Optional[str],
                    cases: Sequence[Tuple[str, Dict[str, Any]]],
                    arg_names: Sequence[str],
                    labels: Dict[str, bool],
                    witness_case: str) -> Dict[str, Any]:
    """Check soundness and exactness on the whole finite domain."""
    if not condition or not condition.strip():
        return {"status": "ABSENT", "sound": False, "complete": False,
                "exact": False, "false_accept": [], "false_reject": []}
    try:
        engine.validate_guard(condition, arg_names)
    except Exception as exc:  # noqa: BLE001
        return {"status": "INVALID", "error": f"{type(exc).__name__}: {exc}",
                "sound": False, "complete": False, "exact": False,
                "false_accept": [], "false_reject": []}

    predicted: Dict[str, bool] = {}
    errors: List[str] = []
    for cid, args in cases:
        try:
            predicted[cid] = _eval_atom(condition, arg_names, args)
        except Exception as exc:  # noqa: BLE001
            errors.append(f"{cid}: {type(exc).__name__}: {exc}")
    if errors:
        return {"status": "INVALID", "errors": errors[:3],
                "sound": False, "complete": False, "exact": False,
                "false_accept": [], "false_reject": []}

    false_accept = [cid for cid, _ in cases
                    if predicted[cid] and not labels[cid]]
    false_reject = [cid for cid, _ in cases
                    if not predicted[cid] and labels[cid]]
    witness_value = predicted.get(witness_case)
    return {
        "status": "VALID",
        "sound": not false_accept,
        "complete": not false_reject,
        "exact": not false_accept and not false_reject,
        "false_accept": false_accept,
        "false_reject": false_reject,
        "witness_value": witness_value,
    }


# ---------------------------------------------------------------------------
# Relation discovery
# ---------------------------------------------------------------------------

def _proper_nonempty_subsets(keys: FrozenSet[str]) -> List[FrozenSet[str]]:
    out: List[FrozenSet[str]] = []
    ordered = sorted(keys)
    for r in range(1, len(ordered)):
        for combo in itertools.combinations(ordered, r):
            out.append(frozenset(combo))
    return out


def _relation_status(check: Dict[str, Any]) -> str:
    """Classify a witness-level relation without conflating failure modes.

    VERIFIED      execution checks pass and the condition is exact on the
                  finite domain;
    WITNESS_ONLY  execution checks pass, but the condition is absent,
                  incomplete, or unsound on the finite domain;
    FALSE         the relation does not hold even on the named witness;
    INVALID       the condition language is malformed;
    UNVERIFIED    execution could not decide the witness.
    """
    state = check.get("status")
    if state == "INVALID":
        return "INVALID"
    if state == "ABSENT":
        return "WITNESS_ONLY"
    if check.get("witness_value") is None:
        return "UNVERIFIED"
    if not check.get("witness_value"):
        return "FALSE"
    if check.get("exact"):
        return "VERIFIED"
    return "WITNESS_ONLY"


def _condition_status(check: Dict[str, Any]) -> str:
    state = check.get("status")
    if state == "ABSENT":
        # No condition could be synthesized from the legal domain.  The
        # witness may still be valid; the condition is explicitly UNKNOWN.
        return "UNKNOWN"
    if state == "INVALID":
        return "INVALID"
    if check.get("exact"):
        return "EXACT"
    if check.get("sound"):
        return "SOUND_INCOMPLETE"
    return "UNSOUND"


def _observation_record(observation: Sequence[Any]) -> Dict[str, Any]:
    """Normalize one engine observation for the evidence record."""
    if not observation:
        return {"outcome": "missing"}
    if observation[0] == "return":
        return {"outcome": "return",
                "value": observation[1] if len(observation) > 1 else None}
    if observation[0] == "raise":
        return {"outcome": "raise",
                "exception": observation[1] if len(observation) > 1 else None,
                "message": observation[2] if len(observation) > 2 else None}
    return {"outcome": str(observation[0])}


def _discover_relations(matrix: _Matrix,
                        candidates: Sequence[Operation],
                        cases: Sequence[Tuple[str, Dict[str, Any]]],
                        arg_names: Sequence[str]) -> List[Relation]:
    by_key = {op.key: op for op in candidates}
    all_keys = frozenset(matrix.all_keys)
    relations: List[Relation] = []

    def control_prerequisites(keys: FrozenSet[str]) -> FrozenSet[str]:
        """Candidates that *define a branch condition* used by ``keys``.

        These are not alternative masking paths; disabling them prevents the
        claimed operation from being reached or executed.  The sufficiency
        check ("only this set is enabled") must keep them enabled.  This is
        the C-changes-state / B-is-controlled-by-C case: C is a prerequisite
        of B, not a masker that B competes with.
        """
        needed: Set[str] = set()
        frontier: Set[str] = set()
        for key in keys:
            frontier |= set(by_key[key].control_reads)
        changed = True
        while changed:
            changed = False
            for key, op in by_key.items():
                if key in keys or key in needed:
                    continue
                if op.writes & frontier:
                    needed.add(key)
                    frontier |= set(op.control_reads)
                    changed = True
        return frozenset(needed)

    for size in range(1, len(all_keys) + 1):
        for combo in itertools.combinations(sorted(all_keys), size):
            s = frozenset(combo)
            prereqs = control_prerequisites(s)
            only = matrix.only_masked(s, prereqs)
            exposes = matrix.disabled_exposes(s)
            proper = _proper_nonempty_subsets(s)
            proper_only = {
                t: matrix.only_masked(t, control_prerequisites(t))
                for t in proper
            }
            proper_disabled = {t: matrix.disabled_masked(t) for t in proper}

            for kind in ("independent", "cooperative", "coexisting"):
                if kind == "independent" and size != 1:
                    continue
                if kind in ("cooperative", "coexisting") and size < 2:
                    continue

                valid_cases: List[str] = []
                for cid, _ in cases:
                    if not matrix.base_equal[cid] or not matrix.local_effect[cid]:
                        continue
                    if kind in ("independent", "cooperative"):
                        ok = only[cid] and exposes[cid]
                        if ok:
                            ok = all(not proper_only[t][cid] for t in proper)
                    else:  # coexisting
                        ok = exposes[cid]
                        if ok:
                            ok = all(proper_disabled[t][cid] for t in proper)
                    if ok:
                        valid_cases.append(cid)
                if not valid_cases:
                    continue

                witness = valid_cases[0]
                witness_input = dict(next(args for cid, args in cases if cid == witness))
                if kind in ("independent", "cooperative"):
                    labels = {cid: only[cid] for cid, _ in cases}
                else:
                    labels = {cid: exposes[cid] for cid, _ in cases}
                condition = synthesize_condition(cases, arg_names, labels)
                check = check_condition(condition, cases, arg_names, labels, witness)

                checks: Dict[str, Any] = {
                    "a_has_local_effect": bool(matrix.local_effect[witness]),
                    "original_masks": bool(matrix.base_equal[witness]),
                }
                if kind in ("independent", "cooperative"):
                    checks["only_set_masks"] = bool(only[witness])
                    checks["disabling_set_exposes"] = bool(exposes[witness])
                    checks["proper_subsets_do_not_mask"] = {
                        ",".join(sorted(t)): not bool(proper_only[t][witness])
                        for t in proper
                    }
                else:
                    checks["disabling_set_exposes"] = bool(exposes[witness])
                    checks["proper_subsets_do_not_expose"] = {
                        ",".join(sorted(t)): bool(proper_disabled[t][witness])
                        for t in proper
                    }

                complement = frozenset(all_keys - s - prereqs)
                if kind in ("independent", "cooperative"):
                    minimality_type = "proper_nonempty_subsets_do_not_mask"
                    minimality_holds = all(
                        not proper_only[t][witness] for t in proper)
                    minimality_results = {
                        ",".join(sorted(t)): {
                            "masks": bool(proper_only[t][witness]),
                            "disabled_keys": sorted(
                                all_keys - t - control_prerequisites(t)),
                            "kept_prerequisites": sorted(
                                control_prerequisites(t)),
                        }
                        for t in sorted(proper, key=lambda x: (len(x), sorted(x)))
                    }
                else:
                    minimality_type = "proper_nonempty_subsets_do_not_expose"
                    minimality_holds = all(
                        proper_disabled[t][witness] for t in proper)
                    minimality_results = {
                        ",".join(sorted(t)): {
                            "exposes": bool(proper_disabled[t][witness]),
                            "disabled_keys": sorted(t),
                        }
                        for t in sorted(proper, key=lambda x: (len(x), sorted(x)))
                    }
                evidence = {
                    "scope": "witness_case_only; finite legal domain used for condition checks",
                    "witness_case": witness,
                    "witness_input": witness_input,
                    "witness_legal_under_p_plus": (
                        matrix.rows[frozenset()]["plus"][witness]["observation"][0]
                        == "return"),
                    "p_plus": _observation_record(
                        matrix.observation(frozenset(), witness, "plus")),
                    "p_minus": _observation_record(
                        matrix.observation(frozenset(), witness, "minus")),
                    "p_plus_snapshot_at_target": matrix.snapshot_captured(
                        frozenset(), witness, "plus"),
                    "p_minus_snapshot_at_target": matrix.snapshot_captured(
                        frozenset(), witness, "minus"),
                    "deletion_without_intervention": {
                        "masked": bool(matrix.base_equal[witness]),
                        "a_has_local_effect": bool(matrix.local_effect[witness]),
                    },
                    "intervention": {
                        "disable_other_masking_candidates": {
                            "disabled_keys": sorted(complement),
                            "kept_prerequisites": sorted(prereqs),
                            "masked": bool(only[witness]),
                        },
                        "disable_claimed_set": {
                            "disabled_keys": sorted(s),
                            "exposes": bool(exposes[witness]),
                            "p_plus": _observation_record(
                                matrix.observation(s, witness, "plus")),
                            "p_minus": _observation_record(
                                matrix.observation(s, witness, "minus")),
                        },
                    },
                    "minimality": {
                        "criterion": minimality_type,
                        "holds_on_witness": bool(minimality_holds),
                        "results": minimality_results,
                    },
                }
                relations.append(Relation(
                    kind=kind,
                    operations=tuple(sorted((by_key[k] for k in s),
                                            key=lambda op: (op.line, op.col))),
                    witness_case=witness,
                    witness_input=witness_input,
                    condition=condition,
                    condition_check=check,
                    checks=checks,
                    status=_relation_status(check),
                    condition_status=_condition_status(check),
                    evidence=evidence,
                ))

    order = {"independent": 0, "cooperative": 1, "coexisting": 2}
    relations.sort(key=lambda r: (order[r.kind], len(r.operations),
                                  tuple(op.line for op in r.operations)))
    return relations


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------

def _cases(task: Dict[str, Any]) -> List[Tuple[str, Dict[str, Any]]]:
    raw = task["input_domain"]["cases"]
    return [(f"case_{i:04d}", {k: v for k, v in c.items() if k != "id"})
            for i, c in enumerate(raw)]


def _operation_for_line(source: str, entry: str, line: int) -> Optional[Operation]:
    """Map a contract-cited line to the smallest enclosing candidate node."""
    tree = ast.parse(source)
    func = _find_function(tree, entry)
    best: Optional[ast.stmt] = None
    for node in ast.walk(func):
        if not isinstance(node, ast.stmt):
            continue
        start = int(getattr(node, "lineno", -1))
        end = int(getattr(node, "end_lineno", start))
        if not (start <= line <= end):
            continue
        if isinstance(node, (ast.Return, ast.FunctionDef,
                             ast.AsyncFunctionDef, ast.ClassDef)):
            continue
        if best is None or (start, end) > (int(best.lineno), int(getattr(best, "end_lineno", best.lineno))):
            best = node
    if best is None:
        return None
    try:
        return _candidate_operation(best, source)
    except UnsupportedProgram:
        return None


def _merge_contract_candidates(
        candidates: Sequence[Operation], source: str, entry: str,
        target_line: int, contract_lines: Sequence[int],
        contract_meta: Dict[str, Any], limit: int
) -> Tuple[List[Operation], Dict[str, Any]]:
    """Add contract-cited operations, never beyond the shared candidate budget.

    A contract line is only a *proposal*.  The execution verifier still has to
    confirm the relation.  Baseline candidates keep priority so the comparison
    cannot gain merely by expanding the search space.
    """
    by_key = {op.key: op for op in candidates}
    ordered = list(candidates)
    cited: List[int] = []
    mapped: List[int] = []
    unmapped: List[int] = []
    added_keys: List[str] = []
    refs_for_key: Dict[str, List[str]] = {}
    refs = contract_meta.get("line_refs") or {}
    for raw_line in contract_lines:
        line = int(raw_line)
        if line <= target_line or line in cited:
            continue
        cited.append(line)
        op = _operation_for_line(source, entry, line)
        if op is None:
            unmapped.append(line)
            continue
        mapped.append(line)
        refs_for_key.setdefault(op.key, [])
        refs_for_key[op.key].extend(refs.get(str(line), refs.get(line, [])))
        if op.key in by_key:
            existing = by_key[op.key]
            merged_refs = tuple(sorted(set(existing.contract_refs) |
                                       set(refs_for_key[op.key])))
            updated = replace(existing, contract_refs=merged_refs)
            by_key[op.key] = updated
            ordered = [updated if item.key == op.key else item for item in ordered]
        else:
            if len(ordered) >= limit:
                continue
            updated = replace(op, contract_refs=tuple(sorted(set(refs_for_key[op.key]))))
            by_key[op.key] = updated
            ordered.append(updated)
            added_keys.append(op.key)
    ordered = sorted(ordered, key=lambda op: (op.line, op.col))
    meta = {
        "cited_lines": cited,
        "mapped_lines": mapped,
        "unmapped_lines": unmapped,
        "added_keys": added_keys,
        "added_lines": [by_key[k].line for k in added_keys],
        "candidate_limit": limit,
        "baseline_count": len(candidates),
        "selected_count": len(ordered),
        "lines": {str(line): refs.get(str(line), refs.get(line, []))
                  for line in cited},
    }
    return ordered, meta


def _run_from_candidates(task: Dict[str, Any], candidates: Sequence[Operation],
                         unsupported: Sequence[str], counter: Dict[str, int],
                         started: float, candidate_source: str,
                         contract: Optional[Dict[str, Any]] = None,
                         budget: Optional[Dict[str, Any]] = None
                         ) -> DiscoveryResult:
    task_id = task.get("task_id", "(unnamed)")
    target_line = int(task["program"]["target_A"]["line"])
    entry = task["entry"]
    cases = _cases(task)
    arg_names = [a["name"] for a in task["input_domain"]["args"]]
    unsupported_list = list(unsupported)
    counter["wall_seconds"] = round(time.perf_counter() - started, 3)

    if not cases:
        return DiscoveryResult(task_id, "UNSUPPORTED", "empty legal domain",
                               target_line, stats=counter,
                               candidate_source=candidate_source,
                               contract=contract or {}, budget=budget or {},
                               unsupported=tuple(unsupported_list))
    if not candidates:
        reason = "no downstream operation writes a live output variable"
        if unsupported_list:
            reason += "; unsupported constructs: " + "; ".join(unsupported_list[:3])
        return DiscoveryResult(task_id, "UNKNOWN", reason, target_line,
                               stats=counter, candidate_source=candidate_source,
                               contract=contract or {}, budget=budget or {},
                               unsupported=tuple(unsupported_list))
    if len(candidates) > MAX_CANDIDATES:
        reason = (f"{len(candidates)} candidates exceed MAX_CANDIDATES="
                  f"{MAX_CANDIDATES}; subset enumeration would be too large")
        counter["wall_seconds"] = round(time.perf_counter() - started, 3)
        return DiscoveryResult(task_id, "UNSUPPORTED", reason, target_line,
                               candidates=tuple(candidates), stats=counter,
                               candidate_source=candidate_source,
                               contract=contract or {}, budget=budget or {},
                               unsupported=tuple(unsupported_list + [reason]))

    try:
        matrix = _build_matrix(task, candidates, cases, counter)
        relations = _discover_relations(matrix, candidates, cases, arg_names)
    except UnsupportedProgram as exc:
        counter["wall_seconds"] = round(time.perf_counter() - started, 3)
        return DiscoveryResult(task_id, "UNSUPPORTED", str(exc), target_line,
                               candidates=tuple(candidates), stats=counter,
                               candidate_source=candidate_source,
                               contract=contract or {}, budget=budget or {},
                               unsupported=tuple(unsupported_list + [str(exc)]))

    counter["subsets"] = len(matrix.rows)
    counter["candidates"] = len(candidates)
    counter["wall_seconds"] = round(time.perf_counter() - started, 3)
    verified = [r for r in relations if r.status == "VERIFIED"]
    if not relations:
        if unsupported_list:
            # Candidate extraction skipped statements that could carry the
            # masking write (loops, try/with, ...).  No relation is not the
            # same as "no relation exists"; report the structure as
            # unsupported instead of silently returning UNKNOWN.
            status = "UNSUPPORTED"
            reason = ("no relation among supported candidates; unsupported "
                      "constructs were not searched: " +
                      "; ".join(unsupported_list[:3]))
        else:
            status = "UNKNOWN"
            reason = "no relation satisfied the witness and minimality checks"
    elif len(verified) == len(relations):
        status = "OK"
        reason = "all discovered relations have exact conditions on the finite domain"
    else:
        status = "PARTIAL"
        reason = "some relations lack an exact condition or a valid witness"
    if unsupported_list:
        if status == "OK":
            status = "PARTIAL"
        reason += "; unsupported constructs were not searched: " + \
                  "; ".join(unsupported_list[:3])
    return DiscoveryResult(task_id, status, reason, target_line,
                           candidates=tuple(candidates),
                           relations=tuple(relations), stats=counter,
                           candidate_source=candidate_source,
                           contract=contract or {}, budget=budget or {},
                           unsupported=tuple(unsupported_list))


def discover(task: Dict[str, Any]) -> DiscoveryResult:
    """Discover operation-level masking relations for one controlled task.

    This is the original top-level backward-slice baseline.  It is kept
    unchanged for the old development fixtures.  ``discover_expanded`` adds
    nested and indirect-state candidates.
    """
    started = time.perf_counter()
    target_line = int(task["program"]["target_A"]["line"])
    entry = task["entry"]
    counter = {"compilations": 0, "case_executions": 0, "variants": 0}
    try:
        candidates, unsupported = find_candidates(
            task["program"]["source"], task["deletion"]["p_minus_source"],
            entry, target_line)
    except UnsupportedProgram as exc:
        counter["wall_seconds"] = round(time.perf_counter() - started, 3)
        return DiscoveryResult(task.get("task_id", "(unnamed)"), "UNSUPPORTED",
                               str(exc), target_line, stats=counter,
                               unsupported=(str(exc),))
    return _run_from_candidates(task, candidates, unsupported, counter, started,
                                "ast_backward_slice", budget={
                                    "candidate_limit": MAX_CANDIDATES,
                                    "candidate_count": len(candidates),
                                })


def discover_expanded(task: Dict[str, Any],
                      contract_lines: Optional[Sequence[int]] = None,
                      contract_meta: Optional[Dict[str, Any]] = None
                      ) -> DiscoveryResult:
    """Discover from nested/control/indirect-state candidates.

    ``contract_lines`` is optional.  When present, it is a proposal source from
    MACE semantic contracts; candidate selection stays within the same
    candidate budget as the no-contract run.
    """
    started = time.perf_counter()
    target_line = int(task["program"]["target_A"]["line"])
    entry = task["entry"]
    counter = {"compilations": 0, "case_executions": 0, "variants": 0}
    try:
        candidates, unsupported = find_candidates_expanded(
            task["program"]["source"], task["deletion"]["p_minus_source"],
            entry, target_line)
    except UnsupportedProgram as exc:
        counter["wall_seconds"] = round(time.perf_counter() - started, 3)
        return DiscoveryResult(task.get("task_id", "(unnamed)"), "UNSUPPORTED",
                               str(exc), target_line, stats=counter,
                               candidate_source="expanded_ast",
                               unsupported=(str(exc),))
    budget = {
        "candidate_limit": MAX_CANDIDATES,
        "baseline_candidate_count": len(candidates),
        "selected_candidate_count": len(candidates),
        "candidate_count_matched": True,
    }
    contract_record: Dict[str, Any] = {}
    if contract_lines is not None:
        # The contract-assisted arm is not allowed more candidates, and thus
        # not more subset executions, than the no-contract arm on this task.
        limit = len(candidates)
        candidates, merge_meta = _merge_contract_candidates(
            candidates, task["program"]["source"], entry, target_line,
            contract_lines, contract_meta or {}, limit)
        contract_record = dict(contract_meta or {})
        contract_record.update(merge_meta)
        contract_record["candidate_limit_matched_to_baseline"] = True
        contract_record["added_verified_relations"] = 0  # filled after checks
        budget["selected_candidate_count"] = len(candidates)
        budget["candidate_count_matched"] = len(candidates) == budget[
            "baseline_candidate_count"]
    result = _run_from_candidates(
        task, candidates, unsupported, counter, started,
        "expanded_ast_with_mace_contracts" if contract_lines is not None
        else "expanded_ast",
        contract=contract_record, budget=budget)
    return result


def to_submission(result: DiscoveryResult) -> Dict[str, Any]:
    """Convert discovered relations to the open submission shape.

    Used only after discovery, for the independent benchmark ``Verifier``.
    """
    relations = []
    for rel in result.relations:
        relations.append({
            "operations": [{"line": op.line, "text": op.text}
                           for op in rel.operations],
            "kind": rel.kind,
            "input": rel.witness_input,
            "condition": rel.condition or "",
            "explanation": (
                f"deterministic {rel.kind} relation over lines "
                f"{', '.join(str(op.line) for op in rel.operations)}"
            ),
            "counterexample": None,
        })
    return {"relations": relations}
