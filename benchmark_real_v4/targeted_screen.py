"""Screen the structurally promising candidates first.

The round-robin funnel is unbiased but slow: most of its budget goes to
candidates whose masking write is unconditional, where no legal exposing input
can exist.  This driver consumes ``ranked_conditional.json`` and reviews, per
project, the candidates whose masking write is guarded and whose read pattern
can make deleting A observable.  It uses the same deletion and suite code as
``pipeline.cmd_screen`` and writes to its own evidence directory.

The selection rule is structural and fixed before any model run; it is not
conditioned on benchmark scores.

Usage::

    python -m benchmark_real_v4.targeted_screen [--per-project 8] [--total 40]
"""
from __future__ import annotations

import argparse
import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from benchmark_real_v3 import run_suite as rs
import benchmark_real_v4.pipeline as pipeline
from benchmark_real_v4.config import CANDIDATES, EVIDENCE, PROJECTS, V4

RANKED = V4 / "candidates" / "ranked_conditional.json"
SOURCES = [
    CANDIDATES / "candidates_static.json",
    CANDIDATES / "candidates_static_more.json",
    CANDIDATES / "candidates_static_state.json",
]
TARGET_ROWS = EVIDENCE / "screening_rows_targeted"
TARGET_FUNNEL = EVIDENCE / "screening_funnel_targeted.json"
TARGET_WORK = Path("<local-path>")

BUDGET = {
    "max_targeted_minus_runs": 60,
    "max_full_suite_minus_runs": 30,
    "targeted_timeout": 180,
    "full_timeout": 900,
}


def _rows() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for source in SOURCES:
        if not source.exists():
            continue
        for row in json.loads(source.read_text(encoding="utf-8"))["candidates"]:
            out.setdefault(row["candidate_id"], row)
    return out


def selection(per_project: int, total: int) -> List[Dict[str, Any]]:
    ranked = json.loads(RANKED.read_text(encoding="utf-8"))["candidates"]
    rows = _rows()
    plus = {pid: json.loads((EVIDENCE / f"{pid}_plus.trace.json").read_text(
        encoding="utf-8")) for pid in PROJECTS}
    buckets: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for item in ranked:
        if not item["exposing_input_plausible"]:
            continue
        row = rows.get(item["candidate_id"])
        if row is None:
            continue
        shape = row["static_shape"]
        if not (shape.get("read_before_later_write")
                or shape.get("later_write_reads_A")):
            continue
        tests = pipeline._hit_tests(
            plus[row["project_id"]], row["file"],
            int(row["target_A"]["line"]),
            pipeline._excluded_nodes(row["project_id"]))
        if not tests:
            continue
        row = dict(row)
        row["p_plus_hit_tests"] = tests
        row["p_plus_hit_test_count"] = len(tests)
        row["rank_score"] = item["score"]
        buckets[row["project_id"]].append(row)

    chosen: List[Dict[str, Any]] = []
    for pid, items in buckets.items():
        items.sort(key=lambda row: (-row["rank_score"],
                                    row["target_A"]["line"]))
        chosen.extend(items[:per_project])
    chosen.sort(key=lambda row: (-row["rank_score"], row["project_id"],
                                 row["target_A"]["line"]))
    return chosen[:total]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--per-project", type=int, default=8)
    parser.add_argument("--total", type=int, default=40)
    args = parser.parse_args()

    # Point the shared runner at this driver's work and evidence space.
    pipeline.WORK_ROOT = TARGET_WORK
    pipeline.ROWS_DIR = TARGET_ROWS
    pipeline.BUDGET = BUDGET
    rs.PROJECTS = PROJECTS
    rs.WORK_ROOT = TARGET_WORK
    rs.EVIDENCE = EVIDENCE
    TARGET_ROWS.mkdir(parents=True, exist_ok=True)

    chosen = selection(args.per_project, args.total)
    (TARGET_ROWS / "_selection.json").write_text(
        json.dumps([row["candidate_id"] for row in chosen], indent=2) + "\n",
        encoding="utf-8")
    bases: Dict[str, Path] = {}
    rows: List[Dict[str, Any]] = []
    targeted_used = full_used = 0
    for index, row in enumerate(chosen):
        cid = row["candidate_id"]
        pid = row["project_id"]
        base = bases.setdefault(pid, pipeline._prepare_base(pid))
        pipeline._restore_base(pid, base)
        row["deletion"] = rs.delete_line(
            base, row["file"], row["target_A"]["line"])
        run = rs.run_pytest(
            base, pid, nodeids=row["p_plus_hit_tests"],
            output_name=f"v4_tgt_{index:03d}_{pipeline._safe(cid)}_targeted",
            trace_files=None, timeout=BUDGET["targeted_timeout"])
        targeted_used += 1
        row["targeted_minus"] = {
            "returncode": run["returncode"], "timed_out": run["timed_out"],
            "summary": run["summary"], "log": run["log"],
        }
        caught = (run["timed_out"] or run["returncode"] != 0
                  or bool(run["summary"].get("failed_nodeids")))
        if caught:
            row["screening_status"] = "TARGETED_TEST_DETECTS_DELETION"
            row["reason"] = "An original test that executes A fails under P-."
        else:
            row["screening_status"] = "TARGETED_TESTS_SURVIVE"
            if full_used >= BUDGET["max_full_suite_minus_runs"]:
                row["screening_status"] = "FULL_SUITE_NOT_RUN_BUDGET"
                row["reason"] = "Full-suite P- budget exhausted."
            else:
                full = rs.run_pytest(
                    base, pid, nodeids=None,
                    output_name=(f"v4_tgt_{index:03d}_"
                                 f"{pipeline._safe(cid)}_full"),
                    trace_files=None, timeout=BUDGET["full_timeout"])
                full_used += 1
                row["full_minus"] = {
                    "returncode": full["returncode"],
                    "timed_out": full["timed_out"],
                    "summary": full["summary"], "log": full["log"],
                    "duration_seconds": full["duration_seconds"],
                }
                if (full["timed_out"] or full["returncode"] != 0
                        or full["summary"].get("failed_nodeids")):
                    row["screening_status"] = "PROJECT_SUITE_DETECTS_DELETION"
                    row["reason"] = "Applicable project suite fails under P-."
                else:
                    row["screening_status"] = "TEST_SURVIVING_DELETION"
                    row["reason"] = ("Targeted and applicable full suites "
                                     "pass under P-.")
        pipeline._restore_base(pid, base)
        pipeline._checkpoint(index, row)
        rows.append(row)
        print(json.dumps({"index": index, "candidate": cid,
                          "status": row["screening_status"],
                          "hits": row["p_plus_hit_test_count"]},
                         ensure_ascii=False), flush=True)

    payload = {
        "protocol": "benchmark_real_v4_targeted",
        "selection_rule": "ranked_conditional.exposing_input_plausible",
        "budget": {**BUDGET, "targeted_runs_used": targeted_used,
                   "full_suite_runs_used": full_used},
        "counts": {status: sum(1 for row in rows
                               if row["screening_status"] == status)
                   for status in sorted({row["screening_status"]
                                         for row in rows})},
        "survivors": [row["candidate_id"] for row in rows
                      if row["screening_status"] == "TEST_SURVIVING_DELETION"],
        "candidates": rows,
    }
    TARGET_FUNNEL.write_text(json.dumps(payload, ensure_ascii=False, indent=2)
                             + "\n", encoding="utf-8")
    print(json.dumps({"counts": payload["counts"],
                      "survivors": payload["survivors"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
