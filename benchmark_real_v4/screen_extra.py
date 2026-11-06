"""Screen the structurally promising candidates the earlier funnel missed.

The first-pass funnel was written before the source-file list and the extra
static passes were complete, so a large part of the ranked queue never got a
P- run.  This driver consumes ``ranked_conditional.json``, skips any candidate
that already has a decision in an existing funnel, and runs the same targeted
and full-suite deletion checks into its own evidence directory.

Selection is fixed before any model run: conditional later write, a read or
later use of A, and original P+ coverage.  It is not conditioned on scores.

Usage::

    python -m benchmark_real_v4.screen_extra [--limit 70]
"""
from __future__ import annotations

import argparse
import json
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
ROWS_DIR = EVIDENCE / "screening_rows_extra"
FUNNEL = EVIDENCE / "screening_funnel_extra.json"
WORK = Path("<local-path>")

BUDGET = {
    "max_targeted_minus_runs": 80,
    "max_full_suite_minus_runs": 20,
    "targeted_timeout": 180,
    "full_timeout": 900,
}

DECIDED = {"TARGETED_TEST_DETECTS_DELETION",
           "PROJECT_SUITE_DETECTS_DELETION",
           "TEST_SURVIVING_DELETION",
           "TARGETED_TESTS_SURVIVE",
           "FULL_SUITE_NOT_RUN_BUDGET",
           "TARGETED_NOT_RUN_BUDGET"}


def _static_rows() -> Dict[str, Dict[str, Any]]:
    out: Dict[str, Dict[str, Any]] = {}
    for source in SOURCES:
        if not source.exists():
            continue
        for row in json.loads(source.read_text(encoding="utf-8"))["candidates"]:
            out.setdefault(row["candidate_id"], row)
    return out


def _decided() -> set:
    seen = set()
    for path in EVIDENCE.glob("screening_funnel*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        for row in data.get("candidates", []):
            if row.get("screening_status") in DECIDED:
                seen.add(row["candidate_id"])
    return seen


def selection(limit: int) -> List[Dict[str, Any]]:
    ranked = json.loads(RANKED.read_text(encoding="utf-8"))["candidates"]
    rows = _static_rows()
    done = _decided()
    plus = {pid: json.loads((EVIDENCE / f"{pid}_plus.trace.json").read_text(
        encoding="utf-8")) for pid in PROJECTS}
    chosen: List[Dict[str, Any]] = []
    for item in ranked:
        cid = item["candidate_id"]
        if cid in done or not item["exposing_input_plausible"]:
            continue
        row = rows.get(cid)
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
        chosen.append(row)
    chosen.sort(key=lambda row: (-row["rank_score"], row["project_id"],
                                 row["target_A"]["line"]))
    return chosen[:limit]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=70)
    args = parser.parse_args()

    pipeline.WORK_ROOT = WORK
    pipeline.ROWS_DIR = ROWS_DIR
    pipeline.BUDGET = BUDGET
    rs.PROJECTS = PROJECTS
    rs.WORK_ROOT = WORK
    rs.EVIDENCE = EVIDENCE
    ROWS_DIR.mkdir(parents=True, exist_ok=True)

    chosen = selection(args.limit)
    (ROWS_DIR / "_selection.json").write_text(
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
            output_name=f"v4_extra_{index:03d}_{pipeline._safe(cid)}_targeted",
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
                    output_name=(f"v4_extra_{index:03d}_"
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
        "protocol": "benchmark_real_v4_extra",
        "selection_rule": "ranked_conditional.exposing_input_plausible, "
                          "not already decided by an earlier funnel",
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
    FUNNEL.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                      encoding="utf-8")
    print(json.dumps({"counts": payload["counts"],
                      "survivors": payload["survivors"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
