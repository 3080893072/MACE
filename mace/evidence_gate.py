"""Evidence gate for local semantic relations.

This is an additive, independently switchable layer over the existing bounded
verifier.  It does not change ``mace.verify``: it reads the per-relation records
that the verifier already produced from paired P+/P- executions and decides
whether a relation is supported by a *witness* on the declared finite domain.

Three outcomes are kept distinct:

``WITNESS_VERIFIED``
    The expression and condition parsed in their scope, at least one domain
    input made the condition true and produced a supporting observation, and no
    checked input falsified the claim.  This is still a bounded result over the
    declared domain -- never ``PROVEN``.

``REFUTED``
    At least one checked input produced a counterexample (or a fixed-point
    condition held while A still changed the local state).

``UNVERIFIED``
    There is no runnable evidence: the expression could not be typed or
    evaluated, no input satisfied the condition, or a required sub-check
    (observer invariance, fixed-point implication) collected no witness.  An
    unverified candidate is *not* an established relation.

The gate never executes the program again.  It reuses the dual-version rows and
counters from the bounded checker, so enabling it adds no model calls and no
program executions; it only reclassifies evidence that was already collected.

Turning the gate off restores the historical statuses exactly, which makes the
ablation a pure switch.
"""
from __future__ import annotations

from typing import Any, Dict, List, Mapping, Sequence

from .compose import compose_guard

WITNESS_VERIFIED = "WITNESS_VERIFIED"
REFUTED = "REFUTED"
UNVERIFIED = "UNVERIFIED"
VERIFIED_STATUSES = (WITNESS_VERIFIED,)


def _evidence(relation: Mapping[str, Any]) -> Dict[str, Any]:
    """Witness/refutation counts for one relation record from ``verify_bundle``."""
    kind = relation.get("kind")
    if kind == "observer":
        checked = int(relation.get("checked") or 0)
        faithful = int(relation.get("faithful_failures") or 0)
        faithful_minus = int(relation.get("faithful_minus_failures") or 0)
        invariance_checked = int(relation.get("invariance_checked") or 0)
        invariance_failures = int(relation.get("invariance_failures") or 0)
        evaluation_errors = int(relation.get("evaluation_errors") or 0)
        return {
            "checked": checked,
            "witnesses": max(0, invariance_checked - invariance_failures),
            "refutations": faithful + faithful_minus + invariance_failures + evaluation_errors,
            "condition_true": invariance_checked,
            "faithfulness_failures": faithful + faithful_minus,
            "invariance_failures": invariance_failures,
            "evaluation_errors": evaluation_errors,
            "fixed_point_checked": None,
            "fixed_point_failures": None,
        }
    checked = int(relation.get("checked") or 0)
    failures = int(relation.get("failures") or 0)
    return {
        "checked": checked,
        "witnesses": max(0, checked - failures),
        "refutations": failures,
        "condition_true": checked,
        "faithfulness_failures": None,
        "invariance_failures": None,
        "evaluation_errors": None,
        "fixed_point_checked": (int(relation["fixed_point_checked"])
                                if relation.get("fixed_point_checked") is not None else None),
        "fixed_point_failures": (int(relation["fixed_point_failures"])
                                 if relation.get("fixed_point_failures") is not None else None),
    }


def classify(relation: Mapping[str, Any]) -> Dict[str, Any]:
    """Classify one relation record.  Pure function; never runs the program."""
    status = relation.get("status")
    evidence = _evidence(relation)
    base = {
        "id": relation.get("id"),
        "kind": relation.get("kind"),
        "role": relation.get("role"),
        "channel": relation.get("channel"),
        "verifier_status": status,
        "verifier_reason": relation.get("reason"),
        "evidence": evidence,
    }

    if status == REFUTED:
        return {**base, "evidence_status": REFUTED,
                "gate_reason": "at least one checked input produced a counterexample"}
    if status not in ("BOUNDED", "TESTED"):
        return {**base, "evidence_status": UNVERIFIED,
                "gate_reason": "the relation could not be typed or evaluated on the domain"}
    if evidence["refutations"]:
        return {**base, "evidence_status": REFUTED,
                "gate_reason": f"{evidence['refutations']} counterexample(s) remain"}
    if evidence["witnesses"] <= 0:
        return {**base, "evidence_status": UNVERIFIED,
                "gate_reason": ("no domain input both satisfied the condition and produced "
                                "a supporting observation")}
    if relation.get("role") == "fixed_point":
        fixed_checked = evidence["fixed_point_checked"]
        fixed_failures = evidence["fixed_point_failures"]
        if fixed_failures:
            return {**base, "evidence_status": REFUTED,
                    "gate_reason": ("the condition held where A still changed the local "
                                    "state, so it is not a fixed point")}
        if not fixed_checked:
            return {**base, "evidence_status": UNVERIFIED,
                    "gate_reason": ("no domain input satisfied the fixed-point condition, "
                                    "so the no-op implication has no witness")}
    return {**base, "evidence_status": WITNESS_VERIFIED,
            "gate_reason": (f"{evidence['witnesses']} supporting witness(es), "
                            "0 counterexamples on the declared domain")}


def gate_report(report: Mapping[str, Any]) -> Dict[str, Any]:
    """Return a copy of a verification report annotated with gate decisions."""
    records: List[Dict[str, Any]] = [classify(rel) for rel in report.get("relations") or []]
    counts: Dict[str, int] = {WITNESS_VERIFIED: 0, REFUTED: 0, UNVERIFIED: 0}
    for record in records:
        counts[record["evidence_status"]] = counts.get(record["evidence_status"], 0) + 1
    by_id = {record["id"]: record for record in records}
    relations = []
    for rel in report.get("relations") or []:
        record = by_id.get(rel.get("id"))
        annotated = dict(rel)
        if record is not None:
            annotated["evidence_status"] = record["evidence_status"]
            annotated["evidence"] = record["evidence"]
            annotated["gate_reason"] = record["gate_reason"]
        relations.append(annotated)
    return {
        **report,
        "relations": relations,
        "evidence_gate": {
            "enabled": True,
            "counts": counts,
            "records": records,
            "policy": ("only WITNESS_VERIFIED relations may contribute to the "
                       "deterministic composition; an unverified candidate is not "
                       "an established relation"),
            "extra_program_executions": 0,
            "note": ("bounded over the declared finite domain; WITNESS_VERIFIED "
                     "does not mean PROVEN"),
        },
    }


def filtered_report(report: Mapping[str, Any]) -> Dict[str, Any]:
    """A report in which only WITNESS_VERIFIED relations keep a good status.

    ``compose_guard`` consumes statuses, so this is the minimal adapter that
    lets the unchanged composer see exactly the gated relation set.
    """
    gated = gate_report(report)
    decisions = {record["id"]: record["evidence_status"]
                 for record in gated["evidence_gate"]["records"]}
    relations = []
    for rel in gated["relations"]:
        if decisions.get(rel.get("id")) == WITNESS_VERIFIED:
            relations.append(rel)
            continue
        # ``compose_guard`` only accepts BOUNDED/TESTED, so every non-witness
        # relation stays out of the composition.  Keep *why* it stayed out:
        # folding INVALID and REFUTED into UNVERIFIED made the gated statistics
        # unable to distinguish a malformed contract from a disproved one.
        verifier_status = rel.get("status")
        if verifier_status == "INVALID":
            kept = "INVALID"
        elif verifier_status == "REFUTED" or decisions.get(rel.get("id")) == REFUTED:
            kept = "REFUTED"
        else:
            kept = UNVERIFIED
        relations.append({**rel, "status": kept})
    return {**gated, "relations": relations}


def compose_gated(bundle: Any, report: Mapping[str, Any], channels: int) -> Dict[str, Any]:
    """Compose a guard from WITNESS_VERIFIED relations only (gate ON)."""
    return compose_guard(bundle, filtered_report(report), channels)


def compose_ungated(bundle: Any, report: Mapping[str, Any], channels: int) -> Dict[str, Any]:
    """Compose from the verifier's own BOUNDED/TESTED statuses (gate OFF ablation)."""
    return compose_guard(bundle, report, channels)


def rejected_relations(report: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """Relations the original verifier accepted but the gate did not."""
    out = []
    for record in gate_report(report)["evidence_gate"]["records"]:
        if record["verifier_status"] in ("BOUNDED", "TESTED") \
                and record["evidence_status"] != WITNESS_VERIFIED:
            out.append(record)
    return out
