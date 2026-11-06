"""Evaluation-side comparison of v3 baseline submissions to the reference.

This script is *not* part of any baseline.  It is run after the experiment,
reads the frozen hidden reference, and reports which reference relations were
recovered.  The hidden data never enters model input, candidate generation or
parameter tuning.

Usage::

    python scripts/v3_reference_match.py --run runs/v3_baseline_pilot
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Set

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

HIDDEN = KIT / "benchmark_real_v3" / "release" / "HIDDEN"
TASKS = [
    "jinja2_bytecode_cache_read",
    "werkzeug_bind_server_name_lower",
    "werkzeug_filestorage_stream_name",
    "werkzeug_get_host_default_empty",
    "werkzeug_secure_filename_ascii_filter",
]


def _location(op: Dict[str, Any]) -> str:
    first = int(op.get("first_line", op.get("line")))
    last = int(op.get("last_line", op.get("line")))
    end = int(op.get("end_line", last))
    return f"{op['file']}:{first}" if first == end else f"{op['file']}:{first}-{end}"


def _reference_keys(reference: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    keys: Dict[str, Dict[str, Any]] = {}
    for claim in reference.get("reference_claims", []):
        kind = claim["type"]
        if kind == "EXPOSING_COUNTEREXAMPLE":
            key = "EXPOSING"
        elif kind in ("MSMS", "MMBS"):
            key = kind + ":" + "+".join(sorted(_location(op) for op in claim["operations"]))
        elif kind == "PREREQUISITE_BREAKING":
            key = ("PREREQUISITE:"
                   + "+".join(sorted(_location(op) for op in claim["operations"])))
        else:
            key = kind
        keys[key] = claim
    return keys


def _credited(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [claim for claim in result.get("claims", [])
            if claim.get("credit") == 1 and claim.get("relation_key")]


def compare(run_dir: Path) -> Dict[str, Any]:
    per_task = {}
    for task_id in TASKS:
        score_path = run_dir / "tasks" / task_id / "scores" / "C.json"
        ref_path = HIDDEN / "tasks" / task_id / "reference.json"
        if not score_path.exists() or not ref_path.exists():
            per_task[task_id] = {"status": "MISSING_ARTIFACT"}
            continue
        score = json.loads(score_path.read_text(encoding="utf-8"))
        reference = json.loads(ref_path.read_text(encoding="utf-8"))
        ref_keys = _reference_keys(reference)
        credited = _credited(score)
        credited_keys = {claim["relation_key"] for claim in credited}
        matched = sorted(set(ref_keys) & credited_keys)
        missing = sorted(set(ref_keys) - credited_keys)
        extra = sorted(credited_keys - set(ref_keys))
        levels = {}
        for claim in credited:
            levels[claim["relation_key"]] = claim["status"]
        per_task[task_id] = {
            "reference_relations": len(ref_keys),
            "credited_relations": len(credited_keys),
            "matched_reference_relations": len(matched),
            "matched": matched,
            "missing": missing,
            "extra_true_relations_not_in_reference": extra,
            "evidence_levels": levels,
            "status_counts": score.get("status_counts"),
            "claims_submitted": len(score.get("claims", [])),
            "false_claims": sum(
                1 for c in score.get("claims", []) if c.get("status") == "FALSE"),
            "unverified_claims": sum(
                1 for c in score.get("claims", []) if c.get("status") == "UNVERIFIED"),
            "invalid_claims": sum(
                1 for c in score.get("claims", []) if c.get("status") == "INVALID"),
        }
    total_ref = sum(v.get("reference_relations", 0) for v in per_task.values())
    total_match = sum(v.get("matched_reference_relations", 0)
                      for v in per_task.values())
    return {
        "per_task": per_task,
        "total_reference_relations": total_ref,
        "total_matched": total_match,
        "recall": (total_match / total_ref) if total_ref else None,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    payload = compare(args.run)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
