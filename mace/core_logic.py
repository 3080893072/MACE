"""Core-logic repair helpers: candidate retention and failure taxonomy.

The audit separated three things that the historical loop mixed together:

* a guard candidate that passed the bounded checker,
* a local relation that failed (possibly for a reason unrelated to the guard),
* the status label used in the final report.

This module keeps the *candidate* independent of the *contract* and makes the
selection rule explicit.  It never reads a reference guard, an offline exact
label, or the model's hidden score.  A candidate is judged only by the bounded
checker on the currently declared finite domain.

The status vocabulary here is intentionally bounded: ``EXACT`` means
``unsound == 0 and incomplete == 0`` on the current domain, never ``PROVEN``.
"""
from __future__ import annotations

from typing import Any, Callable, Dict, Iterable, List, Mapping

GOOD = ("BOUNDED", "TESTED")

# Guard failure taxonomy.  EXACT / SOUND are success outcomes; the rest are
# failure classes required by the audit.
EXACT = "EXACT"
SOUND = "SOUND"
FALSE_ACCEPT = "FALSE_ACCEPT"
FALSE_REJECT = "FALSE_REJECT"
BOTH = "FALSE_ACCEPT_AND_FALSE_REJECT"
EVALUATION_ERROR = "EVALUATION_ERROR"
INVALID_CONTRACT = "INVALID_CONTRACT"
UNVERIFIED_RELATION = "UNVERIFIED_RELATION"
UNKNOWN = "UNKNOWN"

# Relation verdicts that are not guard failures but must stay distinguishable.
VERIFIED_RELATION = "VERIFIED_RELATION"
REFUTED_RELATION = "REFUTED_RELATION"


def _guard_report(report: Mapping[str, Any]) -> Mapping[str, Any]:
    guard = report.get("guard")
    return guard if isinstance(guard, Mapping) else report


def _int(value: Any) -> int:
    try:
        return int(value or 0)
    except (TypeError, ValueError):
        return 0


def guard_exact(guard: Mapping[str, Any]) -> bool:
    """Bounded exactness: no false accept, no false reject, at least one row."""
    return (guard.get("status") in GOOD
            and _int(guard.get("checked")) > 0
            and _int(guard.get("unsound")) == 0
            and _int(guard.get("incomplete")) == 0
            and _int(guard.get("evaluation_errors")) == 0)


def guard_sound(guard: Mapping[str, Any]) -> bool:
    """A sound partial guard: no false accept / evaluation error on the domain."""
    return (guard.get("status") in GOOD
            and _int(guard.get("unsound")) == 0
            and _int(guard.get("evaluation_errors")) == 0)


def guard_error_count(guard: Mapping[str, Any]) -> tuple[int, int, int]:
    return (_int(guard.get("unsound")), _int(guard.get("incomplete")),
            _int(guard.get("evaluation_errors")))


def classify_guard_report(report: Mapping[str, Any]) -> str:
    """Classify a guard report into the audit's failure categories."""
    guard = _guard_report(report)
    if guard.get("status") == "INVALID":
        return INVALID_CONTRACT
    if _int(guard.get("evaluation_errors")) > 0:
        return EVALUATION_ERROR
    unsound = _int(guard.get("unsound"))
    incomplete = _int(guard.get("incomplete"))
    if unsound and incomplete:
        return BOTH
    if unsound:
        return FALSE_ACCEPT
    if incomplete:
        return FALSE_REJECT
    if guard_exact(guard):
        return EXACT
    if guard.get("status") in GOOD:
        return SOUND
    return UNKNOWN


def classify_relation_evidence(relation: Mapping[str, Any]) -> str:
    """Classify one relation without conflating refuted with unverified.

    A relation is *verified* only when the checker's own status is good and the
    counter that makes the claim non-vacuous is positive.  Otherwise it is
    either refuted (a counterexample exists) or unverified (no witness).
    """
    status = relation.get("status")
    if status == "INVALID":
        return INVALID_CONTRACT
    kind = relation.get("kind")
    if kind == "observer":
        if _int(relation.get("faithful_failures")) or \
                _int(relation.get("faithful_minus_failures")) or \
                _int(relation.get("invariance_failures")) or \
                _int(relation.get("evaluation_errors")):
            return REFUTED_RELATION
        if _int(relation.get("invariance_checked")) <= 0:
            return UNVERIFIED_RELATION
    elif relation.get("role") == "fixed_point":
        if _int(relation.get("fixed_point_failures")):
            return REFUTED_RELATION
        if _int(relation.get("fixed_point_checked")) <= 0:
            return UNVERIFIED_RELATION
    elif status not in GOOD:
        return UNVERIFIED_RELATION
    if status not in GOOD:
        return REFUTED_RELATION if status == "REFUTED" else UNVERIFIED_RELATION
    return VERIFIED_RELATION


def _candidate_view(record: Mapping[str, Any]) -> Dict[str, Any]:
    guard = _guard_report(record.get("guard") or {})
    out = dict(record)
    out["guard"] = dict(guard)
    out["classification"] = classify_guard_report({"guard": guard})
    out["exact"] = guard_exact(guard)
    out["sound"] = guard_sound(guard)
    out["errors"] = guard_error_count(guard)
    return out


class CandidatePool:
    """Retain guard candidates; replace an exact incumbent only after revocation.

    Selection is deliberately runtime-only: it uses the checker's bounded
    status on the current domain.  It never consults a reference guard or an
    offline exact label.  If a new domain exposes a counterexample, ``recheck``
    updates the incumbent's report and revocation is allowed.
    """

    def __init__(self, prefer: str = "qwen"):
        if prefer not in ("qwen", "derived"):
            raise ValueError("prefer must be 'qwen' or 'derived'")
        self.prefer = prefer
        self._items: List[Dict[str, Any]] = []

    def offer(self, record: Mapping[str, Any]) -> Dict[str, Any]:
        item = _candidate_view(record)
        item.setdefault("source", "qwen")
        item.setdefault("round", 0)
        item.setdefault("expr", (item["guard"] or {}).get("expr"))
        self._items.append(item)
        return item

    def recheck(self, evaluator: Callable[[str], Mapping[str, Any]]) -> List[Dict[str, Any]]:
        """Re-evaluate every stored candidate on the current verification domain."""
        for item in self._items:
            expr = item.get("expr")
            if not expr:
                continue
            try:
                report = evaluator(expr)
            except Exception as exc:  # noqa: BLE001 - a checker failure is a status
                item["guard"] = {"status": "ERROR", "expr": expr,
                                 "unsound": 0, "incomplete": 0,
                                 "evaluation_errors": 1, "checked": 0,
                                 "reason": f"{type(exc).__name__}: {exc}"}
            else:
                item["guard"] = dict(_guard_report(report))
            refreshed = _candidate_view(item)
            item.clear()
            item.update(refreshed)
        return self._items

    def select(self) -> Dict[str, Any] | None:
        if not self._items:
            return None

        def prefer_key(item):
            # Earlier rounds win ties, so an early exact guard is not displaced
            # by a later duplicate.
            return (0 if item.get("source") == self.prefer else 1,
                    int(item.get("round") or 0), len(item.get("expr") or ""))

        valid = [item for item in self._items if item["guard"].get("status") in GOOD]
        exact = [item for item in valid if item["exact"]]
        if exact:
            chosen = min(exact, key=prefer_key)
            reason = (f"exact bounded guard kept; source={chosen.get('source')}, "
                      f"round={chosen.get('round')}; later candidates were not "
                      "allowed to overwrite it")
        else:
            sound = [item for item in valid if item["sound"]]
            if sound:
                chosen = min(sound, key=lambda item: (item["errors"][1],
                                                      item["errors"][2],
                                                      prefer_key(item)))
                reason = ("no exact candidate; kept the soundest partial guard "
                          f"(incomplete={chosen['guard'].get('incomplete')})")
            elif valid:
                chosen = min(valid, key=lambda item: (item["errors"][0],
                                                      item["errors"][1],
                                                      item["errors"][2],
                                                      prefer_key(item)))
                reason = ("no sound/exact candidate; kept the least unsound "
                          "bounded candidate")
            else:
                chosen = max(self._items, key=lambda item: int(item.get("round") or 0))
                chosen = dict(chosen)
                chosen["exact"] = False
                chosen["sound"] = False
                reason = "no candidate passed the bounded checker; kept the latest for reporting"

        def _is_chosen(item):
            return item is chosen or (
                item.get("expr") == chosen.get("expr")
                and item.get("source") == chosen.get("source")
                and item.get("round") == chosen.get("round"))

        rejected = [item for item in self._items if not _is_chosen(item)]
        if rejected:
            reason += "; not selected: " + ", ".join(
                f"{item.get('source')}@{item.get('round')}="
                f"{item.get('classification')}" for item in rejected)

        for item in self._items:
            item["selected"] = _is_chosen(item)
            if item["selected"]:
                item["decision"] = reason
            elif item.get("classification") == EXACT:
                item["decision"] = "not selected: another exact candidate was preferred"
            elif item.get("classification") in (INVALID_CONTRACT, EVALUATION_ERROR, UNKNOWN):
                item["decision"] = f"not selected: {item.get('classification')}"
            elif item.get("sound"):
                item["decision"] = "not selected: worse bounded residual than the chosen sound candidate"
            else:
                item["decision"] = "not selected: unsound or less complete than the chosen candidate"
        out = dict(chosen)
        out["selection_reason"] = reason
        return out

    def history(self) -> List[Dict[str, Any]]:
        return [dict(item) for item in self._items]
