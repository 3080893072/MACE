"""Independent verifier v2 for operation-level masking tasks.

This module is evaluation infrastructure, not part of the MACE algorithm.  It
re-executes P+ and P- under explicit statement-line interventions and checks
single-witness claims.  It deliberately does not import ``mace``.

Two limits are explicit:

* A relation result is a *single-witness* result.  It never claims to be
  exhaustive over all inputs, and ``verify_guard_domain`` is the only API that
  reports sound/complete/exact over a supplied finite case set.
* Model-supplied Guard expressions are evaluated by a small AST interpreter
  over int/bool values.  No ``eval`` is used for guards.
"""
from __future__ import annotations

import ast
import itertools
import sys
import traceback
from dataclasses import dataclass, field
from typing import Any, Dict, FrozenSet, Iterable, List, Mapping, Optional, Sequence, Tuple


class VerificationError(RuntimeError):
    """Base class for verifier input errors."""


class InterventionError(VerificationError):
    """An operation line cannot be disabled without changing the task."""


class GuardError(VerificationError):
    """A Guard expression is malformed, unsupported, or raises."""


# ---------------------------------------------------------------------------
# Canonical observations
# ---------------------------------------------------------------------------

def canonical(value: Any) -> Any:
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
        return ["dict", sorted((canonical(k), canonical(v)) for k, v in value.items())]
    if isinstance(value, (set, frozenset)):
        return ["set", sorted(canonical(v) for v in value)]
    return ["obj", f"{type(value).__name__}:{value!r}"]


def exception_signature(exc: BaseException) -> str:
    return f"{type(exc).__name__}: {exc}"


# ---------------------------------------------------------------------------
# Source / operation-line handling
# ---------------------------------------------------------------------------

_SIMPLE_STATEMENTS = (
    ast.Assign, ast.AnnAssign, ast.AugAssign, ast.Expr, ast.Return,
    ast.Raise, ast.Pass, ast.Delete,
)


@dataclass(frozen=True)
class Operation:
    name: str
    line: int
    node_type: str
    spans_lines: bool


def _statement_at_line(source: str, line: int) -> ast.stmt:
    tree = ast.parse(source)
    candidates = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.stmt) and getattr(node, "lineno", None) == line
    ]
    if not candidates:
        raise InterventionError(f"line {line} has no statement")
    if len(candidates) != 1:
        raise InterventionError(
            f"line {line} contains {len(candidates)} statements; "
            "operation lines must be unambiguous")
    node = candidates[0]
    if not isinstance(node, _SIMPLE_STATEMENTS + (ast.If,)):
        raise InterventionError(
            f"line {line} is {type(node).__name__}; only simple statements "
            "and If are accepted as operation lines")
    spans = getattr(node, "end_lineno", line) != line
    if spans and not isinstance(node, ast.If):
        raise InterventionError(
            f"line {line} is a multi-line {type(node).__name__}; "
            "operation disabling would replace more than one statement")
    return node


def resolve_operations(source: str, ops: Mapping[str, int],
                       target_line: Optional[int] = None) -> Dict[str, Operation]:
    """Validate an explicit operation-name -> source-line map."""
    if not ops:
        return {}
    names = list(ops)
    lines = [int(ops[name]) for name in names]
    if len(set(names)) != len(names):
        raise InterventionError("duplicate operation names")
    if len(set(lines)) != len(lines):
        raise InterventionError("two operations share one source line")
    if target_line is not None and target_line in lines:
        raise InterventionError("target A line cannot also be an operation line")
    out: Dict[str, Operation] = {}
    for name, line in zip(names, lines):
        node = _statement_at_line(source, line)
        out[name] = Operation(
            name=name,
            line=line,
            node_type=type(node).__name__,
            spans_lines=getattr(node, "end_lineno", line) != line,
        )
    return out


def disable_statement_lines(source: str, lines: Iterable[int]) -> str:
    """Replace the statements whose ``lineno`` is in ``lines`` with ``pass``.

    The source is re-parsed for every call.  An empty set returns the source
    unchanged, preserving line numbers and comments.
    """
    wanted = {int(line) for line in lines}
    if not wanted:
        return source
    tree = ast.parse(source)
    by_line: Dict[int, ast.stmt] = {}
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and getattr(node, "lineno", None) in wanted:
            line = int(node.lineno)
            if line in by_line:
                raise InterventionError(
                    f"line {line} contains more than one statement")
            by_line[line] = node
    missing = sorted(wanted - set(by_line))
    if missing:
        raise InterventionError(f"no statement on operation line(s) {missing}")

    class Disable(ast.NodeTransformer):
        def visit(self, node: ast.AST):  # noqa: ANN001 - ast API
            if isinstance(node, ast.stmt) and getattr(node, "lineno", None) in wanted:
                return ast.copy_location(ast.Pass(), node)
            return super().visit(node)

    tree = Disable().visit(tree)
    tree = ast.fix_missing_locations(tree)
    return ast.unparse(tree) + "\n"


def variant_source(source: str, disabled_lines: Iterable[int]) -> str:
    return disable_statement_lines(source, disabled_lines)


def replace_line_with_pass(source: str, line: int) -> str:
    """Delete one target statement while preserving every line number."""
    _statement_at_line(source, line)
    lines = source.splitlines(keepends=True)
    original = lines[line - 1]
    indent = original[: len(original) - len(original.lstrip())]
    lines[line - 1] = indent + "pass  # P-: target A deleted\n"
    return "".join(lines)


# ---------------------------------------------------------------------------
# Execution
# ---------------------------------------------------------------------------

@dataclass
class CallResult:
    ok: bool
    observation: Any
    exception: Optional[str]
    target_hit: bool
    traceback: Optional[str] = None


class Program:
    """A compiled task source with an explicit entry function."""

    def __init__(self, source: str, entry: str = "program",
                 filename: Optional[str] = None):
        self.source = source
        self.entry = entry
        self.filename = filename or f"<verifier-v2:{id(self):x}>"
        tree = ast.parse(source)
        self.namespace: Dict[str, Any] = {}
        exec(compile(tree, self.filename, "exec"), self.namespace)  # noqa: S102
        if entry not in self.namespace or not callable(self.namespace[entry]):
            raise VerificationError(f"entry {entry!r} is not callable")

    def call(self, args: Mapping[str, Any], trace_line: Optional[int] = None) -> CallResult:
        hit = [False]

        def tracer(frame, event, arg):  # noqa: ANN001 - trace API
            if (event == "line" and trace_line is not None
                    and frame.f_code.co_filename == self.filename
                    and frame.f_lineno == trace_line):
                hit[0] = True
            return tracer

        fn = self.namespace[self.entry]
        old_trace = sys.gettrace()
        if trace_line is not None:
            sys.settrace(tracer)
        try:
            value = fn(**dict(args))
            return CallResult(True, ["return", canonical(value)], None, hit[0])
        except Exception as exc:  # noqa: BLE001 - an exception is an observation
            return CallResult(
                False,
                ["raise", exception_signature(exc)],
                exception_signature(exc),
                hit[0],
                traceback.format_exc(limit=6),
            )
        finally:
            sys.settrace(old_trace)


# ---------------------------------------------------------------------------
# Legal inputs
# ---------------------------------------------------------------------------

@dataclass
class Case:
    case_id: str
    args: Dict[str, Any]


def validate_cases(cases: Sequence[Tuple[str, Mapping[str, Any]]],
                   arg_names: Sequence[str]) -> List[Case]:
    """Check shape and JSON-safety; execution-based legality is separate."""
    from json import dumps

    declared = list(arg_names)
    seen_ids = set()
    seen_args = set()
    out: List[Case] = []
    for item in cases:
        if not (isinstance(item, (tuple, list)) and len(item) == 2):
            raise VerificationError("each case must be (case_id, args)")
        case_id, raw_args = item
        if not isinstance(case_id, str) or not case_id:
            raise VerificationError("case_id must be a non-empty string")
        if case_id in seen_ids:
            raise VerificationError(f"duplicate case_id {case_id!r}")
        if not isinstance(raw_args, Mapping):
            raise VerificationError(f"case {case_id}: args must be a mapping")
        args = dict(raw_args)
        if set(args) != set(declared):
            raise VerificationError(
                f"case {case_id}: expected args {declared}, got {sorted(args)}")
        try:
            signature = dumps({k: canonical(v) for k, v in args.items()},
                              sort_keys=True, allow_nan=False)
        except (TypeError, ValueError) as exc:
            raise VerificationError(f"case {case_id}: args are not JSON-safe: {exc}") from None
        if signature in seen_args:
            raise VerificationError(f"case {case_id}: duplicate argument tuple")
        seen_ids.add(case_id)
        seen_args.add(signature)
        out.append(Case(case_id, args))
    if not out:
        raise VerificationError("at least one legal case is required")
    return out


# ---------------------------------------------------------------------------
# Intervention matrix
# ---------------------------------------------------------------------------

def subsets(names: Sequence[str]) -> List[FrozenSet[str]]:
    return [frozenset(c) for r in range(len(names) + 1)
            for c in itertools.combinations(names, r)]


@dataclass
class MatrixRow:
    case_id: str
    plus: CallResult
    minus: CallResult
    status: str

    @property
    def masked(self) -> bool:
        return self.status == "MASKED"

    @property
    def exposed(self) -> bool:
        return self.status == "EXPOSED"


@dataclass
class Matrix:
    ops: Tuple[str, ...]
    cases: Tuple[str, ...]
    op_map: Dict[str, Operation]
    rows: Dict[FrozenSet[str], Dict[str, MatrixRow]] = field(default_factory=dict)
    errors: Dict[FrozenSet[str], str] = field(default_factory=dict)
    base_target_hits: Dict[str, bool] = field(default_factory=dict)

    def subset_ok(self, disabled: FrozenSet[str]) -> bool:
        return disabled in self.rows and disabled not in self.errors

    def row(self, disabled: FrozenSet[str], case_id: str) -> Optional[MatrixRow]:
        if not self.subset_ok(disabled):
            return None
        return self.rows[disabled].get(case_id)

    def all_ops(self) -> FrozenSet[str]:
        return frozenset(self.ops)


def _classify(plus: CallResult, minus: CallResult) -> str:
    if not plus.ok:
        return "INVALID_INPUT"
    if not minus.ok:
        return "EXPOSED"
    if plus.observation == minus.observation:
        return "MASKED"
    return "EXPOSED"


def run_matrix(source_plus: str, source_minus: str,
               ops: Mapping[str, int], cases: Sequence[Case],
               entry: str = "program",
               target_line: Optional[int] = None,
               max_ops: int = 10) -> Matrix:
    """Execute every enable/disable subset for P+ and P-."""
    if len(ops) > max_ops:
        raise VerificationError(f"at most {max_ops} operations are supported")
    op_map = resolve_operations(source_plus, ops, target_line)
    names = tuple(sorted(op_map))
    matrix = Matrix(ops=names, cases=tuple(c.case_id for c in cases),
                    op_map=op_map)
    filename_plus = "<verifier-v2:plus>"
    filename_minus = "<verifier-v2:minus>"

    for disabled in subsets(names):
        try:
            plus_source = variant_source(source_plus, {op_map[n].line for n in disabled})
            minus_source = variant_source(source_minus, {op_map[n].line for n in disabled})
            plus_program = Program(plus_source, entry=entry, filename=filename_plus)
            minus_program = Program(minus_source, entry=entry, filename=filename_minus)
        except (InterventionError, SyntaxError, VerificationError) as exc:
            matrix.errors[disabled] = f"{type(exc).__name__}: {exc}"
            continue
        rows: Dict[str, MatrixRow] = {}
        for case in cases:
            plus = plus_program.call(case.args, target_line if not disabled else None)
            minus = minus_program.call(case.args, target_line if not disabled else None)
            rows[case.case_id] = MatrixRow(case.case_id, plus, minus,
                                           _classify(plus, minus))
        matrix.rows[disabled] = rows
        if not disabled:
            matrix.base_target_hits = {
                case.case_id: rows[case.case_id].plus.target_hit for case in cases
            }
    return matrix


# ---------------------------------------------------------------------------
# Relation verification
# ---------------------------------------------------------------------------

def _mini(matrix: Matrix, disabled: FrozenSet[str], case_id: str) -> str:
    if not matrix.subset_ok(disabled):
        return "ILLEGAL_INTERVENTION"
    row = matrix.row(disabled, case_id)
    if row is None:
        return "MISSING_CASE"
    return row.status


def verify_relation(matrix: Matrix, kind: str, ops: Iterable[str],
                    case_id: str) -> Dict[str, Any]:
    """Verify one claim on one witness.  Never reports domain-wide exactness."""
    claim = frozenset(ops)
    all_ops = matrix.all_ops()
    if case_id not in matrix.cases:
        return {"kind": kind, "valid": False, "status": "INVALID_WITNESS",
                "reason": "case is not in the supplied finite domain",
                "scope": "single_witness", "witness": case_id}
    if not claim <= all_ops:
        return {"kind": kind, "valid": False, "status": "UNKNOWN_OPERATION",
                "reason": "claim names an operation not in the task",
                "scope": "single_witness", "witness": case_id}
    if kind == "independent" and len(claim) != 1:
        return {"kind": kind, "valid": False, "status": "MALFORMED_CLAIM",
                "reason": "independent requires exactly one operation",
                "scope": "single_witness", "witness": case_id}
    if kind in ("cooperative", "coexisting") and len(claim) < 2:
        return {"kind": kind, "valid": False, "status": "MALFORMED_CLAIM",
                "reason": f"{kind} requires at least two operations",
                "scope": "single_witness", "witness": case_id}

    base = _mini(matrix, frozenset(), case_id)
    if base == "INVALID_INPUT":
        return {"kind": kind, "valid": False, "status": "INVALID_INPUT",
                "reason": "P+ raised on the witness; the input is not legal",
                "scope": "single_witness", "witness": case_id,
                "base_status": base}

    only_key = all_ops - claim          # only the claimed ops remain enabled
    disabled_key = claim                # the claimed ops are disabled
    only_status = _mini(matrix, only_key, case_id)
    disabled_status = _mini(matrix, disabled_key, case_id)
    checks: Dict[str, Any] = {
        "only_claim_status": only_status,
        "claim_disabled_status": disabled_status,
        "only_claim_masks": only_status == "MASKED",
        "claim_disabled_exposes": disabled_status == "EXPOSED",
    }
    if only_status == "ILLEGAL_INTERVENTION" or disabled_status == "ILLEGAL_INTERVENTION":
        return {"kind": kind, "valid": False, "status": "ILLEGAL_INTERVENTION",
                "reason": "a required intervention variant did not compile",
                "scope": "single_witness", "witness": case_id, "checks": checks}
    if only_status in ("INVALID_INPUT", "MISSING_CASE") or disabled_status in (
            "INVALID_INPUT", "MISSING_CASE"):
        return {"kind": kind, "valid": False, "status": "UNDECIDABLE",
                "reason": "a required variant raised or lost the witness",
                "scope": "single_witness", "witness": case_id, "checks": checks}

    proper = [
        s for s in subsets(sorted(claim))
        if 0 < len(s) < len(claim)
    ]
    minimality: Dict[str, Any] = {}
    minimal = True
    for sub in proper:
        if kind == "cooperative":
            status = _mini(matrix, all_ops - sub, case_id)
            minimality["+".join(sorted(sub))] = {
                "only_claim_status": status,
                "only_claim_masks": status == "MASKED",
            }
            if status == "MASKED":
                minimal = False
        else:
            status = _mini(matrix, sub, case_id)
            minimality["+".join(sorted(sub))] = {
                "claim_disabled_status": status,
                "claim_disabled_masks": status == "MASKED",
            }
            if status != "MASKED":
                minimal = False
        if status in ("ILLEGAL_INTERVENTION", "MISSING_CASE", "INVALID_INPUT"):
            return {"kind": kind, "valid": False, "status": "UNDECIDABLE",
                    "reason": "a proper-subset check was not decidable",
                    "scope": "single_witness", "witness": case_id,
                    "checks": checks, "minimality": minimality}
    checks["proper_subset_checks"] = minimality
    checks["minimal"] = minimal
    valid = checks["only_claim_masks"] and checks["claim_disabled_exposes"] and minimal
    status = "VERIFIED" if valid else "REJECTED"
    return {
        "kind": kind,
        "ops": sorted(claim),
        "witness": case_id,
        "scope": "single_witness",
        "valid": valid,
        "status": status,
        "minimal": minimal,
        "checks": checks,
        "note": ("This result is checked only on the named witness.  It is not "
                 "a proof over all inputs."),
    }


def discover_relations(matrix: Matrix, case_id: str) -> Dict[str, Any]:
    """Enumerate independent/cooperative/coexisting claims on one witness."""
    all_ops = matrix.all_ops()
    independent: List[Dict[str, Any]] = []
    cooperative: List[Dict[str, Any]] = []
    coexisting: List[Dict[str, Any]] = []
    undecidable: List[List[str]] = []
    for subset in subsets(sorted(all_ops)):
        if not subset:
            continue
        if not matrix.subset_ok(subset):
            undecidable.append(sorted(subset))
            continue
        if len(subset) == 1:
            result = verify_relation(matrix, "independent", subset, case_id)
            if result["valid"]:
                independent.append(result)
        else:
            coop = verify_relation(matrix, "cooperative", subset, case_id)
            if coop["valid"]:
                cooperative.append(coop)
            co = verify_relation(matrix, "coexisting", subset, case_id)
            if co["valid"]:
                coexisting.append(co)
    return {
        "witness": case_id,
        "scope": "single_witness",
        "independent": independent,
        "cooperative": cooperative,
        "coexisting": coexisting,
        "illegal_or_undecidable": undecidable,
    }


# ---------------------------------------------------------------------------
# Safe Guard interpreter
# ---------------------------------------------------------------------------

_ALLOWED_BOOL = (ast.And, ast.Or)
_ALLOWED_UNARY = (ast.Not, ast.USub, ast.UAdd)
_ALLOWED_BIN = (ast.Add, ast.Sub, ast.Mult, ast.FloorDiv, ast.Mod)
_ALLOWED_CMP = (ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)


def _guard_ast(expr: str) -> ast.Expression:
    if not isinstance(expr, str):
        raise GuardError(f"guard must be a string, not {type(expr).__name__}")
    try:
        tree = ast.parse(expr, mode="eval")
    except (SyntaxError, ValueError, TypeError) as exc:
        raise GuardError(f"syntax error: {exc}") from None
    count = 0
    for node in ast.walk(tree):
        count += 1
        if count > 200:
            raise GuardError("guard is too large")
        if isinstance(node, (ast.Call, ast.Attribute, ast.Subscript,
                             ast.Lambda, ast.ListComp, ast.SetComp,
                             ast.DictComp, ast.GeneratorExp, ast.NamedExpr)):
            raise GuardError(f"unsupported construct {type(node).__name__}")
        if isinstance(node, ast.Constant) and not isinstance(node.value, (int, bool)):
            raise GuardError("guard constants must be int or bool")
    return tree


def _int(value: Any, what: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise GuardError(f"{what} must be an int")
    return value


def _bool(value: Any, what: str) -> bool:
    if not isinstance(value, bool):
        raise GuardError(f"{what} must be a bool")
    return value


def _eval_node(node: ast.AST, args: Mapping[str, Any]) -> Any:
    if isinstance(node, ast.Constant):
        if isinstance(node.value, bool):
            return node.value
        if isinstance(node.value, int):
            return node.value
        raise GuardError("guard constants must be int or bool")
    if isinstance(node, ast.Name):
        if node.id not in args:
            raise GuardError(f"unknown argument {node.id!r}")
        value = args[node.id]
        if isinstance(value, bool):
            return value
        if isinstance(value, int):
            return value
        raise GuardError(f"argument {node.id!r} is not int/bool")
    if isinstance(node, ast.BoolOp):
        if isinstance(node.op, ast.And):
            left = _bool(_eval_node(node.values[0], args), "and operand")
            if not left:
                return False
            for child in node.values[1:]:
                if not _bool(_eval_node(child, args), "and operand"):
                    return False
            return True
        if isinstance(node.op, ast.Or):
            left = _bool(_eval_node(node.values[0], args), "or operand")
            if left:
                return True
            for child in node.values[1:]:
                if _bool(_eval_node(child, args), "or operand"):
                    return True
            return False
        raise GuardError(f"unsupported boolean operator {type(node.op).__name__}")
    if isinstance(node, ast.UnaryOp):
        value = _eval_node(node.operand, args)
        if isinstance(node.op, ast.Not):
            return not _bool(value, "not operand")
        if isinstance(node.op, ast.USub):
            return -_int(value, "unary - operand")
        if isinstance(node.op, ast.UAdd):
            return +_int(value, "unary + operand")
        raise GuardError(f"unsupported unary operator {type(node.op).__name__}")
    if isinstance(node, ast.BinOp):
        left = _int(_eval_node(node.left, args), "left operand")
        right = _int(_eval_node(node.right, args), "right operand")
        if isinstance(node.op, ast.Add):
            return left + right
        if isinstance(node.op, ast.Sub):
            return left - right
        if isinstance(node.op, ast.Mult):
            return left * right
        if isinstance(node.op, ast.FloorDiv):
            if right == 0:
                raise GuardError("integer division by zero")
            return left // right
        if isinstance(node.op, ast.Mod):
            if right == 0:
                raise GuardError("modulo by zero")
            return left % right
        raise GuardError(f"unsupported binary operator {type(node.op).__name__}")
    if isinstance(node, ast.Compare):
        left = _eval_node(node.left, args)
        for op, right_node in zip(node.ops, node.comparators):
            right = _eval_node(right_node, args)
            if isinstance(op, (ast.Eq, ast.NotEq)):
                if isinstance(left, bool) != isinstance(right, bool):
                    raise GuardError("cannot compare bool and int")
                if type(left) is not type(right):
                    raise GuardError("comparison operands have different types")
                if isinstance(op, ast.Eq):
                    ok = left == right
                else:
                    ok = left != right
            else:
                if isinstance(left, bool) or isinstance(right, bool):
                    raise GuardError("ordered comparison requires ints")
                if not isinstance(left, int) or not isinstance(right, int):
                    raise GuardError("ordered comparison requires ints")
                if isinstance(op, ast.Lt):
                    ok = left < right
                elif isinstance(op, ast.LtE):
                    ok = left <= right
                elif isinstance(op, ast.Gt):
                    ok = left > right
                elif isinstance(op, ast.GtE):
                    ok = left >= right
                else:
                    raise GuardError(f"unsupported comparison {type(op).__name__}")
            if not ok:
                return False
            left = right
        return True
    raise GuardError(f"unsupported construct {type(node).__name__}")


def eval_guard(expr: str, arg_names: Sequence[str],
               args: Mapping[str, Any]) -> bool:
    """Evaluate a Guard expression without Python ``eval``."""
    tree = _guard_ast(expr)
    declared = set(arg_names)
    for node in ast.walk(tree):
        if isinstance(node, ast.Name) and node.id not in declared:
            raise GuardError(f"unknown argument {node.id!r}")
    if set(args) != declared:
        raise GuardError(f"guard arguments must be exactly {sorted(declared)}")
    value = _eval_node(tree.body, args)
    return _bool(value, "guard result")


def verify_guard_witness(expr: str, arg_names: Sequence[str],
                         args: Mapping[str, Any]) -> Dict[str, Any]:
    """Check a Guard on one input.  This is not a domain-wide verdict."""
    try:
        value = eval_guard(expr, arg_names, args)
    except GuardError as exc:
        return {"scope": "witness", "valid": False, "value": None,
                "reason": str(exc)}
    return {"scope": "witness", "valid": True, "value": value,
            "note": "single witness only; no soundness/completeness claim"}


def verify_guard_domain(expr: str, arg_names: Sequence[str],
                        cases: Sequence[Case],
                        masked: Mapping[str, bool]) -> Dict[str, Any]:
    """Check a Guard over the supplied finite case set and report exactness."""
    values: Dict[str, bool] = {}
    for case in cases:
        try:
            values[case.case_id] = eval_guard(expr, arg_names, case.args)
        except GuardError as exc:
            return {
                "scope": "domain",
                "valid": False,
                "domain_size": len(cases),
                "error_case": case.case_id,
                "reason": str(exc),
                "sound": None,
                "complete": None,
                "exact": None,
            }
    missing = [c.case_id for c in cases if c.case_id not in masked]
    if missing:
        return {"scope": "domain", "valid": False, "domain_size": len(cases),
                "reason": f"masked map missing cases {missing}", "sound": None,
                "complete": None, "exact": None}
    false_accept = [cid for cid, value in values.items()
                    if value and not masked[cid]]
    false_reject = [cid for cid, value in values.items()
                    if not value and masked[cid]]
    return {
        "scope": "domain",
        "valid": True,
        "domain_size": len(cases),
        "guard_true": sum(1 for v in values.values() if v),
        "guard_false": sum(1 for v in values.values() if not v),
        "false_accept": false_accept,
        "false_reject": false_reject,
        "sound": not false_accept,
        "complete": not false_reject,
        "exact": not false_accept and not false_reject,
        "note": "finite-domain result; not a proof over all inputs",
    }
