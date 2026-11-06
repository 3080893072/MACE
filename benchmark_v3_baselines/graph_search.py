"""Graph-guided causal masking search (CPU prototype).

The search evaluates interventions (delete a subset of candidate operations)
and records three-valued evidence: masked, exposed, or UNKNOWN.  It never
turns UNKNOWN into False and it never uses an unproven monotonicity rule to
discard a subset.

Two orderings are provided:

``exhaustive``
    All subsets, in a fixed deterministic order (used by the candidate
    ablations without graph guidance).

``graph``
    All subsets, ordered by A-centred subgraph relevance of the two sets a
    subset can serve as: the disabled set itself (MMBS side) and its
    complement (MSMS side).  After each observation, operations implicated
    in a mask/exposure receive a small deterministic boost.  Ordering only
    changes *when* evidence is obtained; unless a caller supplies a probe
    budget, every subset is still evaluated, so completeness is preserved.

Minimality is always checked against the exact public definitions and only
with evidence that was actually collected.  A set whose required subset
comparisons include an UNKNOWN is reported as minimality-unknown, not as a
relation.
"""
from __future__ import annotations

import itertools
import json
import time
from dataclasses import dataclass
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple


def subset_key(ids: Iterable[str]) -> str:
    return "+".join(sorted(ids)) or "EMPTY"


def payload_key(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def all_subsets(ids: Sequence[str]) -> List[Tuple[str, ...]]:
    ordered = sorted(ids)
    out: List[Tuple[str, ...]] = []
    for size in range(len(ordered) + 1):
        for combo in itertools.combinations(ordered, size):
            out.append(combo)
    return out


@dataclass
class EvalRecord:
    disabled: Tuple[str, ...]
    status: str                    # OK | UNKNOWN | INVALID
    masked: Optional[bool] = None
    exposed: Optional[bool] = None
    reason: str = ""
    plus: Any = None
    minus: Any = None


class ExecutorOracle:
    """Adapts ``Executor`` to the three-valued search interface.

    ``cache_hits`` counts observations already present in the executor's
    run cache before this search asked for them, so repeated evidence (for
    example the single-deletion probes computed during isolation) is
    reported rather than silently charged twice.
    """

    def __init__(self, executor: Any, payload: Dict[str, Any]):
        self.executor = executor
        self.payload = payload
        self.cache_hits = 0

    def _cached(self, disabled: Sequence[str], side: str) -> bool:
        key = (subset_key(disabled), side, payload_key(self.payload))
        return key in getattr(self.executor, "_runs", {})

    def evaluate(self, disabled: Sequence[str]) -> EvalRecord:
        disabled = tuple(sorted(disabled))
        if self._cached(disabled, "plus"):
            self.cache_hits += 1
        if self._cached(disabled, "minus"):
            self.cache_hits += 1
        try:
            plus = self.executor.observation(disabled, "plus", self.payload)
            minus = self.executor.observation(disabled, "minus", self.payload)
        except KeyError as exc:
            return EvalRecord(disabled, "INVALID", reason=f"unknown operation: {exc}")
        except Exception as exc:  # noqa: BLE001 - recorded, never hidden
            return EvalRecord(disabled, "UNKNOWN",
                              reason=f"{type(exc).__name__}: {exc}")
        if plus.get("__probe_error__") or minus.get("__probe_error__"):
            return EvalRecord(
                disabled, "UNKNOWN",
                reason="probe did not produce an observation",
                plus=plus, minus=minus)
        masked = bool(plus.get("outcome") == "return" and plus == minus)
        exposed = bool(plus != minus)
        return EvalRecord(disabled, "OK", masked=masked, exposed=exposed,
                          plus=plus, minus=minus)


class SyntheticOracle:
    """Oracle backed by a truth table (used by the algorithmic tests)."""

    def __init__(self, masked_sets: Iterable[Iterable[str]],
                 exposed_sets: Iterable[Iterable[str]],
                 unknown_sets: Iterable[Iterable[str]] = (),
                 invalid_sets: Iterable[Iterable[str]] = ()):
        self.masked = {subset_key(item) for item in masked_sets}
        self.exposed = {subset_key(item) for item in exposed_sets}
        self.unknown = {subset_key(item) for item in unknown_sets}
        self.invalid = {subset_key(item) for item in invalid_sets}

    def evaluate(self, disabled: Sequence[str]) -> EvalRecord:
        disabled = tuple(sorted(disabled))
        key = subset_key(disabled)
        if key in self.invalid:
            return EvalRecord(disabled, "INVALID", reason="illegal intervention")
        if key in self.unknown:
            return EvalRecord(disabled, "UNKNOWN", reason="evidence unavailable")
        return EvalRecord(disabled, "OK", masked=key in self.masked,
                          exposed=key in self.exposed)


class EvidenceStore:
    """Evidence cache; UNKNOWN is retained and can be explicitly revisited."""

    def __init__(self, oracle: Any):
        self.oracle = oracle
        self.records: Dict[str, EvalRecord] = {}
        self.order: List[str] = []
        self.evaluations = 0
        self.cache_hits = 0
        self.unknown = 0
        self.invalid = 0

    def get(self, disabled: Sequence[str]) -> Optional[EvalRecord]:
        key = subset_key(disabled)
        record = self.records.get(key)
        if record is not None:
            self.cache_hits += 1
        return record

    def evaluate(self, disabled: Sequence[str]) -> EvalRecord:
        key = subset_key(disabled)
        existing = self.records.get(key)
        if existing is not None:
            self.cache_hits += 1
            return existing
        record = self.oracle.evaluate(disabled)
        self.records[key] = record
        self.order.append(key)
        self.evaluations += 1
        if record.status == "UNKNOWN":
            self.unknown += 1
        elif record.status == "INVALID":
            self.invalid += 1
        return record

    def invalidate_unknown(self) -> int:
        keys = [k for k, r in self.records.items() if r.status == "UNKNOWN"]
        for key in keys:
            del self.records[key]
        return len(keys)


def _masked_value(store: EvidenceStore, ids: Sequence[str],
                  disabled: Sequence[str]) -> Tuple[Optional[bool], str]:
    record = store.get(disabled)
    if record is None:
        return None, "missing"
    if record.status != "OK":
        return None, record.status
    return record.masked, ""


def _exposed_value(store: EvidenceStore, ids: Sequence[str],
                   disabled: Sequence[str]) -> Tuple[Optional[bool], str]:
    record = store.get(disabled)
    if record is None:
        return None, "missing"
    if record.status != "OK":
        return None, record.status
    return record.exposed, ""


def _proper_nonempty_subsets(ids: Sequence[str]) -> Iterable[Tuple[str, ...]]:
    ordered = sorted(ids)
    for size in range(1, len(ordered)):
        for combo in itertools.combinations(ordered, size):
            yield combo


def _proper_subsets_including_empty(ids: Sequence[str]) -> Iterable[Tuple[str, ...]]:
    ordered = sorted(ids)
    for size in range(0, len(ordered)):
        for combo in itertools.combinations(ordered, size):
            yield combo


def minimal_masked_sets(universe: Sequence[str],
                        store: EvidenceStore) -> Dict[str, Any]:
    """Non-empty minimal S with Masked_strict(U \\ S).

    Returns confirmed sets and sets whose minimality is blocked by UNKNOWN
    evidence.  A blocked set is never returned as confirmed.
    """
    universe = sorted(universe)
    confirmed: List[List[str]] = []
    unknown: List[Dict[str, Any]] = []
    base_false: List[List[str]] = []
    for size in range(1, len(universe) + 1):
        for kept in itertools.combinations(universe, size):
            disabled = tuple(sorted(set(universe) - set(kept)))
            value, reason = _masked_value(store, universe, disabled)
            if value is not True:
                if value is False:
                    base_false.append(list(kept))
                continue
            blocked = False
            blocked_by: List[Dict[str, Any]] = []
            for sub in _proper_nonempty_subsets(kept):
                sub_disabled = tuple(sorted(set(universe) - set(sub)))
                sub_value, sub_reason = _masked_value(store, universe, sub_disabled)
                if sub_value is True:
                    blocked = True
                    break
                if sub_value is None:
                    blocked_by.append({"subset": list(sub),
                                       "reason": sub_reason})
            if blocked:
                continue
            if blocked_by:
                unknown.append({"set": list(kept), "blocked_by": blocked_by})
                continue
            confirmed.append(sorted(kept))
    return {"confirmed": sorted(confirmed), "unknown": unknown,
            "base_false": sorted(base_false)}


def minimal_exposed_sets(universe: Sequence[str],
                         store: EvidenceStore) -> Dict[str, Any]:
    """Non-empty minimal H with Exposed(H); empty subset is checked too."""
    universe = sorted(universe)
    confirmed: List[List[str]] = []
    unknown: List[Dict[str, Any]] = []
    for size in range(1, len(universe) + 1):
        for disabled in itertools.combinations(universe, size):
            value, reason = _exposed_value(store, universe, disabled)
            if value is not True:
                continue
            blocked = False
            blocked_by: List[Dict[str, Any]] = []
            for sub in _proper_subsets_including_empty(disabled):
                sub_value, sub_reason = _exposed_value(store, universe, sub)
                if sub_value is True:
                    blocked = True
                    break
                if sub_value is None:
                    blocked_by.append({"subset": list(sub),
                                       "reason": sub_reason})
            if blocked:
                continue
            if blocked_by:
                unknown.append({"set": list(disabled), "blocked_by": blocked_by})
                continue
            confirmed.append(sorted(disabled))
    return {"confirmed": sorted(confirmed), "unknown": unknown}


def profile_from_maps(masked: Dict[str, bool], exposed: Dict[str, bool],
                      universe: Sequence[str]) -> Dict[str, Any]:
    """Post-hoc discovery cost for an already-complete exhaustive run.

    The maps come from ``Executor.relations``, which evaluates subsets in
    the same deterministic order used here.  This reconstructs exactly when
    each relation first became verifiable without executing anything again,
    so C-original's frozen execution path is untouched.
    """
    universe = sorted(universe)
    subsets = all_subsets(universe)
    order = sorted(subsets, key=lambda item: (len(item), item))
    store = EvidenceStore(oracle=None)
    first_msms: Optional[Dict[str, Any]] = None
    first_mmbs: Optional[Dict[str, Any]] = None
    for index, subset in enumerate(order):
        key = subset_key(subset)
        store.records[key] = EvalRecord(
            subset, "OK", masked=bool(masked.get(key)),
            exposed=bool(exposed.get(key)))
        store.order.append(key)
        store.evaluations = index + 1
        if first_msms is None:
            found = minimal_masked_sets(universe, store)["confirmed"]
            if found:
                first_msms = {"set": found[0], "evaluations": index + 1,
                              "elapsed_seconds": None}
        if first_mmbs is None:
            found = minimal_exposed_sets(universe, store)["confirmed"]
            if found:
                first_mmbs = {"set": found[0], "evaluations": index + 1,
                              "elapsed_seconds": None}
        if first_msms is not None and first_mmbs is not None:
            break
    return {"first_msms": first_msms, "first_mmbs": first_mmbs,
            "evaluations": len(order), "subsets_total": len(subsets),
            "complete": True, "order": order}


def _subset_priority(disabled: Tuple[str, ...], universe: Sequence[str],
                     scores: Dict[str, float],
                     dynamic: Dict[str, float]) -> Tuple[float, float, int,
                                                         int, Tuple[str, ...]]:
    """Lower is evaluated earlier.  Heuristic only.

    A subset can serve either role: ``disabled`` is an MMBS candidate and
    its complement is an MSMS candidate.  Ordering therefore walks a
    symmetric frontier by ``min(|D|, |U \\ D|)`` so that neither role is
    starved by the other.  Graph relevance breaks ties within a layer.
    """
    disabled_set = set(disabled)
    kept = [op for op in universe if op not in disabled_set]
    mmbs = sum(scores.get(op, 0.0) + dynamic.get(op, 0.0) for op in disabled)
    msms = sum(scores.get(op, 0.0) + dynamic.get(op, 0.0) for op in kept)
    edge = min(len(disabled), len(kept))
    role_score = mmbs if len(disabled) <= len(kept) else msms
    return (edge, -round(role_score, 9), len(disabled), 0, disabled)


def search_relations(executor: Any, payload: Dict[str, Any],
                     universe: Sequence[str], *,
                     graph_scores: Optional[Dict[str, float]] = None,
                     mode: str = "graph",
                     budget: Optional[int] = None,
                     adaptive: bool = True,
                     oracle: Any = None) -> Dict[str, Any]:
    """Evaluate subsets and derive MSMS/MMBS with explicit completeness.

    ``budget`` is a number of subset evaluations, not probes.  When it is
    smaller than ``2 ** len(universe)`` the result is marked incomplete and
    no completeness claim is made.
    """
    universe = sorted(universe)
    oracle = oracle or ExecutorOracle(executor, payload)
    store = EvidenceStore(oracle)
    started = time.perf_counter()
    scores = {op: float((graph_scores or {}).get(op, 0.0)) for op in universe}
    dynamic: Dict[str, float] = {op: 0.0 for op in universe}
    subsets = all_subsets(universe)
    pending = set(subsets)
    evaluation_trace: List[Dict[str, Any]] = []
    first_msms: Optional[Dict[str, Any]] = None
    first_mmbs: Optional[Dict[str, Any]] = None
    limit = len(subsets) if budget is None else max(0, min(budget, len(subsets)))
    while pending and store.evaluations < limit:
        if mode == "graph":
            # The tuple itself breaks ties so the order does not depend on
            # set iteration/hash randomization.
            choice = min(pending, key=lambda item: (_subset_priority(
                item, universe, scores, dynamic), item))
        else:
            # Deterministic exhaustive order: empty first, then size, then
            # lexicographic (the same order as Executor.relations).
            choice = min(pending, key=lambda item: (len(item), item))
        pending.remove(choice)
        record = store.evaluate(choice)
        evaluation_trace.append({
            "disabled": list(choice), "status": record.status,
            "masked": record.masked, "exposed": record.exposed,
        })
        if adaptive and record.status == "OK":
            implicated = choice if record.exposed else ()
            if record.masked:
                implicated = tuple(op for op in universe if op not in choice)
            for op in implicated:
                dynamic[op] = min(0.25, dynamic.get(op, 0.0) + 0.05)
        if first_msms is None or first_mmbs is None:
            msms_now = minimal_masked_sets(universe, store)["confirmed"]
            mmbs_now = minimal_exposed_sets(universe, store)["confirmed"]
            if first_msms is None and msms_now:
                first_msms = {"set": msms_now[0],
                              "evaluations": store.evaluations,
                              "elapsed_seconds": round(
                                  time.perf_counter() - started, 3)}
            if first_mmbs is None and mmbs_now:
                first_mmbs = {"set": mmbs_now[0],
                              "evaluations": store.evaluations,
                              "elapsed_seconds": round(
                                  time.perf_counter() - started, 3)}
    msms = minimal_masked_sets(universe, store)
    mmbs = minimal_exposed_sets(universe, store)
    complete = len(store.records) == len(subsets)
    evidence_complete = (complete and store.unknown == 0 and store.invalid == 0
                         and not msms["unknown"] and not mmbs["unknown"])
    return {
        "universe": universe,
        "msms_ids": msms["confirmed"],
        "mmbs_ids": mmbs["confirmed"],
        "msms_unknown": msms["unknown"],
        "mmbs_unknown": mmbs["unknown"],
        "masked": {key: record.masked for key, record in store.records.items()},
        "exposed": {key: record.exposed for key, record in store.records.items()},
        "evidence_status": {key: record.status
                            for key, record in store.records.items()},
        "evaluations": store.evaluations,
        "subsets_total": len(subsets),
        "complete": complete,
        "evidence_complete": evidence_complete,
        "cache_hits": getattr(oracle, "cache_hits", 0),
        "evidence_reads": store.cache_hits,
        "executor_cache_hits": getattr(oracle, "cache_hits", 0),
        "unknown_subsets": store.unknown,
        "invalid_subsets": store.invalid,
        "first_msms": first_msms,
        "first_mmbs": first_mmbs,
        "wall_seconds": round(time.perf_counter() - started, 3),
        "order": store.order,
        "trace": evaluation_trace,
        "search_mode": mode,
    }


# ---------------------------------------------------------------------------
# v2: role-separated, dual-queue search
# ---------------------------------------------------------------------------
# The legacy ``search_relations`` above is kept untouched so that every
# previously published Graph-only / budget number stays reproducible.  The
# function below is the v2 algorithm: MSMS and MMBS are separate search
# problems with separate score maps and separate queues.  It never prunes a
# candidate subset and never turns UNKNOWN/INVALID into False.

def _normalise_hypotheses(universe, hypotheses, role):
    """Validate model hypotheses against the frozen universe.

    Unknown ids reject the whole hypothesis (a model must not widen U); a
    hypothesis with no usable id is dropped.  Order and duplicates are
    canonicalised so the schedule stays deterministic.
    """
    ids = set(universe)
    accepted = []
    rejected = []
    for item in (hypotheses or {}).get(role, []) or []:
        if isinstance(item, dict):
            raw = item.get("kept_ops") if role == "msms" else item.get("disabled_ops")
            ops = list(raw or [])
        else:
            ops = list(item)
        unknown = [op for op in ops if op not in ids]
        cleaned = tuple(sorted({op for op in ops if op in ids}))
        if unknown:
            rejected.append({"role": role, "ops": ops, "reason": "unknown_ids",
                             "unknown_ids": unknown})
            continue
        if not cleaned:
            rejected.append({"role": role, "ops": ops, "reason": "empty"})
            continue
        if cleaned in accepted:
            continue
        accepted.append(cleaned)
    return accepted, rejected


def _role_score(ops, scores):
    return sum(float(scores.get(op, 0.0)) for op in ops)


def search_relations_role_separated(
        executor, payload, universe, *,
        msms_scores=None,
        mmbs_scores=None,
        budget=None,
        hypotheses=None,
        max_hypothesis_probes_per_role=3,
        oracle=None):
    """Search MSMS and MMBS as two independent problems.

    ``msms_scores`` orders kept sets S (the intervention is D = U \\ S).
    ``mmbs_scores`` orders disabled sets H (the intervention is D = H).
    Changing one score map cannot change the other role's queue order.

    Scheduling:

    1. ``D = EMPTY`` first (the baseline MMBS needs it).
    2. Hypothesis gating: at most ``max_hypothesis_probes_per_role`` per
       role are evaluated, alternating MSMS/MMBS so neither role can
       monopolise the budget.  A hypothesis is prioritised only with
       ``status == "OK"`` and the matching predicate True.  Gated probes
       count toward the budget and are shared through the evidence cache.
    3. Strict alternation between the two queues.  ``D = U`` is only an
       ordinary MMBS candidate (large ``|H|``), so it is no longer forced
       into the second evaluation.

    With ``budget=None`` (or ``2 ** len(universe)``) every subset is
    evaluated exactly once, so the confirmed sets equal exhaustive search.
    """
    universe = sorted(universe)
    n = len(universe)
    total = 2 ** n
    limit = total if budget is None else max(0, min(budget, total))
    oracle = oracle or ExecutorOracle(executor, payload)
    store = EvidenceStore(oracle)
    msms_scores = dict(msms_scores or {})
    mmbs_scores = dict(mmbs_scores or {})
    msms_hyp, msms_rejected = _normalise_hypotheses(universe, hypotheses, "msms")
    mmbs_hyp, mmbs_rejected = _normalise_hypotheses(universe, hypotheses, "mmbs")

    schedule = []
    first_msms = None
    first_mmbs = None
    reused_evidence = 0

    def record(role, disabled):
        nonlocal first_msms, first_mmbs
        already = subset_key(disabled) in store.records
        rec = store.evaluate(disabled)
        if not already:
            schedule.append({
                "step": len(schedule) + 1,
                "role": role,
                "disabled": list(disabled),
                "status": rec.status,
                "masked": rec.masked,
                "exposed": rec.exposed,
            })
            if first_msms is None:
                found = minimal_masked_sets(universe, store)["confirmed"]
                if found:
                    first_msms = {"set": found[0],
                                  "evaluations": store.evaluations}
            if first_mmbs is None:
                found = minimal_exposed_sets(universe, store)["confirmed"]
                if found:
                    first_mmbs = {"set": found[0],
                                  "evaluations": store.evaluations}
        return rec

    if limit > 0:
        record("baseline", ())

    gate = {"msms": [], "mmbs": []}
    witnessed = {"msms": set(), "mmbs": set()}
    rounds = max(len(msms_hyp), len(mmbs_hyp))
    for index in range(rounds):
        for role, items in (("msms", msms_hyp), ("mmbs", mmbs_hyp)):
            if index >= max_hypothesis_probes_per_role or index >= len(items):
                continue
            ops = items[index]
            disabled = (tuple(sorted(set(universe) - set(ops)))
                        if role == "msms" else ops)
            if store.evaluations >= limit:
                gate[role].append({"ops": list(ops), "disabled": list(disabled),
                                   "status": "BUDGET_SKIPPED",
                                   "witness": False, "prioritised": False})
                continue
            rec = record(f"{role}_hypothesis", disabled)
            witness = (rec.status == "OK"
                       and (rec.masked if role == "msms" else rec.exposed) is True)
            if witness:
                witnessed[role].add(ops)
            gate[role].append({"ops": list(ops), "disabled": list(disabled),
                               "status": rec.status, "witness": bool(witness),
                               "prioritised": bool(witness)})

    kept_sets = [combo for size in range(1, n + 1)
                 for combo in itertools.combinations(universe, size)]
    msms_queue = sorted(
        kept_sets,
        key=lambda ops: (0 if ops in witnessed["msms"] else 1, len(ops),
                         -round(_role_score(ops, msms_scores), 9), ops))
    mmbs_queue = sorted(
        kept_sets,
        key=lambda ops: (0 if ops in witnessed["mmbs"] else 1, len(ops),
                         -round(_role_score(ops, mmbs_scores), 9), ops))
    cursors = {"msms": 0, "mmbs": 0}

    def pop(role):
        nonlocal reused_evidence
        queue = msms_queue if role == "msms" else mmbs_queue
        while cursors[role] < len(queue):
            ops = queue[cursors[role]]
            cursors[role] += 1
            disabled = (tuple(sorted(set(universe) - set(ops)))
                        if role == "msms" else ops)
            if subset_key(disabled) in store.records:
                reused_evidence += 1
                continue
            return disabled
        return None

    turn = "msms"
    while store.evaluations < limit:
        disabled = pop(turn)
        executed_role = turn
        if disabled is None:
            other = "mmbs" if turn == "msms" else "msms"
            disabled = pop(other)
            executed_role = other
            if disabled is None:
                break
        record(executed_role, disabled)
        turn = "mmbs" if executed_role == "msms" else "msms"

    msms = minimal_masked_sets(universe, store)
    mmbs = minimal_exposed_sets(universe, store)
    complete = len(store.records) == total
    evidence_complete = (complete and store.unknown == 0 and store.invalid == 0
                         and not msms["unknown"] and not mmbs["unknown"])
    probed = {role: [g for g in gate[role] if g["status"] != "BUDGET_SKIPPED"]
              for role in ("msms", "mmbs")}
    hits = {role: sum(1 for g in probed[role] if g["witness"])
            for role in ("msms", "mmbs")}
    return {
        "universe": universe,
        "msms_ids": msms["confirmed"],
        "mmbs_ids": mmbs["confirmed"],
        "msms_unknown": msms["unknown"],
        "mmbs_unknown": mmbs["unknown"],
        "masked": {key: r.masked for key, r in store.records.items()},
        "exposed": {key: r.exposed for key, r in store.records.items()},
        "evidence_status": {key: r.status for key, r in store.records.items()},
        "evaluations": store.evaluations,
        "subsets_total": total,
        "complete": complete,
        "evidence_complete": evidence_complete,
        "unknown_subsets": store.unknown,
        "invalid_subsets": store.invalid,
        "first_msms": first_msms,
        "first_mmbs": first_mmbs,
        "hypotheses": {
            "accepted": {"msms": [list(item) for item in msms_hyp],
                         "mmbs": [list(item) for item in mmbs_hyp]},
            "rejected": msms_rejected + mmbs_rejected,
            "gate": gate,
            "probed": probed,
            "witness_hits": hits,
            "witness_rate": {
                role: (round(hits[role] / len(probed[role]), 3)
                       if probed[role] else None)
                for role in ("msms", "mmbs")},
        },
        "queues": {
            "msms": [list(item) for item in msms_queue],
            "mmbs": [list(item) for item in mmbs_queue],
        },
        "reused_evidence": reused_evidence,
        "duplicate_probes": 0,
        "cache_hits": store.cache_hits,
        "executor_cache_hits": getattr(oracle, "cache_hits", 0),
        "schedule": schedule,
        "order": store.order,
        "search_mode": "role_separated",
    }
