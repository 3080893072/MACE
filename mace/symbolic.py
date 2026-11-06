"""Source-level symbolic derivation of a masking guard (no model calls).

This is the M6 "pure symbolic" arm.  It executes the program and the program
with the target assignment deleted *symbolically*: entry arguments are symbolic
values, branches create path conditions, and the two versions' return
expressions are compared per path.  A guard is the disjunction, over paths, of

    (path condition) and (condition under which every output channel agrees)

No hidden reference guard is read, no subset of source operations is
enumerated, and no LLM is involved.  All conclusions are still bounded claims
about the declared finite domain; this module never emits ``PROVEN``.

Coverage is deliberately narrow.  It supports straight-line function bodies
with ``if``/``elif`` and conditional expressions, plus a small set of loop
idioms in helper functions (sum, min/max fold, dedup, insertion sort).  A
helper whose loop is not recognised makes the whole derivation ``UNKNOWN``
unless ``use_summaries=False``, in which case every user-function call is
already unknown.  That difference is exactly the "pure symbolic" vs
"symbolic + verified local semantic summaries" comparison.
"""
from __future__ import annotations

import ast
import copy
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Mapping, Sequence

from .fixture import Fixture


class SymbolicError(Exception):
    """The program is outside the supported symbolic fragment."""


# ---------------------------------------------------------------------------
# Expression helpers
# ---------------------------------------------------------------------------
def parse_expr(text: str) -> ast.expr:
    return ast.parse(text, mode="eval").body


def dump(node: ast.AST) -> str:
    return ast.unparse(node)


def Const(value: Any) -> ast.Constant:
    return ast.Constant(value=value)


def Name(ident: str) -> ast.Name:
    return ast.Name(id=ident, ctx=ast.Load())


def Call(func: str, *args: ast.expr) -> ast.Call:
    return ast.Call(func=Name(func), args=list(args), keywords=[])


def BinOp(op: ast.operator, left: ast.expr, right: ast.expr) -> ast.BinOp:
    return ast.BinOp(left=left, op=op, right=right)


def Compare(op: ast.cmpop, left: ast.expr, right: ast.expr) -> ast.Compare:
    return ast.Compare(left=left, ops=[op], comparators=[right])


def Not(node: ast.expr) -> ast.expr:
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        return node.operand
    return ast.UnaryOp(op=ast.Not(), operand=node)


def And(nodes: Sequence[ast.expr]) -> ast.expr:
    flat: List[ast.expr] = []
    for node in nodes:
        if isinstance(node, ast.Constant) and node.value is True:
            continue
        if isinstance(node, ast.Constant) and node.value is False:
            return Const(False)
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
            flat.extend(node.values)
        else:
            flat.append(node)
    if not flat:
        return Const(True)
    if len(flat) == 1:
        return flat[0]
    return ast.BoolOp(op=ast.And(), values=flat)


def Or(nodes: Sequence[ast.expr]) -> ast.expr:
    flat: List[ast.expr] = []
    for node in nodes:
        if isinstance(node, ast.Constant) and node.value is False:
            continue
        if isinstance(node, ast.Constant) and node.value is True:
            return Const(True)
        if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
            flat.extend(node.values)
        else:
            flat.append(node)
    if not flat:
        return Const(False)
    if len(flat) == 1:
        return flat[0]
    return ast.BoolOp(op=ast.Or(), values=flat)


def node_count(node: ast.AST) -> int:
    return sum(1 for _ in ast.walk(node))


def _const_value(node: ast.AST) -> Any:
    if isinstance(node, ast.Constant) and isinstance(node.value, (bool, int)):
        return node.value
    return None


def _is_int_const(node: ast.AST) -> bool:
    return (isinstance(node, ast.Constant) and isinstance(node.value, int)
            and not isinstance(node.value, bool))


# ---------------------------------------------------------------------------
# Symbolic values
# ---------------------------------------------------------------------------
@dataclass
class DictSym:
    entries: Dict[int, ast.expr]


@dataclass
class PathResult:
    conditions: List[ast.expr]
    outputs: List[ast.expr]


@dataclass
class HelperSummary:
    kind: str          # sum | dedup | sorted | min | max
    param: str


# ---------------------------------------------------------------------------
# Simplification
# ---------------------------------------------------------------------------
BUILTINS_INT = {"len", "sum", "min", "max", "abs", "count", "distinct"}
BUILTINS_LIST = {"sorted"}


def simplify_expr(node: ast.expr) -> ast.expr:
    """Small, syntax-directed simplifier over the supported fragment."""
    if isinstance(node, ast.Constant):
        return node
    if isinstance(node, ast.Name):
        return node
    if isinstance(node, ast.UnaryOp):
        operand = simplify_expr(node.operand)
        if isinstance(node.op, ast.USub) and _is_int_const(operand):
            return Const(-operand.value)
        if isinstance(node.op, ast.Not):
            if isinstance(operand, ast.Constant) and isinstance(operand.value, bool):
                return Const(not operand.value)
            return Not(operand)
        return ast.UnaryOp(op=node.op, operand=operand)
    if isinstance(node, ast.BinOp):
        left, right = simplify_expr(node.left), simplify_expr(node.right)
        if _is_int_const(left) and _is_int_const(right):
            try:
                if isinstance(node.op, ast.Add):
                    return Const(left.value + right.value)
                if isinstance(node.op, ast.Sub):
                    return Const(left.value - right.value)
                if isinstance(node.op, ast.Mult):
                    return Const(left.value * right.value)
                if isinstance(node.op, ast.FloorDiv) and right.value != 0:
                    return Const(left.value // right.value)
                if isinstance(node.op, ast.Mod) and right.value != 0:
                    return Const(left.value % right.value)
            except (TypeError, ZeroDivisionError):
                pass
        return ast.BinOp(left=left, op=node.op, right=right)
    if isinstance(node, ast.BoolOp):
        values = [simplify_expr(v) for v in node.values]
        return And(values) if isinstance(node.op, ast.And) else Or(values)
    if isinstance(node, ast.Compare):
        left = simplify_expr(node.left)
        rights = [simplify_expr(v) for v in node.comparators]
        if len(rights) == 1 and _is_int_const(left) and _is_int_const(rights[0]):
            op = node.ops[0]
            table = {ast.Eq: left.value == rights[0].value,
                     ast.NotEq: left.value != rights[0].value,
                     ast.Lt: left.value < rights[0].value,
                     ast.LtE: left.value <= rights[0].value,
                     ast.Gt: left.value > rights[0].value,
                     ast.GtE: left.value >= rights[0].value}
            for cls, value in table.items():
                if isinstance(op, cls):
                    return Const(value)
        out = ast.Compare(left=left, ops=node.ops, comparators=rights)
        return _simplify_compare(out)
    if isinstance(node, ast.IfExp):
        test = simplify_expr(node.test)
        if isinstance(test, ast.Constant) and isinstance(test.value, bool):
            return simplify_expr(node.body if test.value else node.orelse)
        return ast.IfExp(test=test, body=simplify_expr(node.body),
                         orelse=simplify_expr(node.orelse))
    if isinstance(node, ast.List):
        return ast.List(elts=[simplify_expr(v) for v in node.elts], ctx=ast.Load())
    if isinstance(node, ast.Subscript):
        value = simplify_expr(node.value)
        index = simplify_expr(node.slice)
        if isinstance(value, ast.Call) and isinstance(value.func, ast.Name):
            if value.func.id == "sorted" and _is_int_const(index) and value.args:
                if index.value == 0:
                    return simplify_expr(Call("min", value.args[0]))
                if index.value == -1:
                    return simplify_expr(Call("max", value.args[0]))
            if value.func.id == "distinct_list" and _is_int_const(index) \
                    and index.value == 0 and value.args:
                return simplify_expr(ast.Subscript(value=value.args[0], slice=Const(0),
                                                   ctx=ast.Load()))
        return ast.Subscript(value=value, slice=index, ctx=ast.Load())
    if isinstance(node, ast.Call):
        args = [simplify_expr(a) for a in node.args]
        if not isinstance(node.func, ast.Name):
            return ast.Call(func=node.func, args=args, keywords=[])
        fname = node.func.id
        if fname in ("min", "max") and len(args) == 1:
            inner = args[0]
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name):
                if inner.func.id == "sorted" and inner.args:
                    return Call(fname, inner.args[0])
        if fname == "sorted" and args:
            inner = args[0]
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) \
                    and inner.func.id == "sorted" and inner.args:
                return inner
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) \
                    and inner.func.id == "distinct_list" and inner.args:
                return inner
        if fname == "distinct_list" and args:
            inner = args[0]
            if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) \
                    and inner.func.id == "distinct_list":
                return inner
            # distinct_list(distinct_list(xs) + [y]) == distinct_list(xs + [y])
            if isinstance(inner, ast.BinOp) and isinstance(inner.op, ast.Add):
                left, right = inner.left, inner.right
                if isinstance(left, ast.Call) and isinstance(left.func, ast.Name) \
                        and left.func.id == "distinct_list" and left.args:
                    return simplify_expr(Call("distinct_list",
                                              simplify_expr(BinOp(ast.Add(),
                                                                  left.args[0], right))))
        return ast.Call(func=Name(fname), args=args, keywords=[])
    return node


def _simplify_compare(node: ast.Compare) -> ast.expr:
    """Turn ``x % k < 1`` into ``x % k == 0`` and similar range facts."""
    if len(node.ops) != 1 or len(node.comparators) != 1:
        return node
    left, right = node.left, node.comparators[0]
    if not _is_int_const(right):
        return node
    if not (isinstance(left, ast.BinOp) and isinstance(left.op, ast.Mod)
            and _is_int_const(left.right)):
        return node
    k = left.right.value
    if k <= 0:
        return node
    if isinstance(node.ops[0], ast.Lt) and right.value == 1 and k > 1:
        return Compare(ast.Eq(), left, Const(0))
    if isinstance(node.ops[0], ast.Lt) and right.value == k - 1:
        return Compare(ast.NotEq(), left, Const(k - 1))
    return node


# ---------------------------------------------------------------------------
# Boolean clause simplification (DNF + resolution + factoring)
# ---------------------------------------------------------------------------
Literal = tuple[bool, str]  # (positive?, atom text)


def _literal(node: ast.expr) -> List[Literal]:
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return [] if node.value else None  # type: ignore[return-value]
    positive = True
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        positive = False
        node = node.operand
    return [(positive, dump(node))]


def to_dnf(node: ast.expr) -> List[frozenset[Literal]]:
    """DNF clauses; a clause is a set of literals.  ``[]`` means False."""
    node = simplify_expr(node)
    if isinstance(node, ast.Constant) and isinstance(node.value, bool):
        return [frozenset()] if node.value else []
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.Or):
        out: List[frozenset[Literal]] = []
        for value in node.values:
            out.extend(to_dnf(value))
        return out
    if isinstance(node, ast.BoolOp) and isinstance(node.op, ast.And):
        clauses: List[frozenset[Literal]] = [frozenset()]
        for value in node.values:
            sub = to_dnf(value)
            if not sub:
                return []
            merged: List[frozenset[Literal]] = []
            for a in clauses:
                for b in sub:
                    merged.append(a | b)
            clauses = merged
        return clauses
    lits = _literal(node)
    if lits is None:
        return []
    clause = frozenset(lits)
    for positive, atom in clause:
        if (not positive, atom) in clause:
            return []
    return [clause]


def simplify_dnf(clauses: Iterable[frozenset[Literal]]) -> List[frozenset[Literal]]:
    current = [set(c) for c in clauses]
    changed = True
    while changed:
        changed = False
        # drop contradictory and duplicate clauses, absorb supersets
        clean: List[set] = []
        for clause in current:
            if any((not p, a) in clause for p, a in clause):
                changed = True
                continue
            if clause not in clean:
                clean.append(clause)
            else:
                changed = True
        current = clean
        keep: List[set] = []
        for i, clause in enumerate(current):
            if any(i != j and other < clause for j, other in enumerate(current)):
                changed = True
                continue
            keep.append(clause)
        current = keep
        # Unit propagation valid in DNF:  l or (not l and B) == l or B.
        additions: List[set] = []
        for unit in [c for c in current if len(c) == 1]:
            (positive, atom), = unit
            negative = (not positive, atom)
            for clause in current:
                if clause is unit or negative not in clause:
                    continue
                reduced = set(clause) - {negative}
                if reduced not in current and reduced not in additions:
                    additions.append(reduced)
        # Complementary pair with the same remainder:  (S and l) or (S and not l) == S.
        for i in range(len(current)):
            for j in range(i + 1, len(current)):
                a, b = current[i], current[j]
                shared = a & b
                ra, rb = a - shared, b - shared
                if len(ra) == 1 and len(rb) == 1:
                    (pa, atom_a), = ra
                    (pb, atom_b), = rb
                    if atom_a == atom_b and pa != pb:
                        addition = set(shared)
                        if addition not in current and addition not in additions:
                            additions.append(addition)
        if additions:
            current.extend(additions)
            changed = True
    return [frozenset(c) for c in current]


def factor_dnf(clauses: Sequence[frozenset[Literal]]) -> ast.expr:
    """Render DNF, factoring only literals common to every disjunct."""
    if not clauses:
        return Const(False)
    items: List[set[Literal]] = [set(c) for c in clauses]
    common = set.intersection(*items) if items else set()
    if common and len(items) > 1:
        rest = [item - common for item in items]
        return And([_literal_node(lit) for lit in sorted(common)]
                   + [factor_dnf([frozenset(r) for r in rest])])
    disjuncts = []
    for item in items:
        if not item:
            return Const(True)
        disjuncts.append(_literal_node(sorted(item)[0]) if len(item) == 1 else
                         And([_literal_node(lit) for lit in sorted(item)]))
    return Or(disjuncts)


def _literal_node(lit: Literal) -> ast.expr:
    positive, atom = lit
    node = parse_expr(atom)
    return node if positive else Not(node)


def simplify_bool(node: ast.expr) -> ast.expr:
    clauses = simplify_dnf(to_dnf(node))
    return factor_dnf(clauses)


# ---------------------------------------------------------------------------
# Linear arithmetic and equality rules
# ---------------------------------------------------------------------------
def linear(node: ast.expr) -> tuple[Dict[str, int], int] | None:
    if _is_int_const(node):
        return {}, node.value
    if isinstance(node, ast.BinOp):
        left, right = linear(node.left), linear(node.right)
        if isinstance(node.op, ast.Add) and left and right:
            return ({k: left[0].get(k, 0) + right[0].get(k, 0) for k in set(left[0]) | set(right[0])},
                    left[1] + right[1])
        if isinstance(node.op, ast.Sub) and left and right:
            return ({k: left[0].get(k, 0) - right[0].get(k, 0) for k in set(left[0]) | set(right[0])},
                    left[1] - right[1])
        if isinstance(node.op, ast.Mult) and left and right:
            if not left[0]:
                return ({k: v * left[1] for k, v in right[0].items()}, right[1] * left[1])
            if not right[0]:
                return ({k: v * right[1] for k, v in left[0].items()}, left[1] * right[1])
            return None
        return None
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.USub):
        sub = linear(node.operand)
        if sub:
            return ({k: -v for k, v in sub[0].items()}, -sub[1])
        return None
    if isinstance(node, (ast.Name, ast.Subscript, ast.Call)):
        # Function calls and indices are atoms unless they are list-valued.
        return {dump(node): 1}, 0
    return None


def _linear_rule(a: ast.expr, b: ast.expr) -> ast.expr | None:
    la, lb = linear(a), linear(b)
    if la is None or lb is None:
        return None
    atoms = set(la[0]) | set(lb[0])
    coeffs = {k: la[0].get(k, 0) - lb[0].get(k, 0) for k in atoms}
    const = la[1] - lb[1]
    coeffs = {k: v for k, v in coeffs.items() if v}
    if not coeffs:
        return Const(const == 0)
    if len(coeffs) == 1:
        (atom, coeff), = coeffs.items()
        numerator = -const
        if numerator % coeff == 0:
            return Compare(ast.Eq(), parse_expr(atom), Const(numerator // coeff))
        return Compare(ast.Eq(),
                       BinOp(ast.Mult(), Const(coeff), parse_expr(atom)), Const(numerator))
    if len(coeffs) == 2:
        (a1, c1), (a2, c2) = list(coeffs.items())
        if c1 == -c2:
            # c1*x + c2*y + const = 0
            return Compare(ast.Eq(), parse_expr(a1), parse_expr(a2)) if const == 0 else None
        if c1 == c2:
            return Compare(ast.Eq(),
                           BinOp(ast.Add(), parse_expr(a1), parse_expr(a2)), Const(-const // c1)) \
                if (-const) % c1 == 0 else None
    return None


def _floor(node: ast.expr) -> tuple[ast.expr, int] | None:
    # e - e % k
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Sub):
        left, right = node.left, node.right
        if isinstance(right, ast.BinOp) and isinstance(right.op, ast.Mod) \
                and dump(left) == dump(right.left) and _is_int_const(right.right):
            return left, right.right.value
    return None


def _add_const(node: ast.expr, delta: int) -> ast.expr:
    return simplify_expr(BinOp(ast.Add(), node, Const(delta)))


def _floor_rule(a: ast.expr, b: ast.expr) -> ast.expr | None:
    fa, fb = _floor(a), _floor(b)
    if not fa or not fb:
        return None
    (xa, ka), (xb, kb) = fa, fb
    if ka != kb or ka <= 0:
        return None
    la, lb = linear(xa), linear(xb)
    if la is None or lb is None:
        return None
    # xa = xb + d ?
    atoms = set(la[0]) | set(lb[0])
    if any(la[0].get(k, 0) != lb[0].get(k, 0) for k in atoms):
        return None
    d = la[1] - lb[1]
    if d == 0:
        return Const(True)
    base = xb if d > 0 else xa
    delta = abs(d)
    if delta >= ka:
        return None
    return Compare(ast.Lt(), BinOp(ast.Mod(), base, Const(ka)), Const(ka - delta))


def _min_parts(node: ast.expr) -> tuple[ast.expr, ast.expr] | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id in ("min", "max") and len(node.args) == 2:
        return node.func.id, node.args[0], node.args[1]  # type: ignore[return-value]
    return None


def _min_rule(a: ast.expr, b: ast.expr) -> ast.expr | None:
    pa, pb = _min_parts(a), _min_parts(b)
    if not pa or not pb:
        return None
    fa, ea, ca = pa
    fb, eb, cb = pb
    if fa != fb or dump(ca) != dump(cb):
        return None
    la, lb = linear(ea), linear(eb)
    if la is None or lb is None:
        return None
    atoms = set(la[0]) | set(lb[0])
    if any(la[0].get(k, 0) != lb[0].get(k, 0) for k in atoms):
        return None
    d = la[1] - lb[1]
    if d == 0:
        return _eq_condition(ea, eb)
    base = eb if d > 0 else ea
    op = ast.GtE() if fa == "min" else ast.LtE()
    return Compare(op, base, ca)


def _distinct_len(node: ast.expr) -> ast.expr | None:
    if isinstance(node, ast.Call) and isinstance(node.func, ast.Name) \
            and node.func.id == "len" and len(node.args) == 1:
        inner = node.args[0]
        if isinstance(inner, ast.Call) and isinstance(inner.func, ast.Name) \
                and inner.func.id == "distinct_list":
            return inner.args[0]
    return None


def _append_parts(node: ast.expr) -> tuple[ast.expr, ast.expr] | None:
    if isinstance(node, ast.BinOp) and isinstance(node.op, ast.Add):
        if isinstance(node.right, ast.List) and len(node.right.elts) == 1:
            return node.left, node.right.elts[0]
        if isinstance(node.left, ast.List) and len(node.left.elts) == 1:
            return node.right, node.left.elts[0]
    return None


def _distinct_rule(a: ast.expr, b: ast.expr) -> ast.expr | None:
    la, lb = _distinct_len(a), _distinct_len(b)
    if la is None or lb is None:
        return None
    for base, other in ((la, lb), (lb, la)):
        parts = _append_parts(other)
        if parts and dump(parts[0]) == dump(base):
            return Compare(ast.Gt(), Call("count", base, parts[1]), Const(0))
    return None


def _canon(node: ast.expr) -> ast.expr:
    """Canonical operand order for int addition/multiplication."""
    if isinstance(node, ast.BinOp):
        left, right = _canon(node.left), _canon(node.right)
        if isinstance(node.op, (ast.Add, ast.Mult)):
            values: List[ast.expr] = []
            op = node.op
            for part in (left, right):
                if isinstance(part, ast.BinOp) and type(part.op) is type(op):
                    values.extend([part.left, part.right])
                else:
                    values.append(part)
            if any(isinstance(v, (ast.List,)) for v in values):
                return ast.BinOp(left=left, op=node.op, right=right)
            values.sort(key=dump)
            result = values[0]
            for value in values[1:]:
                result = ast.BinOp(left=result, op=op, right=value)
            return result
        return ast.BinOp(left=left, op=node.op, right=right)
    if isinstance(node, ast.Call):
        return ast.Call(func=node.func, args=[_canon(a) for a in node.args], keywords=[])
    if isinstance(node, ast.Subscript):
        return ast.Subscript(value=_canon(node.value), slice=_canon(node.slice),
                             ctx=ast.Load())
    if isinstance(node, ast.UnaryOp):
        return ast.UnaryOp(op=node.op, operand=_canon(node.operand))
    return node


def _eq_condition(a: ast.expr, b: ast.expr) -> ast.expr | None:
    a, b = _canon(simplify_expr(a)), _canon(simplify_expr(b))
    if dump(a) == dump(b):
        return Const(True)
    for rule in (_distinct_rule, _floor_rule, _min_rule, _linear_rule):
        result = rule(a, b)
        if result is not None:
            return simplify_expr(result)
    # Equality itself is an exact condition over the arguments; use it only when
    # the terms are in the declared expression language.
    if "distinct_list" not in dump(a) + dump(b):
        return Compare(ast.Eq(), a, b)
    return None


# ---------------------------------------------------------------------------
# Helper summarisation
# ---------------------------------------------------------------------------
def _loop_target_assign(node: ast.For) -> tuple[str, ast.expr] | None:
    if not (isinstance(node.target, ast.Name) and isinstance(node.iter, ast.Name)):
        return None
    if len(node.body) != 1:
        return None
    body = node.body[0]
    if not (isinstance(body, ast.Assign) and len(body.targets) == 1
            and isinstance(body.targets[0], ast.Name)):
        return None
    return node.target.id, body


def summarize_helper(func: ast.FunctionDef) -> HelperSummary | None:
    if len(func.args.args) != 1:
        return None
    param = func.args.args[0].arg
    body = func.body
    # sum: total = 0; for x in xs: total = total + x
    if len(body) >= 2 and isinstance(body[0], ast.Assign) \
            and isinstance(body[0].value, ast.Constant) and body[0].value.value == 0 \
            and isinstance(body[1], ast.For):
        target = body[1].target
        if isinstance(target, ast.Name) and isinstance(body[1].iter, ast.Name) \
                and body[1].iter.id == param and len(body[1].body) == 1:
            stmt = body[1].body[0]
            if isinstance(stmt, ast.Assign) and isinstance(stmt.targets[0], ast.Name) \
                    and isinstance(stmt.value, ast.BinOp) \
                    and isinstance(stmt.value.op, ast.Add):
                names = {n.id for n in ast.walk(stmt.value) if isinstance(n, ast.Name)}
                if names == {stmt.targets[0].id, target.id}:
                    return HelperSummary("sum", param)
    # min/max fold: value = xs[0]; for item in xs[1:]: if item < value: value = item
    if len(body) >= 3 and isinstance(body[1], ast.For):
        loop = body[1]
        if isinstance(loop.iter, ast.Subscript) and len(loop.body) == 1 \
                and isinstance(loop.body[0], ast.If):
            test = loop.body[0].test
            if isinstance(test, ast.Compare) and len(test.ops) == 1 \
                    and isinstance(test.comparators[0], ast.Name):
                op = test.ops[0]
                if isinstance(op, (ast.Lt, ast.Gt)):
                    return HelperSummary("min" if isinstance(op, ast.Lt) else "max", param)
    # dedup: out = []; for x in xs: if x not in out: out.append(x)
    if len(body) >= 2 and isinstance(body[0], ast.Assign) \
            and isinstance(body[0].value, ast.List) and not body[0].value.elts \
            and isinstance(body[1], ast.For):
        loop = body[1]
        if len(loop.body) == 1 and isinstance(loop.body[0], ast.If):
            call = loop.body[0].body[0] if loop.body[0].body else None
            if isinstance(call, ast.Expr) and isinstance(call.value, ast.Call) \
                    and isinstance(call.value.func, ast.Attribute) \
                    and call.value.func.attr == "append":
                return HelperSummary("dedup", param)
    # insertion sort: for ...: while ...: result.insert(...)
    if any(isinstance(n, ast.While) for n in ast.walk(func)):
        if any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "insert" for n in ast.walk(func)):
            return HelperSummary("sorted", param)
    return None


# ---------------------------------------------------------------------------
# Executor
# ---------------------------------------------------------------------------
class SymbolicExecutor:
    def __init__(self, fixture: Fixture, *, use_summaries: bool = True):
        self.fixture = fixture
        self.source = fixture.source
        self.tree = ast.parse(fixture.source)
        self.entry = fixture.entry
        self.target_line = self._target_line()
        self.use_summaries = use_summaries
        self.summaries: Dict[str, HelperSummary | None] = {}
        self._collect_summaries()
        self.explanation: List[Dict[str, Any]] = []
        # Statement line numbers visited by path enumeration, and those covered
        # by a helper summary rather than enumerated statement by statement.
        self.reached: set[int] = set()
        self.summarized: set[int] = set()

    def _target_line(self) -> int:
        for index, line in enumerate(self.source.splitlines(), 1):
            if "# TARGET_A" in line:
                return index
        raise SymbolicError("no TARGET_A marker")

    def _functions(self) -> Dict[str, ast.FunctionDef]:
        return {n.name: n for n in self.tree.body if isinstance(n, ast.FunctionDef)}

    def _collect_summaries(self) -> None:
        for name, func in self._functions().items():
            if name == self.entry:
                continue
            self.summaries[name] = summarize_helper(func) if self.use_summaries else None

    def _entry_func(self, tree: ast.Module) -> ast.FunctionDef:
        for node in tree.body:
            if isinstance(node, ast.FunctionDef) and node.name == self.entry:
                return node
        raise SymbolicError(f"entry function {self.entry!r} not found")

    def versions(self) -> tuple[ast.FunctionDef, ast.FunctionDef]:
        plus = copy.deepcopy(self.tree)
        minus = copy.deepcopy(self.tree)
        target = None
        for node in ast.walk(minus):
            if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign))                     and node.lineno == self.target_line:
                target = node
                break
        if target is None:
            raise SymbolicError("target assignment not found")
        for parent in ast.walk(minus):
            for field_name, value in ast.iter_fields(parent):
                if isinstance(value, list):
                    new = [ast.copy_location(ast.Pass(), target) if v is target else v
                           for v in value]
                    if any(v is target for v in value):
                        setattr(parent, field_name, new)
                        break
                elif value is target:
                    setattr(parent, field_name, ast.copy_location(ast.Pass(), target))
                    break
            if target not in list(ast.walk(minus)):
                break
        return self._entry_func(plus), self._entry_func(minus)

    def _normalise(self, stmts: Sequence[ast.stmt]) -> List[ast.stmt]:
        out: List[ast.stmt] = []
        for stmt in stmts:
            if isinstance(stmt, ast.Assign) and isinstance(stmt.value, ast.IfExp):
                value = stmt.value
                name = stmt.targets[0]
                out.append(ast.copy_location(ast.If(
                    test=value.test,
                    body=[ast.copy_location(ast.Assign(targets=[name], value=value.body,
                                                       type_comment=None), stmt)],
                    orelse=[ast.copy_location(ast.Assign(targets=[copy.deepcopy(name)],
                                                         value=value.orelse,
                                                         type_comment=None), stmt)]), stmt))
                continue
            if isinstance(stmt, ast.If):
                stmt = ast.If(test=stmt.test,
                              body=self._normalise(stmt.body),
                              orelse=self._normalise(stmt.orelse))
            out.append(stmt)
        return out

    def execute(self, func: ast.FunctionDef, args: Sequence[str]) -> List[PathResult]:
        env: Dict[str, Any] = {name: Name(name) for name in args}
        return self._exec_block(self._normalise(func.body), env, [])

    def _exec_block(self, stmts: Sequence[ast.stmt], env: Dict[str, Any],
                    conds: List[ast.expr]) -> List[PathResult]:
        stmts = list(stmts)
        results: List[PathResult] = []
        current_env = dict(env)
        current_conds = list(conds)
        for index, stmt in enumerate(stmts):
            rest = stmts[index + 1:]
            if getattr(stmt, "lineno", None):
                self.reached.add(stmt.lineno)
            if isinstance(stmt, ast.Pass):
                continue
            if isinstance(stmt, ast.Return):
                values = self._return_values(stmt.value, current_env)
                results.append(PathResult(current_conds, values))
                return results
            if isinstance(stmt, ast.If):
                test = self.eval_expr(stmt.test, current_env)
                results.extend(self._exec_block(
                    list(stmt.body) + list(rest), copy.deepcopy(current_env),
                    current_conds + [test]))
                results.extend(self._exec_block(
                    list(stmt.orelse) + list(rest), copy.deepcopy(current_env),
                    current_conds + [Not(test)]))
                return results
            if isinstance(stmt, ast.Assign):
                value = self.eval_expr(stmt.value, current_env)
                for target in stmt.targets:
                    self._assign(target, value, current_env)
                continue
            if isinstance(stmt, ast.AnnAssign):
                if stmt.value is not None:
                    self._assign(stmt.target, self.eval_expr(stmt.value, current_env),
                                 current_env)
                continue
            if isinstance(stmt, ast.AugAssign):
                old = self.eval_expr(stmt.target, current_env)
                new = self.eval_expr(stmt.value, current_env)
                self._assign(stmt.target, BinOp(stmt.op, old, new), current_env)
                continue
            if isinstance(stmt, ast.Expr):
                continue
            raise SymbolicError(f"unsupported statement {type(stmt).__name__} "
                                f"at line {getattr(stmt, 'lineno', '?')}")
        results.append(PathResult(current_conds, []))
        return results

    def _return_values(self, value: ast.expr | None, env: Dict[str, Any]) -> List[ast.expr]:
        if value is None:
            return []
        if isinstance(value, ast.Tuple):
            return [self.eval_expr(v, env) for v in value.elts]
        return [self.eval_expr(value, env)]

    def _assign(self, target: ast.expr, value: Any, env: Dict[str, Any]) -> None:
        if isinstance(target, ast.Name):
            env[target.id] = value
            return
        if isinstance(target, (ast.Tuple, ast.List)):
            if not isinstance(value, tuple) or len(value) != len(target.elts):
                raise SymbolicError("tuple assignment mismatch")
            for t, v in zip(target.elts, value):
                self._assign(t, v, env)
            return
        if isinstance(target, ast.Subscript):
            container = self.eval_expr(target.value, env)
            index = self.eval_expr(target.slice, env)
            if not isinstance(container, DictSym) or not _is_int_const(index):
                raise SymbolicError("only constant dict keys are supported")
            container.entries[index.value] = value
            return
        raise SymbolicError(f"unsupported assignment target {type(target).__name__}")

    def eval_expr(self, node: ast.expr, env: Dict[str, Any]) -> Any:
        if isinstance(node, ast.Constant):
            if isinstance(node.value, (bool, int)):
                return Const(node.value)
            raise SymbolicError(f"unsupported constant {node.value!r}")
        if isinstance(node, ast.Name):
            return env.get(node.id, Name(node.id))
        if isinstance(node, ast.Tuple):
            return tuple(self.eval_expr(v, env) for v in node.elts)
        if isinstance(node, ast.List):
            return ast.List(elts=[self.eval_expr(v, env) for v in node.elts],
                            ctx=ast.Load())
        if isinstance(node, ast.Dict):
            entries = {}
            for key, value in zip(node.keys, node.values):
                if not isinstance(key, ast.Constant) or not isinstance(key.value, int):
                    raise SymbolicError("only constant int dict keys are supported")
                entries[key.value] = self.eval_expr(value, env)
            return DictSym(entries)
        if isinstance(node, ast.BinOp):
            left = self.eval_expr(node.left, env)
            right = self.eval_expr(node.right, env)
            if isinstance(left, DictSym) or isinstance(right, DictSym):
                raise SymbolicError("dict arithmetic is not supported")
            return simplify_expr(BinOp(node.op, left, right))
        if isinstance(node, ast.UnaryOp):
            return simplify_expr(ast.UnaryOp(node.op, self.eval_expr(node.operand, env)))
        if isinstance(node, ast.BoolOp):
            return simplify_expr(ast.BoolOp(
                node.op, [self.eval_expr(v, env) for v in node.values]))
        if isinstance(node, ast.Compare):
            left = self.eval_expr(node.left, env)
            rights = [self.eval_expr(v, env) for v in node.comparators]
            return simplify_expr(ast.Compare(left, node.ops, rights))
        if isinstance(node, ast.Subscript):
            container = self.eval_expr(node.value, env)
            index = self.eval_expr(node.slice, env)
            if isinstance(container, DictSym):
                if not _is_int_const(index):
                    raise SymbolicError("dict index must be constant")
                if index.value not in container.entries:
                    raise SymbolicError("dict key is not present")
                return container.entries[index.value]
            return simplify_expr(ast.Subscript(container, index, ast.Load()))
        if isinstance(node, ast.IfExp):
            raise SymbolicError("conditional expression outside a normalised assignment")
        if isinstance(node, ast.Call):
            return self._call(node, env)
        raise SymbolicError(f"unsupported expression {type(node).__name__}")

    def _call(self, node: ast.Call, env: Dict[str, Any]) -> Any:
        if not isinstance(node.func, ast.Name):
            raise SymbolicError("method calls are only allowed inside helpers")
        fname = node.func.id
        args = [self.eval_expr(a, env) for a in node.args]
        if fname in ("len",):
            if isinstance(args[0], DictSym):
                return Const(len(args[0].entries))
            return simplify_expr(Call(fname, args[0]))
        if fname in BUILTINS_INT:
            return simplify_expr(Call(fname, *args))
        if fname in BUILTINS_LIST:
            return simplify_expr(Call(fname, *args))
        summary = self.summaries.get(fname)
        if summary is None or not self.use_summaries:
            raise SymbolicError(f"no semantic summary for helper {fname!r}")
        helper = self._functions().get(fname)
        if helper is not None:
            for node in ast.walk(helper):
                if isinstance(node, ast.stmt) and getattr(node, "lineno", None):
                    self.summarized.add(node.lineno)
        if len(args) != 1:
            raise SymbolicError("helper summaries take exactly one argument")
        arg = args[0]
        if summary.kind == "sum":
            return simplify_expr(Call("sum", arg))
        if summary.kind == "dedup":
            return simplify_expr(Call("distinct_list", arg))
        if summary.kind == "sorted":
            return simplify_expr(Call("sorted", arg))
        if summary.kind == "min":
            return simplify_expr(Call("min", arg))
        if summary.kind == "max":
            return simplify_expr(Call("max", arg))
        raise SymbolicError(f"unknown summary kind {summary.kind!r}")

    def coverage(self) -> Dict[str, Any]:
        """Source statement coverage: enumerated + summarized, over all functions."""
        total = 0
        for func in self._functions().values():
            for node in ast.walk(func):
                if isinstance(node, ast.stmt) and getattr(node, "lineno", None):
                    total += 1
        hit = len(self.reached | self.summarized)
        return {"reached": len(self.reached), "summarized": len(self.summarized),
                "covered": hit, "total": total,
                "ratio": round(hit / total, 3) if total else 0.0}


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------
def _path_key(item: PathResult) -> tuple[str, ...]:
    return tuple(sorted(dump(c) for c in item.conditions))


def derive_guard(fixture: Fixture, *, use_summaries: bool = True) -> Dict[str, Any]:
    """Derive a guard; returns a dict with ``status`` DERIVED or UNKNOWN."""
    executor = SymbolicExecutor(fixture, use_summaries=use_summaries)
    try:
        plus_func, minus_func = executor.versions()
        args = [a.arg for a in plus_func.args.args]
        plus_paths = executor.execute(plus_func, args)
        minus_paths = executor.execute(minus_func, args)
    except SymbolicError as exc:
        return {"status": "UNKNOWN", "guard": None, "reason": str(exc),
                "paths": 0, "node_count": 0, "explanation": [],
                "coverage": executor.coverage()}

    by_plus = {_path_key(p): p for p in plus_paths}
    by_minus = {_path_key(p): p for p in minus_paths}
    if set(by_plus) != set(by_minus):
        return {"status": "UNKNOWN", "guard": None,
                "reason": "A changes control flow: path conditions differ",
                "paths": len(by_plus), "node_count": 0, "explanation": [],
                "coverage": executor.coverage()}

    clauses: List[ast.expr] = []
    explanation: List[Dict[str, Any]] = []
    unknown: List[str] = []
    for key in sorted(by_plus):
        plus = by_plus[key]
        minus = by_minus[key]
        if len(plus.outputs) != len(minus.outputs):
            return {"status": "UNKNOWN", "guard": None,
                    "reason": "output arity differs between versions",
                    "paths": len(by_plus), "node_count": 0, "explanation": [],
                    "coverage": executor.coverage()}
        channel_conditions = []
        rules = []
        for index, (a, b) in enumerate(zip(plus.outputs, minus.outputs)):
            cond = _eq_condition(a, b)
            if cond is None:
                unknown.append(f"channel {index}: {dump(a)} vs {dump(b)}")
                channel_conditions = []
                break
            channel_conditions.append(cond)
            rules.append({"channel": index, "left": dump(a), "right": dump(b),
                          "condition": dump(cond)})
        if not channel_conditions:
            continue
        condition = simplify_bool(And(channel_conditions))
        if isinstance(condition, ast.Constant) and condition.value is False:
            continue
        clause = simplify_bool(And(list(plus.conditions) + [condition]))
        if isinstance(clause, ast.Constant) and clause.value is False:
            continue
        if isinstance(clause, ast.Constant) and clause.value is True:
            clauses = [Const(True)]
            explanation = [{"path": [dump(c) for c in plus.conditions],
                            "channels": rules, "clause": True}]
            break
        clauses.append(clause)
        explanation.append({"path": [dump(c) for c in plus.conditions],
                            "channels": rules, "clause": dump(clause)})

    if unknown:
        return {"status": "UNKNOWN", "guard": None,
                "reason": "no equality rule for " + "; ".join(unknown),
                "paths": len(by_plus), "node_count": 0, "explanation": explanation,
                "coverage": executor.coverage()}

    guard = simplify_bool(Or(clauses)) if clauses else Const(False)
    if "distinct_list" in dump(guard):
        return {"status": "UNKNOWN", "guard": None,
                "reason": "derived guard mentions an internal summary",
                "paths": len(by_plus), "node_count": 0, "explanation": explanation,
                "coverage": executor.coverage()}
    return {"status": "DERIVED", "guard": dump(guard), "reason": "source-level path equality",
            "paths": len(by_plus), "node_count": node_count(guard),
            "explanation": explanation,
            "coverage": executor.coverage(),
            "summaries": {k: (v.kind if v else None) for k, v in executor.summaries.items()}}
