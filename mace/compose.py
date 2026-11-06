"""Deterministic guard composition from verified relations.

This is the part of MACE that is *not* the model: given a contract whose
relations have been checked, the guard is assembled from them by a fixed rule

    guard = (OR over verified fixed-point conditions)
            OR (AND over channels of the OR of that channel's conditions)

Nothing here looks at the input domain, the real outputs, or the model's own
``mask_guard``.  It only rearranges conditions the checker already accepted, so
the result is a *candidate* that then has to pass the same bounded check as any
other guard.

If a channel has no verified observer, the composition cannot cover the whole
output; it is reported ``INCOMPLETE`` rather than silently dropping the channel.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Mapping, Sequence

GOOD = ("BOUNDED", "TESTED")


def _by_id(report: Mapping[str, Any]) -> Dict[str, Dict[str, Any]]:
    return {r["id"]: r for r in (report or {}).get("relations") or []}


def _or(parts: Sequence[str]) -> str:
    parts = [p for p in parts if p and p.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return f"({parts[0]})"
    return "(" + " or ".join(f"({p})" for p in parts) + ")"


def _and(parts: Sequence[str]) -> str:
    parts = [p for p in parts if p and p.strip()]
    if not parts:
        return ""
    if len(parts) == 1:
        return f"({parts[0]})"
    return "(" + " and ".join(f"({p})" for p in parts) + ")"


def _has_witness(row: Mapping[str, Any]) -> tuple[bool, str]:
    """Whether a relation has a non-vacuous witness on the checked domain."""
    kind = row.get("kind")
    checked = int(row.get("checked") or 0)
    if kind == "observer":
        if checked <= 0:
            return False, "no usable input"
        if int(row.get("invariance_checked") or 0) <= 0:
            return False, "condition never true on the domain"
        if (int(row.get("faithful_failures") or 0)
                or int(row.get("faithful_minus_failures") or 0)
                or int(row.get("invariance_failures") or 0)
                or int(row.get("evaluation_errors") or 0)):
            return False, "counterexample or evaluation error"
        return True, ""
    if row.get("role") == "fixed_point":
        if checked <= 0:
            return False, "no usable input"
        if int(row.get("fixed_point_checked") or 0) <= 0:
            return False, "fixed-point condition never true on the domain"
        if int(row.get("fixed_point_failures") or 0):
            return False, "fixed-point counterexample"
        return True, ""
    if checked <= 0:
        return False, "no usable input"
    if int(row.get("failures") or 0):
        return False, "counterexample"
    return True, ""


def compose_guard(bundle: Any, report: Mapping[str, Any], channels: int,
                  require_witness: bool = False) -> Dict[str, Any]:
    """Assemble a sufficient guard candidate from verified relations.

    ``require_witness`` is the repaired mode's evidence boundary.  A relation
    whose condition was never true on the declared domain is not evidence, even
    if the bounded checker labels it ``BOUNDED``.  Such a relation is listed in
    ``unverified_relations`` and cannot enter the OR/AND.

    Even with ``require_witness``, this function only composes *sufficient*
    conditions.  It does not infer necessary conditions, so the result is a
    candidate, not a proof of equivalence.
    """
    rows = _by_id(report)
    verified = set()
    unverified_relations: List[Dict[str, Any]] = []
    for rid, row in rows.items():
        if row.get("status") not in GOOD:
            continue
        if require_witness:
            ok, why = _has_witness(row)
            if not ok:
                unverified_relations.append({"id": rid, "reason": why,
                                             "kind": row.get("kind"),
                                             "role": row.get("role"),
                                             "channel": row.get("channel")})
                continue
        verified.add(rid)

    fixed = [r for r in bundle.upstream
             if getattr(r, "role", "") == "fixed_point" and r.id in verified]
    per_channel: Dict[int, List[Any]] = {}
    for rel in bundle.observers:
        if rel.id in verified and rel.channel is not None:
            per_channel.setdefault(int(rel.channel), []).append(rel)

    missing = [c for c in range(channels) if c not in per_channel]
    upstream_text = _or([r.condition for r in fixed])
    downstream_text = _and([_or([r.condition for r in per_channel[c]]) for c in sorted(per_channel)])

    parts: List[Dict[str, Any]] = []
    for rel in fixed:
        parts.append({"relation": rel.id, "op": "or", "text": rel.condition,
                      "source_lines": list(rel.source_lines)})
    for channel in sorted(per_channel):
        for rel in per_channel[channel]:
            parts.append({"relation": rel.id, "op": "and", "channel": channel,
                          "text": rel.condition, "source_lines": list(rel.source_lines)})

    if upstream_text and downstream_text:
        assembled = f"{upstream_text} or {downstream_text}"
    else:
        assembled = upstream_text or downstream_text

    # A missing channel cannot be dropped: the guard would then accept inputs
    # where that channel differs.  So an uncovered channel means no guard at
    # all, not a weaker one.
    if not assembled:
        status, expr = "UNKNOWN", None
        reason = "no verified relation can contribute to the guard"
        missing_reasons = ["no sufficient condition with a non-vacuous witness"]
    elif missing:
        status, expr = "INCOMPLETE", None
        reason = (f"channels {missing} have no verified observer, so no guard can "
                  "cover the whole output")
        missing_reasons = [f"channel {c} has no witnessed observer" for c in missing]
    else:
        status, expr = "COMPOSED", assembled
        reason = "assembled from verified fixed-point and observer conditions"
        missing_reasons = ["necessary conditions are not represented in the contract language"]

    sufficient = []
    for rel in fixed:
        sufficient.append({"relation": rel.id, "kind": "upstream",
                           "role": "fixed_point", "condition": rel.condition,
                           "guarantee": "sufficient for A being a local no-op"})
    for channel in sorted(per_channel):
        for rel in per_channel[channel]:
            sufficient.append({"relation": rel.id, "kind": "observer",
                               "channel": channel, "condition": rel.condition,
                               "guarantee": "sufficient for channel invariance"})

    return {
        "status": status,
        "reason": reason,
        "expr": expr,
        "partial_expr": assembled or None,
        "channels_covered": sorted(per_channel),
        "missing_channels": missing,
        "missing_reasons": missing_reasons,
        "fixed_point_relations": [r.id for r in fixed],
        "observer_relations": [r.id for c in sorted(per_channel) for r in per_channel[c]],
        "parts": parts,
        # The contract language has sufficient conditions (fixed-point
        # conditions and observer conditions), but no necessary-condition
        # field.  Keeping this explicit prevents a sufficient guard from being
        # reported as a complete or proven equivalence.
        "semantics": "sufficient_only",
        "sufficient_conditions": sufficient,
        "necessary_conditions": [],
        "exact_equivalence": "not_established",
        "complete": False,
        "guard_complete": False,
        "unverified_relations": unverified_relations,
    }
