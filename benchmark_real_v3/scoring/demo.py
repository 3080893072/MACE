"""One-command end-to-end scoring demo without any model.

The demo builds five human-authored submission classes from the hidden
reference package: correct, wrong, duplicate, illegal and unverifiable.
It then drives the same ``score_submission`` path used for real submissions
and asserts the expected statuses.

Usage::

    python -m benchmark_real_v3.scoring.demo
    python -m benchmark_real_v3.scoring.demo --out-root D:/tmp/v3_demo
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

from benchmark_real_v3.scoring.engine import (
    HIDDEN,
    score_submission,
)

DEFAULT_OUT = Path("<local-path>")


def _clean(claim: Dict[str, Any]) -> Dict[str, Any]:
    return {
        key: value for key, value in claim.items()
        if key not in ("witness_id", "expected_status")
    }


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _load_refs() -> Dict[str, Dict[str, Any]]:
    refs = {}
    for path in sorted((HIDDEN / "tasks").glob("*/reference.json")):
        ref = json.loads(path.read_text(encoding="utf-8"))
        refs[ref["task_id"]] = ref
    return refs


def _first_op(ref: Dict[str, Any]) -> Dict[str, Any]:
    op = ref["candidate_universe"][0]
    if op.get("kind") == "block":
        return {
            "file": op["file"], "line": op["first_line"],
            "end_line": op["last_line"], "code": op["code"],
        }
    return {"file": op["file"], "line": op["line"], "code": op["code"]}


def _payload_for(ref: Dict[str, Any], role: str) -> Dict[str, Any]:
    for witness in ref["witnesses"].values():
        if witness["role"] == role:
            return witness["payload"]
    raise RuntimeError(f"{ref['task_id']}: no {role} witness")


def make_correct(ref: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "submission_id": f"correct-{ref['task_id']}",
        "task_id": ref["task_id"],
        "claims": [_clean(claim) for claim in ref["reference_claims"]],
    }


def make_wrong(ref: Dict[str, Any]) -> Dict[str, Any]:
    masking = _payload_for(ref, "masking")
    exposing = _payload_for(ref, "exposing")
    return {
        "submission_id": f"wrong-{ref['task_id']}",
        "task_id": ref["task_id"],
        "claims": [
            {"type": "EXPOSING_COUNTEREXAMPLE", "input": masking},
            {
                "type": "MSMS",
                "input": exposing,
                "operations": [_first_op(ref)],
            },
        ],
    }


def make_duplicate(ref: Dict[str, Any]) -> Dict[str, Any]:
    claims = [_clean(claim) for claim in ref["reference_claims"]]
    return {
        "submission_id": f"duplicate-{ref['task_id']}",
        "task_id": ref["task_id"],
        "claims": claims + [dict(claim) for claim in claims],
    }


def make_illegal(ref: Dict[str, Any]) -> Dict[str, Any]:
    op = _first_op(ref)
    return {
        "submission_id": f"illegal-{ref['task_id']}",
        "task_id": ref["task_id"],
        "claims": [
            {"type": "MSMS", "input": {"template": 123}, "operations": [op]},
            {
                "type": "EXPOSING_COUNTEREXAMPLE",
                "input": {"template": 123, "unexpected": True},
            },
            {
                "type": "MSMS",
                "input": _payload_for(ref, "masking"),
                "operations": [{"file": op["file"], "line": 999999}],
            },
            {
                "type": "PROVEN",
                "statement": "The relation holds for every legal input.",
                "proof": {},
            },
            {"type": "MYSTERY_RELATION"},
        ],
    }


def make_unverifiable(ref: Dict[str, Any]) -> Dict[str, Any]:
    op = _first_op(ref)
    return {
        "submission_id": f"unverifiable-{ref['task_id']}",
        "task_id": ref["task_id"],
        "claims": [
            {
                "type": "MSMS",
                "input": _payload_for(ref, "masking"),
                "operations": [{"file": op["file"], "line": 1}],
            },
            {
                "type": "PROVEN",
                "statement": "Unchecked formal proof.",
                "proof": {"claim": "by inspection"},
            },
        ],
    }


def _results_by_status(result: Dict[str, Any]) -> List[str]:
    return [claim["status"] for claim in result["claims"]]


def run(out_root: Path) -> Dict[str, Any]:
    if out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True)
    refs = _load_refs()
    if len(refs) != 5:
        raise RuntimeError(f"expected 5 hidden references, got {len(refs)}")
    report: Dict[str, Any] = {
        "protocol": "mace_benchmark_v3_demo",
        "task_count": len(refs),
        "classes": {},
        "all_expectations_met": True,
    }
    for task_id, ref in refs.items():
        submissions = {
            "correct": make_correct(ref),
            "wrong": make_wrong(ref),
            "duplicate": make_duplicate(ref),
            "illegal": make_illegal(ref),
            "unverifiable": make_unverifiable(ref),
        }
        task_result: Dict[str, Any] = {}
        for label, submission in submissions.items():
            _write(out_root / label / f"{task_id}.json", submission)
            result = score_submission(submission)
            _write(
                out_root / label / f"{task_id}.result.json", result)
            task_result[label] = {
                "statuses": _results_by_status(result),
                "status_counts": result["status_counts"],
                "score": result.get("score"),
                "result": f"{label}/{task_id}.result.json",
            }
        # Expectations for the human-authored demo.
        correct_statuses = task_result["correct"]["statuses"]
        if not all(status == "WITNESS_VERIFIED" for status in correct_statuses):
            report["all_expectations_met"] = False
        if task_result["wrong"]["statuses"] != ["FALSE", "FALSE"]:
            report["all_expectations_met"] = False
        duplicate = task_result["duplicate"]
        half = len(duplicate["statuses"]) // 2
        if not all(status == "WITNESS_VERIFIED"
                   for status in duplicate["statuses"][:half]):
            report["all_expectations_met"] = False
        if not all(status == "DUPLICATE"
                   for status in duplicate["statuses"][half:]):
            report["all_expectations_met"] = False
        if duplicate["score"]["credited_relations"] != len(
                ref["reference_claims"]):
            report["all_expectations_met"] = False
        illegal = task_result["illegal"]["statuses"]
        if illegal[:3] != ["INVALID", "INVALID", "INVALID"]:
            report["all_expectations_met"] = False
        if "UNVERIFIED" not in illegal or "UNSUPPORTED" not in illegal:
            report["all_expectations_met"] = False
        unverifiable = task_result["unverifiable"]["statuses"]
        if unverifiable != ["UNVERIFIED", "UNVERIFIED"]:
            report["all_expectations_met"] = False
        report["classes"][task_id] = task_result
    _write(out_root / "demo_report.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out-root", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args()
    report = run(args.out_root)
    print(json.dumps({
        "all_expectations_met": report["all_expectations_met"],
        "task_count": report["task_count"],
        "out_root": str(args.out_root),
        "report": str(args.out_root / "demo_report.json"),
        "statuses": {
            task: {
                label: data["status_counts"]
                for label, data in classes.items()
            }
            for task, classes in report["classes"].items()
        },
    }, ensure_ascii=False, indent=2))
    return 0 if report["all_expectations_met"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
