"""Run the deletion check for one hand-picked candidate.

This is the same P- test as the funnel, used when a structurally selected
candidate sits outside the predeclared review budget.  The selection is made
from the static shape before the run; the driver only records what happens.

Usage::

    python -m benchmark_real_v4.screen_one <candidate_id> [--full]
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict

from benchmark_real_v3 import run_suite as rs
import benchmark_real_v4.pipeline as pipeline
from benchmark_real_v4.config import CANDIDATES, EVIDENCE, PROJECTS

SOURCES = [
    CANDIDATES / "candidates_static.json",
    CANDIDATES / "candidates_static_more.json",
    CANDIDATES / "candidates_static_state.json",
]
ROWS_DIR = EVIDENCE / "screening_rows_extra"
WORK = Path("<local-path>")


def _row(candidate_id: str) -> Dict[str, Any]:
    for source in SOURCES:
        if not source.exists():
            continue
        for row in json.loads(source.read_text(encoding="utf-8"))["candidates"]:
            if row["candidate_id"] == candidate_id:
                return dict(row)
    raise SystemExit(f"unknown candidate {candidate_id}")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_id")
    parser.add_argument("--full", action="store_true")
    args = parser.parse_args()

    row = _row(args.candidate_id)
    pid = row["project_id"]
    plus = json.loads((EVIDENCE / f"{pid}_plus.trace.json").read_text(
        encoding="utf-8"))
    tests = pipeline._hit_tests(plus, row["file"],
                                int(row["target_A"]["line"]),
                                pipeline._excluded_nodes(pid))
    row["p_plus_hit_tests"] = tests
    row["p_plus_hit_test_count"] = len(tests)

    pipeline.WORK_ROOT = WORK
    rs.PROJECTS = PROJECTS
    rs.WORK_ROOT = WORK
    rs.EVIDENCE = EVIDENCE
    base = pipeline._prepare_base(pid)
    pipeline._restore_base(pid, base)
    row["deletion"] = rs.delete_line(base, row["file"],
                                     row["target_A"]["line"])
    if not tests:
        # An empty pytest selection exits non-zero without failing a test;
        # never read that as the suite detecting the deletion.
        row["screening_status"] = "NO_ORIGINAL_TEST_EXECUTES_A"
        row["reason"] = ("No original test executes A; the declared test set "
                         "must be designed explicitly.")
        pipeline._restore_base(pid, base)
        ROWS_DIR.mkdir(parents=True, exist_ok=True)
        name = "manual_" + pipeline._safe(args.candidate_id) + ".json"
        (ROWS_DIR / name).write_text(
            json.dumps(row, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8")
        print(json.dumps({
            "candidate": args.candidate_id,
            "status": row["screening_status"],
            "hits": 0,
            "row": str(ROWS_DIR / name),
        }, ensure_ascii=False))
        return 0
    run = rs.run_pytest(base, pid, nodeids=tests,
                        output_name=f"v4_one_{pipeline._safe(args.candidate_id)}_targeted",
                        trace_files=None, timeout=180)
    row["targeted_minus"] = {
        "returncode": run["returncode"], "timed_out": run["timed_out"],
        "summary": run["summary"], "log": run["log"],
    }
    caught = (run["timed_out"] or run["returncode"] != 0
              or bool(run["summary"].get("failed_nodeids")))
    row["screening_status"] = ("TARGETED_TEST_DETECTS_DELETION" if caught
                               else "TARGETED_TESTS_SURVIVE")
    row["reason"] = ("An original test that executes A fails under P-."
                     if caught else "Targeted tests pass under P-.")
    if args.full and not caught:
        full = rs.run_pytest(base, pid, nodeids=None,
                             output_name=f"v4_one_{pipeline._safe(args.candidate_id)}_full",
                             trace_files=None, timeout=900)
        row["full_minus"] = {
            "returncode": full["returncode"], "timed_out": full["timed_out"],
            "summary": full["summary"], "log": full["log"],
            "duration_seconds": full["duration_seconds"],
        }
        if (full["timed_out"] or full["returncode"] != 0
                or full["summary"].get("failed_nodeids")):
            row["screening_status"] = "PROJECT_SUITE_DETECTS_DELETION"
        else:
            row["screening_status"] = "TEST_SURVIVING_DELETION"
    pipeline._restore_base(pid, base)

    ROWS_DIR.mkdir(parents=True, exist_ok=True)
    name = "manual_" + pipeline._safe(args.candidate_id) + ".json"
    (ROWS_DIR / name).write_text(
        json.dumps(row, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps({
        "candidate": args.candidate_id,
        "status": row["screening_status"],
        "hits": len(tests),
        "row": str(ROWS_DIR / name),
    }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
