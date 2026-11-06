"""Minimal, bounded condition induction for the A-masking obligation.

What this module does
---------------------
The verifier already knows, for each declared input, whether replacing the
target statement A by ``pass`` changes the returned channels.  That equality is
the *local relation obligation*; this module learns a guard over the entry
arguments that predicts it.

It does not read a reference guard, does not enumerate subsets of downstream
statements B, and does not call a model.  Candidate conditions come from a
typed predicate pool built from the source and the declared argument sorts.
The pool has two levels:

``generic``  per-variable scalar tests only (bool identity, int comparisons and
             modulus, list/dict length, cross-variable equality).  No knowledge
             of list aggregates.
``full``     adds list content tests (sum, distinct, count, min/max views and
             first/last extremum relations) and dict value sums.

Learning is counterexample guided.  A clause starts as the point-clause of one
masked witness and is *broadened* by removing literals while it still rejects
every unmasked witness; one clause is *expanded* for each masked witness the
guard still rejects.  The fit half is split again into ``learn`` and ``tune``;
tune counterexamples trigger a bounded refit.  The held-out eval half is never
used for selection.

Every result is bounded: the classification on a finite domain is
``BOUNDED``/``TESTED``, never ``PROVEN``.
"""
from __future__ import annotations

import ast
import hashlib
import time
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, Iterable, List, Mapping, Sequence, Tuple

from . import sandbox
from .fixture import Fixture


# ---------------------------------------------------------------------------
# Witnesses
# ---------------------------------------------------------------------------
def split_cases(cases: Sequence[Mapping[str, Any]], seed: int = 20261030
                ) -> Tuple[List[Mapping[str, Any]], List[Mapping[str, Any]]]:
    digest = [hashlib.sha256((str(seed) + repr(case)).encode("utf-8")).hexdigest()
              for case in cases]
    order = sorted(range(len(cases)), key=lambda index: digest[index])
    return ([cases[i] for i in order[::2]],
            [cases[i] for i in order[1::2]])


def witnesses(fixture: Fixture, timeout: float = 300.0) -> Dict[str, Any]:
    """Run the paired program and label every case with the verifier's equality.

    Returns the target line, the pre-state at A (P-), the post-state at A (P+)
    and a per-case boolean label.  Raises ``sandbox.SandboxError`` if the
    program is outside the supported subset.
    """
    result = sandbox.labels_cases(
        fixture.source, list(fixture.domain.cases),
        arg_sorts=fixture.arg_sorts, entry=fixture.entry, timeout=timeout)
    rows = []
    for item in result["cases"]:
        usable = item["err_plus"] is None and item["err_minus"] is None
        rows.append({"args": item["args"],
                     "masked": bool(usable and item["outputs_equal"]),
                     "usable": usable,
                     "pre": item["snap_minus"],
                     "post": item["snap_plus"],
                     "effect": item["a_has_local_effect"]})
    return {"target_line": result["target_line"], "cases": rows}


# ---------------------------------------------------------------------------
# Typed predicate pool
# ---------------------------------------------------------------------------
@dataclass(frozen=True)
class Predicate:
    expr: str
    family: str
    fn: Callable[[Mapping[str, Any]], bool] = field(compare=False, repr=False)

    def holds(self, args: Mapping[str, Any]) -> bool:
        try:
            return bool(self.fn(args))
        except Exception:  # noqa: BLE001 - a partial view is simply not true
            return False

    @property
    def size(self) -> int:
        return len(self.expr)


def source_constants(source: str) -> List[int]:
    values = {0, 1}
    for node in ast.walk(ast.parse(source)):
        if isinstance(node, ast.Constant) and isinstance(node.value, int) \
                and not isinstance(node.value, bool) and abs(node.value) <= 100:
            values.add(node.value)
    return sorted(values)


def _list_bounds(fixture: Fixture, name: str) -> Tuple[int, int]:
    for spec in fixture.domain.spec.get("args", []):
        if spec.get("name") == name:
            bounds = spec.get("length")
            if isinstance(bounds, list) and len(bounds) == 2:
                return int(bounds[0]), int(bounds[1])
    return 0, 3


def _add(pool: Dict[str, Predicate], expr: str, family: str,
         fn: Callable[[Mapping[str, Any]], bool]) -> None:
    if expr not in pool:
        pool[expr] = Predicate(expr, family, fn)


def build_pool(fixture: Fixture, level: str = "full") -> List[Predicate]:
    """Typed candidate predicates over the entry arguments only.

    The guard's scope in this verifier is the entry arguments; A's pre-state
    names are deliberately *not* in the pool because they are not legal in a
    guard.  Witnesses still use the pre-state to establish the obligation.
    """
    pool: Dict[str, Predicate] = {}
    consts = source_constants(fixture.source)
    moduli = sorted({c for c in consts if 2 <= c <= 12}) or [2]
    moduli = moduli[:4]
    args = list(fixture.arg_sorts)

    for name in args:
        sort = fixture.arg_sorts[name]
        if sort == "bool":
            _add(pool, name, "bool-var", lambda a, n=name: a[n] is True)
            _add(pool, f"not {name}", "bool-var", lambda a, n=name: a[n] is False)
        elif sort == "int":
            for c in consts:
                _add(pool, f"{name} == {c}", "int-scalar",
                     lambda a, n=name, c=c: a[n] == c)
                _add(pool, f"{name} != {c}", "int-scalar",
                     lambda a, n=name, c=c: a[n] != c)
                _add(pool, f"{name} < {c}", "int-scalar",
                     lambda a, n=name, c=c: a[n] < c)
                _add(pool, f"{name} <= {c}", "int-scalar",
                     lambda a, n=name, c=c: a[n] <= c)
                _add(pool, f"{name} > {c}", "int-scalar",
                     lambda a, n=name, c=c: a[n] > c)
                _add(pool, f"{name} >= {c}", "int-scalar",
                     lambda a, n=name, c=c: a[n] >= c)
            for k in moduli:
                for r in range(k):
                    _add(pool, f"{name} % {k} == {r}", "int-mod",
                         lambda a, n=name, k=k, r=r: a[n] % k == r)
                    _add(pool, f"{name} % {k} != {r}", "int-mod",
                         lambda a, n=name, k=k, r=r: a[n] % k != r)
        elif sort == "list[int]":
            low, high = _list_bounds(fixture, name)
            lengths = sorted({0, 1, high} | {c for c in (low, high) if 0 <= c <= high})
            for c in lengths:
                _add(pool, f"len({name}) == {c}", "list-length",
                     lambda a, n=name, c=c: len(a[n]) == c)
                _add(pool, f"len({name}) >= {c}", "list-length",
                     lambda a, n=name, c=c: len(a[n]) >= c)
            _add(pool, f"len({name}) > 0", "list-length",
                 lambda a, n=name: len(a[n]) > 0)
            if level != "full":
                continue
            for c in consts:
                _add(pool, f"sum({name}) == {c}", "list-sum",
                     lambda a, n=name, c=c: sum(a[n]) == c)
                _add(pool, f"sum({name}) != {c}", "list-sum",
                     lambda a, n=name, c=c: sum(a[n]) != c)
                _add(pool, f"sum({name}) < {c}", "list-sum",
                     lambda a, n=name, c=c: sum(a[n]) < c)
                _add(pool, f"sum({name}) <= {c}", "list-sum",
                     lambda a, n=name, c=c: sum(a[n]) <= c)
                _add(pool, f"sum({name}) > {c}", "list-sum",
                     lambda a, n=name, c=c: sum(a[n]) > c)
                _add(pool, f"sum({name}) >= {c}", "list-sum",
                     lambda a, n=name, c=c: sum(a[n]) >= c)
                _add(pool, f"count({name}, {c}) > 0", "list-content",
                     lambda a, n=name, c=c: a[n].count(c) > 0)
            for k in moduli:
                for r in range(k):
                    _add(pool, f"sum({name}) % {k} == {r}", "list-sum-mod",
                         lambda a, n=name, k=k, r=r: sum(a[n]) % k == r)
                    _add(pool, f"sum({name}) % {k} != {r}", "list-sum-mod",
                         lambda a, n=name, k=k, r=r: sum(a[n]) % k != r)
            _add(pool, f"distinct({name}) == len({name})", "list-content",
                 lambda a, n=name: len(set(a[n])) == len(a[n]))
            _add(pool, f"distinct({name}) < len({name})", "list-content",
                 lambda a, n=name: len(set(a[n])) < len(a[n]))
            _add(pool, f"({name} == sorted({name})) if len({name}) > 0 else True",
                 "list-relational",
                 lambda a, n=name: (a[n] == sorted(a[n])) if a[n] else True)
            _add(pool, f"({name}[0] == min({name})) if len({name}) > 0 else False",
                 "list-relational",
                 lambda a, n=name: (a[n][0] == min(a[n])) if a[n] else False)
            _add(pool, f"({name}[-1] == max({name})) if len({name}) > 0 else False",
                 "list-relational",
                 lambda a, n=name: (a[n][-1] == max(a[n])) if a[n] else False)
            _add(pool, f"(min({name}) == max({name})) if len({name}) > 0 else True",
                 "list-relational",
                 lambda a, n=name: (min(a[n]) == max(a[n])) if a[n] else True)
            for c in consts:
                _add(pool,
                     f"(count({name}, {name}[0] + {c}) > 0) if len({name}) > 0 else False",
                     "list-relational",
                     lambda a, n=name, c=c:
                     (a[n].count(a[n][0] + c) > 0) if a[n] else False)
                _add(pool,
                     f"(count({name}, {name}[-1] + {c}) > 0) if len({name}) > 0 else False",
                     "list-relational",
                     lambda a, n=name, c=c:
                     (a[n].count(a[n][-1] + c) > 0) if a[n] else False)
        elif sort == "dict[int,int]":
            low, high = _list_bounds(fixture, name)
            for c in sorted({0, 1, high}):
                _add(pool, f"len({name}) == {c}", "dict-length",
                     lambda a, n=name, c=c: len(a[n]) == c)
                _add(pool, f"len({name}) >= {c}", "dict-length",
                     lambda a, n=name, c=c: len(a[n]) >= c)
            _add(pool, f"len({name}) > 0", "dict-length",
                 lambda a, n=name: len(a[n]) > 0)
            if level == "full":
                for c in consts:
                    _add(pool, f"sum(vals({name})) == {c}", "dict-content",
                         lambda a, n=name, c=c: sum(a[n].values()) == c)
                    _add(pool, f"sum(vals({name})) >= {c}", "dict-content",
                         lambda a, n=name, c=c: sum(a[n].values()) >= c)

    # Cross-variable equality is generic and often the whole condition.
    for i, left in enumerate(args):
        for right in args[i + 1:]:
            if fixture.arg_sorts[left] != fixture.arg_sorts[right]:
                continue
            _add(pool, f"{left} == {right}", "cross-equality",
                 lambda a, l=left, r=right: a[l] == a[r])
            _add(pool, f"{left} != {right}", "cross-equality",
                 lambda a, l=left, r=right: a[l] != a[r])
            if fixture.arg_sorts[left] == "int":
                for op, fn in (("<", lambda x, y: x < y), ("<=", lambda x, y: x <= y),
                               (">", lambda x, y: x > y), (">=", lambda x, y: x >= y)):
                    _add(pool, f"{left} {op} {right}", "cross-order",
                         lambda a, l=left, r=right, fn=fn: fn(a[l], a[r]))
    return sorted(pool.values(), key=lambda p: (p.size, p.expr))


# ---------------------------------------------------------------------------
# Counterexample-guided DNF learning (bitset clauses)
# ---------------------------------------------------------------------------
def _holds_all(clause: Sequence[Predicate], args: Mapping[str, Any]) -> bool:
    return all(p.holds(args) for p in clause)


def _render_clause(clause: Sequence[Predicate]) -> str:
    if not clause:
        return "True"
    if len(clause) == 1:
        return clause[0].expr
    return " and ".join(f"({p.expr})" for p in clause)


def render_guard(clauses: Sequence[Sequence[Predicate]]) -> str:
    if not clauses:
        return "False"
    if any(not clause for clause in clauses):
        return "True"
    if len(clauses) == 1:
        return _render_clause(clauses[0])
    return " or ".join(f"({_render_clause(clause)})" for clause in clauses)


def normalise_clauses(clauses: Sequence[Sequence[Predicate]]) -> List[List[Predicate]]:
    """Drop duplicate and absorbed clauses (A OR B = A when A's literals ⊆ B's)."""
    unique: Dict[Tuple[str, ...], List[Predicate]] = {}
    for clause in clauses:
        key = tuple(sorted(p.expr for p in clause))
        unique.setdefault(key, list(clause))
    kept: List[List[Predicate]] = []
    kept_sets: List[set] = []
    for clause in sorted(unique.values(), key=lambda c: (len(c),
                                                          sorted(p.expr for p in c))):
        literals = {p.expr for p in clause}
        if any(previous <= literals for previous in kept_sets):
            continue
        kept.append(clause)
        kept_sets.append(literals)
    return kept


def _predicate_masks(pool: Sequence[Predicate],
                     cases: Sequence[Mapping[str, Any]]) -> List[int]:
    masks = []
    for pred in pool:
        mask = 0
        for index, case in enumerate(cases):
            if pred.holds(case["args"]):
                mask |= 1 << index
        masks.append(mask)
    return masks


def _and(indices: Iterable[int], masks: Sequence[int], width: int) -> int:
    value = (1 << width) - 1
    for index in indices:
        value &= masks[index]
    return value


def _generalise(seed: int, neg_mask: int, pos_mask: int,
                masks: Sequence[int], pool: Sequence[Predicate],
                width: int) -> Tuple[List[Predicate], int] | None:
    """Broaden the point-clause at ``seed`` while it still rejects every negative.

    The point clause is every predicate true at the seed.  Literals are removed
    one at a time, never letting a negative witness in; among the removable
    ones we take the literal whose removal covers the most positive witnesses.
    """
    clause = [index for index, mask in enumerate(masks) if (mask >> seed) & 1]
    clause_mask = _and(clause, masks, width)
    if clause_mask & neg_mask:
        return None
    while clause:
        best = None
        for position, literal in enumerate(clause):
            trial = _and([i for i in clause if i != literal], masks, width)
            if trial & neg_mask:
                continue
            gain = (trial & pos_mask).bit_count() - (clause_mask & pos_mask).bit_count()
            score = (gain, -pool[literal].size, pool[literal].expr)
            if best is None or score > best[0]:
                best = (score, position, trial)
        if best is None:
            break
        _, position, clause_mask = best
        clause.pop(position)
    # Canonicalise: if one literal true at the seed is already negative-free and
    # covers at least as many positives, prefer it over the conjunction.
    best_single = None
    for index, mask in enumerate(masks):
        if not ((mask >> seed) & 1) or (mask & neg_mask):
            continue
        cover = (mask & pos_mask).bit_count()
        key = (cover, -pool[index].size, pool[index].expr)
        if best_single is None or key > best_single[0]:
            best_single = (key, index, mask)
    if best_single and best_single[0][0] >= (clause_mask & pos_mask).bit_count():
        _, index, mask = best_single
        return [pool[index]], mask
    return [pool[i] for i in clause], clause_mask


def learn_clauses(positives: Sequence[Mapping[str, Any]],
                  negatives: Sequence[Mapping[str, Any]],
                  pool: Sequence[Predicate],
                  cases: Sequence[Mapping[str, Any]],
                  masks: Sequence[int],
                  sample: int = 8) -> Dict[str, Any]:
    """Set-cover style DNF: broaden clauses from uncovered positives.

    The candidate space is finite (the predicate pool over a finite witness
    set), and every clause is checked against all negative witnesses before it
    is kept.  This is a bounded result, not a proof.
    """
    width = len(cases)
    index_of = {id(case): index for index, case in enumerate(cases)}
    pos_mask = sum(1 << index_of[id(case)] for case in positives)
    neg_mask = sum(1 << index_of[id(case)] for case in negatives)
    uncovered = pos_mask
    clauses: List[List[Predicate]] = []
    log: List[Dict[str, Any]] = []
    failures = 0
    while uncovered:
        seeds = []
        probe = uncovered
        while probe and len(seeds) < sample:
            low = probe & -probe
            seeds.append(low.bit_length() - 1)
            probe ^= low
        best = None
        for seed in seeds:
            result = _generalise(seed, neg_mask, pos_mask, masks, pool, width)
            if result is None:
                continue
            clause, clause_mask = result
            cover = (clause_mask & uncovered).bit_count()
            key = (cover, -len(clause), _render_clause(clause))
            if best is None or key > best[0]:
                best = (key, seed, clause, clause_mask)
        if best is None:
            failures += 1
            seed = seeds[0]
            log.append({"kind": "unseparated-positive",
                        "seed": dict(cases[seed]["args"]),
                        "error": "no clause in the pool separates this witness"})
            uncovered &= ~(1 << seed)
            continue
        _, seed, clause, clause_mask = best
        clauses.append(clause)
        log.append({"kind": "expand", "seed": dict(cases[seed]["args"]),
                    "clause": _render_clause(clause),
                    "covered": (clause_mask & uncovered).bit_count()})
        uncovered &= ~clause_mask
    clauses = normalise_clauses(clauses)
    return {"clauses": clauses, "log": log, "failures": failures}


def _accepts(clauses: Sequence[Sequence[Predicate]], args: Mapping[str, Any]) -> bool:
    return any(_holds_all(clause, args) for clause in clauses)


def learn_with_repair(positives: Sequence[Mapping[str, Any]],
                      negatives: Sequence[Mapping[str, Any]],
                      tune: Sequence[Mapping[str, Any]],
                      pool: Sequence[Predicate],
                      cases: Sequence[Mapping[str, Any]]) -> Dict[str, Any]:
    """Learn on the learn half, then let tune counterexamples trigger a refit.

    A false accept is a *tightening* signal (the candidate is too broad), a
    false reject an *expansion* signal (too narrow).  Both are folded into a
    second bounded learn over the whole fit half; the eval half is untouched.
    """
    masks = _predicate_masks(pool, cases)
    learned = learn_clauses(positives, negatives, pool, cases, masks)
    false_accepts = [c for c in tune
                     if not c["masked"] and _accepts(learned["clauses"], c["args"])]
    false_rejects = [c for c in tune
                     if c["masked"] and not _accepts(learned["clauses"], c["args"])]
    repairs: List[Dict[str, Any]] = []
    if false_accepts or false_rejects:
        before = render_guard(learned["clauses"])
        refit = learn_clauses(list(positives) + [c for c in tune if c["masked"]],
                              list(negatives) + [c for c in tune if not c["masked"]],
                              pool, cases, masks)
        repairs.append({
            "kind": "refit-on-counterexamples",
            "false_accept": len(false_accepts),
            "false_reject": len(false_rejects),
            "tighten_examples": [dict(c["args"]) for c in false_accepts[:3]],
            "expand_examples": [dict(c["args"]) for c in false_rejects[:3]],
            "before": before,
            "after": render_guard(refit["clauses"]),
        })
        learned = refit
    return {**learned, "repair": repairs}


def classify(labels: Sequence[Mapping[str, Any]],
             clauses: Sequence[Sequence[Predicate]]) -> Dict[str, Any]:
    false_accept = sum(1 for c in labels
                       if not c["masked"] and _accepts(clauses, c["args"]))
    false_reject = sum(1 for c in labels
                       if c["masked"] and not _accepts(clauses, c["args"]))
    return {"sound": false_accept == 0, "complete": false_reject == 0,
            "exact": false_accept == 0 and false_reject == 0,
            "false_accept": false_accept, "false_reject": false_reject}


def _kind(result: Mapping[str, Any]) -> str:
    if result["exact"]:
        return "exact"
    if result["sound"] and not result["complete"]:
        return "sufficient"
    if result["complete"] and not result["sound"]:
        return "necessary"
    return "neither"


# ---------------------------------------------------------------------------
# Bounded check with the real verifier
# ---------------------------------------------------------------------------
def verify_guard(fixture: Fixture, guard: str | None,
                 cases: Sequence[Mapping[str, Any]] | None = None,
                 level: str = "BOUNDED", timeout: float = 300.0) -> Dict[str, Any]:
    from .contracts import ContractError, parse_bundle
    from .loop import _guard_only_bundle

    if not guard:
        return {"status": "ABSENT", "unsound": None, "incomplete": None,
                "exact": False, "error": "no guard"}
    try:
        bundle = parse_bundle(_guard_only_bundle(guard), allow_guard_only=True)
        report = sandbox.analyze(
            fixture.source, list(cases or fixture.domain.cases), bundle.to_dict(),
            arg_sorts=fixture.arg_sorts, functions=fixture.functions,
            channels=fixture.channels, level=level, entry=fixture.entry,
            timeout=timeout)
    except (ContractError, sandbox.SandboxError, ValueError) as exc:
        return {"status": "ERROR", "unsound": None, "incomplete": None,
                "exact": False, "error": f"{type(exc).__name__}: {exc}"}
    guard_report = report.get("guard") or {}
    unsound = guard_report.get("unsound")
    incomplete = guard_report.get("incomplete")
    typed = guard_report.get("status") not in ("INVALID", "ERROR", None)
    return {"status": guard_report.get("status"), "unsound": unsound,
            "incomplete": incomplete,
            "exact": typed and unsound == 0 and incomplete == 0,
            "error": guard_report.get("reason")}


# ---------------------------------------------------------------------------
# One fixture, both directions
# ---------------------------------------------------------------------------
def induce(fixture: Fixture, level: str = "full", seed: int = 20261030,
           check_domain: bool = True) -> Dict[str, Any]:
    start = time.perf_counter()
    data = witnesses(fixture)
    cases = [c for c in data["cases"] if c["usable"]]
    fit, ev = split_cases(cases, seed=seed)
    learn, tune = split_cases(fit, seed=seed + 1)
    pool = build_pool(fixture, level=level)
    pos = [c for c in learn if c["masked"]]
    neg = [c for c in learn if not c["masked"]]

    learned = learn_with_repair(pos, neg, tune, pool, fit)
    guard = render_guard(learned["clauses"])
    sufficient = {"guard": guard,
                  "fit": classify(fit, learned["clauses"]),
                  "eval": classify(ev, learned["clauses"]),
                  "full": classify(cases, learned["clauses"])}

    # Necessary direction: learn what is *unmasked*, then negate.
    dual = learn_with_repair(neg, pos, tune, pool, fit)
    necessary_expr = ("not (" + render_guard(dual["clauses"]) + ")")
    necessary_clauses = dual["clauses"]

    def dual_holds(args: Mapping[str, Any]) -> bool:
        return not _accepts(necessary_clauses, args)

    def classify_dual(labels):
        false_accept = sum(1 for c in labels
                           if not c["masked"] and dual_holds(c["args"]))
        false_reject = sum(1 for c in labels
                           if c["masked"] and not dual_holds(c["args"]))
        return {"sound": false_accept == 0, "complete": false_reject == 0,
                "exact": false_accept == 0 and false_reject == 0,
                "false_accept": false_accept, "false_reject": false_reject}

    necessary = {"guard": necessary_expr,
                 "fit": classify_dual(fit), "eval": classify_dual(ev),
                 "full": classify_dual(cases)}

    check = verify_guard(fixture, guard) if check_domain else None
    necessary_check = verify_guard(fixture, necessary_expr) if check_domain else None
    elapsed = time.perf_counter() - start

    def example(items: Sequence[Mapping[str, Any]], limit: int = 2):
        return [{"args": dict(c["args"]), "pre": c["pre"], "post": c["post"]}
                for c in items[:limit]]

    return {
        "fixture": fixture.id,
        "target_line": data["target_line"],
        "pool": {"level": level, "size": len(pool),
                 "families": sorted({p.family for p in pool})},
        "witnesses": {"total": len(cases), "fit": len(fit), "eval": len(ev),
                      "learn": len(learn), "tune": len(tune),
                      "masked": sum(1 for c in cases if c["masked"]),
                      "unmasked": sum(1 for c in cases if not c["masked"]),
                      "masked_examples": example([c for c in cases if c["masked"]]),
                      "unmasked_examples": example([c for c in cases if not c["masked"]])},
        "sufficient": {**sufficient, "kind": _kind(sufficient["eval"]),
                       "fit_kind": _kind(sufficient["fit"]),
                       "clauses": len(learned["clauses"]),
                       "failures": learned["failures"],
                       "log": learned["log"], "repair": learned["repair"]},
        "necessary": {**necessary, "kind": _kind(necessary["eval"]),
                      "fit_kind": _kind(necessary["fit"]),
                      "clauses": len(dual["clauses"]),
                      "failures": dual["failures"],
                      "log": dual["log"], "repair": dual["repair"]},
        "check": check, "necessary_check": necessary_check,
        "seconds": elapsed,
    }
