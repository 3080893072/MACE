"""Submission claim construction.

The shapes follow the published ``submission_format.md`` exactly.  The
functions here never decide whether a claim is true; they only serialize
already-computed evidence into the public submission language.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

SUBMISSION_SCHEMA_VERSION = "mace-v3-baseline-claims-1.0"

CLAIM_TYPES = (
    "EXPOSING_COUNTEREXAMPLE", "MSMS", "MMBS", "PREREQUISITE_BREAKING",
    "CONDITIONAL_CORRECTNESS", "PROVEN",
)


def operation_ref(op: Dict[str, Any]) -> Dict[str, Any]:
    ref: Dict[str, Any] = {"file": op["file"], "line": int(op["first_line"])}
    if int(op["last_line"]) != int(op["first_line"]):
        ref["end_line"] = int(op["last_line"])
    if op.get("code"):
        ref["code"] = op["code"]
    return ref


def operation_refs(ops: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return [operation_ref(op) for op in ops]


def exposing(payload: Dict[str, Any]) -> Dict[str, Any]:
    return {"type": "EXPOSING_COUNTEREXAMPLE", "input": payload}


def minimal_set(kind: str, payload: Dict[str, Any],
                ops: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
    return {"type": kind, "input": payload,
            "operations": operation_refs(ops)}


def prerequisite(payload: Dict[str, Any], control: Dict[str, Any],
                 ops: Iterable[Dict[str, Any]], note: str) -> Dict[str, Any]:
    return {"type": "PREREQUISITE_BREAKING", "input": payload,
            "control_input": control,
            "operations": operation_refs(ops), "prerequisite": note}


def envelope(task_id: str, claims: List[Dict[str, Any]],
             submission_id: str) -> Dict[str, Any]:
    return {"submission_id": submission_id, "task_id": task_id,
            "claims": claims}


def canonical_claim(claim: Dict[str, Any]) -> str:
    import json

    return json.dumps(claim, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
