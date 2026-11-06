"""Round-2 screening of the candidates left outside the round-1 budget.

Declaration, written before any round-2 P- run was observed:

* Round 1 reviewed the first 160 of 426 statically eligible candidates that
  are executed by at least one original test, and produced 10 survivors.
* The pilot target is about five qualified tasks; ten survivors were not
  enough to expect five once masking relations are checked.
* Round 2 therefore reviews every remaining eligible candidate (the 266
  marked ``NOT_REVIEWED_BUDGET``), with the same static selection order and
  the same targeted-then-full-suite rule.  No round-1 P- outcome is used to
  order round 2.
* Full-suite runs are capped at the 30 runs left from the declared total of
  40.  If more survivors need a full run, they are recorded as
  ``FULL_SUITE_NOT_RUN_BUDGET``.
"""
from __future__ import annotations

import json
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List

from benchmark_real_v3.config import BUDGET, EVIDENCE, PROJECTS
from benchmark_real_v3.run_suite import run_pytest
from benchmark_real_v3.screen import (
    OUT_PATH,
    _prepare_base,
    _restore_base,
    _round_robin,
    _safe,
    _static_priority,
)

ROUND2_OUT = EVIDENCE / "screening_funnel_round2.json"
ROUND2_TARGETED_BUDGET = 266
ROUND2_FULL_BUDGET = 30


def _select_remaining(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = [r for r in rows if r["screening_status"] == "NOT_REVIEWED_BUDGET"]
    rows.sort(key=_static_priority, reverse=True)
    return _round_robin(rows, ROUND2_TARGETED_BUDGET)


def main() -> int:
    payload = json.loads(OUT_PATH.read_text(encoding="utf-8"))
    rows = payload["candidates"]
    review = _select_remaining(rows)
    targeted_used = 0
    full_used = 0
    base_by_project: Dict[str, Path] = {}
    for index, row in enumerate(review):
        project_id = row["project_id"]
        base = base_by_project.setdefault(
            project_id, _prepare_base(project_id))
        _restore_base(project_id, base)
        from benchmark_real_v3.run_suite import delete_line

        row["deletion"] = delete_line(
            base, row["file"], row["target_A"]["line"])
        row["screening_round"] = 2
        output = f"r2_{index:03d}_{_safe(row['candidate_id'])}_targeted"
        run = run_pytest(
            base, project_id, nodeids=row["p_plus_hit_tests"],
            output_name=output, trace_files=None,
        )
        targeted_used += 1
        row["targeted_minus"] = {
            "command": run["command"],
            "returncode": run["returncode"],
            "timed_out": run["timed_out"],
            "summary": run["summary"],
            "log": run["log"],
            "junit_xml": run["junit_xml"],
        }
        caught = (
            run["timed_out"]
            or run["returncode"] != 0
            or bool(run["summary"].get("failed_nodeids"))
        )
        if caught:
            row["screening_status"] = "TARGETED_TEST_DETECTS_DELETION"
            row["reason"] = (
                "At least one original test that executes A fails under P-."
            )
            _restore_base(project_id, base)
            continue
        row["screening_status"] = "TARGETED_TESTS_SURVIVE"
        if full_used >= ROUND2_FULL_BUDGET:
            row["screening_status"] = "FULL_SUITE_NOT_RUN_BUDGET"
            row["reason"] = (
                f"Targeted tests survive, but the round-2 full-suite budget "
                f"({ROUND2_FULL_BUDGET}) was exhausted."
            )
            _restore_base(project_id, base)
            continue
        full = run_pytest(
            base, project_id, nodeids=None,
            output_name=f"r2_{index:03d}_{_safe(row['candidate_id'])}_full",
            trace_files=None,
        )
        full_used += 1
        row["full_minus"] = {
            "command": full["command"],
            "returncode": full["returncode"],
            "timed_out": full["timed_out"],
            "summary": full["summary"],
            "log": full["log"],
            "junit_xml": full["junit_xml"],
        }
        if full["timed_out"] or full["returncode"] != 0 \
                or full["summary"].get("failed_nodeids"):
            row["screening_status"] = "PROJECT_SUITE_DETECTS_DELETION"
            row["reason"] = (
                "Targeted hit tests pass, but the applicable project suite "
                "fails under P-."
            )
        else:
            row["screening_status"] = "TEST_SURVIVING_DELETION"
            row["reason"] = (
                "All original tests that execute A pass under P- and the "
                "applicable project suite passes under P-."
            )
        _restore_base(project_id, base)

    counts: Dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row["screening_status"]] += 1
    survivors = [
        row["candidate_id"] for row in rows
        if row["screening_status"] == "TEST_SURVIVING_DELETION"
    ]
    output = {
        "protocol": "benchmark_real_v3",
        "round": 2,
        "declared_budget": {
            "targeted_runs": ROUND2_TARGETED_BUDGET,
            "full_suite_runs": ROUND2_FULL_BUDGET,
        },
        "used": {
            "targeted_runs": targeted_used,
            "full_suite_runs": full_used,
        },
        "counts": dict(sorted(counts.items())),
        "survivors": sorted(survivors),
        "round2_reviewed": [row["candidate_id"] for row in review],
    }
    ROUND2_OUT.write_text(
        json.dumps(output, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(output["used"], indent=2))
    print(json.dumps(output["counts"], indent=2))
    print("survivors", len(survivors))
    for cid in survivors:
        row = next(r for r in rows if r["candidate_id"] == cid)
        print(" ", cid, "tests=", row["p_plus_hit_test_count"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
