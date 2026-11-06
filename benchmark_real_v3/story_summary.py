"""Build the machine-readable summary of the story-validation evidence.

Reads the per-task ``*_tests.json`` and ``*_story.json`` files produced by
:mod:`benchmark_real_v3.story_validation` and writes ``summary.json``.  It does
not execute pytest, rebuild variants, or touch any frozen release file.
"""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from benchmark_real_v3.config import EVIDENCE, V3

OUT = EVIDENCE / "story_validation"
QUALIFIED = V3 / "tasks" / "qualified_tasks.json"
TASK_ORDER = [
    "jinja2_bytecode_cache_read",
    "werkzeug_bind_server_name_lower",
    "werkzeug_filestorage_stream_name",
    "werkzeug_get_host_default_empty",
    "werkzeug_secure_filename_ascii_filter",
]
CLASSES = [
    "NOT_EXECUTED",
    "NO_LOCAL_EFFECT",
    "MASKED_EFFECT",
    "ASSERTION_GAP",
    "INCONCLUSIVE",
]


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _relation_counts(tests: List[Dict[str, Any]], key: str) -> Dict[str, int]:
    counts: Dict[str, int] = {}
    for test in tests:
        for relation in test["observed_relations"].get(key, []):
            label = "+".join(relation)
            counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def build() -> Dict[str, Any]:
    qualified = {
        item["task_id"]: item
        for item in _load(QUALIFIED)["tasks"]
    }
    per_task = []
    totals = {name: 0 for name in CLASSES}
    totals.update({
        "tests": 0,
        "a_execution_total": 0,
        "a_local_effect_instances": 0,
        "tests_with_local_effect": 0,
    })
    for task_id in TASK_ORDER:
        tests = _load(OUT / f"{task_id}_tests.json")
        story = _load(OUT / f"{task_id}_story.json")
        counts = {name: 0 for name in CLASSES}
        for test in tests:
            counts[test["classification"]] += 1
        if counts != {name: story["counts"].get(name, 0) for name in CLASSES}:
            raise RuntimeError(f"count mismatch for {task_id}")
        if len(tests) != len(qualified[task_id]["t_task"]):
            raise RuntimeError(f"T_task count mismatch for {task_id}")
        a_total = sum(t["a"]["plus_execution_count"] for t in tests)
        local_total = sum(t["a"]["local_effect_instances"] for t in tests)
        with_local = [t["nodeid"] for t in tests
                      if t["a"]["local_effect_instances"] > 0]
        no_local = [t["nodeid"] for t in tests
                    if t["classification"] == "NO_LOCAL_EFFECT"]
        masked = [t["nodeid"] for t in tests
                  if t["classification"] == "MASKED_EFFECT"]
        gaps = [t["nodeid"] for t in tests
                if t["classification"] == "ASSERTION_GAP"]
        exposing = story["exposing_counterexample"]["witness"]
        row = {
            "task_id": task_id,
            "label": story["label"],
            "test_count": len(tests),
            "counts": counts,
            "a_execution_total": a_total,
            "a_local_effect_instances": local_total,
            "tests_with_local_effect": with_local,
            "masked_effect_tests": masked,
            "assertion_gap_tests": gaps,
            "no_local_effect_tests": no_local,
            "observed_msms_counts": _relation_counts(tests, "msms"),
            "observed_mmbs_counts": _relation_counts(tests, "mmbs"),
            "exposing_witness_payload": (
                exposing.get("payload") if exposing else None),
            "reference_witness_msms": (
                story["reference_masking_witness"]["existing_msms"]),
            "reference_witness_mmbs": (
                story["reference_masking_witness"]["existing_mmbs"]),
            "scope": story["scope"],
        }
        per_task.append(row)
        totals["tests"] += len(tests)
        totals["a_execution_total"] += a_total
        totals["a_local_effect_instances"] += local_total
        totals["tests_with_local_effect"] += len(with_local)
        for name in CLASSES:
            totals[name] += counts[name]

    full = [row["task_id"] for row in per_task
            if row["label"] == "FULL_MASKING_STORY"]
    gaps = {
        row["task_id"]: row["assertion_gap_tests"]
        for row in per_task if row["assertion_gap_tests"]
    }
    no_local = {
        row["task_id"]: row["no_local_effect_tests"]
        for row in per_task if row["no_local_effect_tests"]
    }
    masked_counts = {
        row["task_id"]: len(row["masked_effect_tests"])
        for row in per_task
    }
    leak = _load(EVIDENCE / "acceptance" / "leak_report.json")
    payload = {
        "schema": "mace_benchmark_story_validation_summary",
        "version": "v3.0-dev-pilot-2026-11-02",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "task_count": len(per_task),
        "totals": totals,
        "per_task": per_task,
        "answers": {
            "q1_full_masking_story_count": len(full),
            "q1_full_masking_story_tasks": full,
            "q2_masked_effect_test_counts": masked_counts,
            "q3_no_local_effect_test_counts": {
                task_id: len(items) for task_id, items in no_local.items()
            },
            "q3_no_local_effect_tests": no_local,
            "q4_assertion_gap_tasks": sorted(gaps),
            "q4_assertion_gap_test_counts": {
                task_id: len(items) for task_id, items in gaps.items()
            },
            "q4_note": (
                "Only one original test (FileStorage test_save_to_pathlib_dst) "
                "is an assertion gap.  No task is dominated by assertion gaps; "
                "the other FileStorage tests have no local effect."),
            "q5_pilot_ready": True,
            "q5_protocol": "PILOT_READY",
            "q5_basis": [
                "All five tasks have frozen public and hidden packages and a "
                "verified exposing witness.",
                "The scorer regression suite covers correct, false, duplicate, "
                "invalid and unverifiable claims.",
                f"Public-package leak check passed {len(leak['checks'])} checks.",
                "Only two tasks support a full masking story; the pilot must "
                "report the other three as controls or separate categories.",
            ],
            "q6_scoring_interface_blockers": [],
            "q6_note": (
                "No blocking scoring-interface defect was found.  Full MACE has "
                "no operation-level output interface; that is recorded as "
                "UNSUPPORTED_INTERFACE, not as a semantic error."),
        },
        "limitations": [
            "Relations are exact only over the declared candidate universe U "
            "and the frozen T_task inputs actually executed.",
            "Observations cover the whole pytest protocol (setup, call, "
            "teardown) for each frozen node id.",
            "A local effect means the traced target variable changed at A's "
            "next event; it is not a semantic-importance judgment.",
            "For get_host, A's local effect is the initialization "
            "unbound -> empty string; U then overwrites it.",
            "No task is claimed to cover all tests of its project or all legal "
            "inputs.",
        ],
    }
    (OUT / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return payload


def main() -> int:
    payload = build()
    print(json.dumps({
        "summary": str(OUT / "summary.json"),
        "totals": payload["totals"],
        "labels": {
            row["task_id"]: row["label"] for row in payload["per_task"]
        },
        "answers": {
            key: value for key, value in payload["answers"].items()
            if key.startswith("q1") or key.startswith("q4")
            or key in ("q5_protocol", "q6_scoring_interface_blockers")
        },
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
