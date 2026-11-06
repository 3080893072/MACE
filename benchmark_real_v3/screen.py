"""Run the deletion screening funnel for benchmark v3.

Stages, all chosen before any P- result is observed:

1. Static candidates from ``scan_candidates.py``.
2. Keep candidates whose A line was executed by at least one original test in
   the P+ trace.  Tests are selected from P+ coverage only.
3. Run those hit tests on P-.  A failure is a direct original-test catch.
4. Run the project's applicable full suite on P- for targeted survivors.
   Only a full-suite pass qualifies as ``TEST_SURVIVING_DELETION``.
"""
from __future__ import annotations

import hashlib
import json
import shutil
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, List, Tuple

from benchmark_real_v3.config import (
    BUDGET,
    CANDIDATES,
    EVIDENCE,
    PROJECTS,
    WORK_ROOT,
)
from benchmark_real_v3.run_suite import (
    copy_project,
    delete_line,
    run_pytest,
)

STATIC_PATH = CANDIDATES / "candidates_static.json"
OUT_PATH = EVIDENCE / "screening_funnel.json"
ROWS_DIR = EVIDENCE / "screening_rows"
REVIEW_BUDGET = BUDGET["max_candidates_reviewed"]
TARGET_BUDGET = BUDGET["max_targeted_minus_runs"]
FULL_BUDGET = BUDGET["max_full_suite_minus_runs"]
TARGETED_TIMEOUT = 120
FULL_TIMEOUT = 600


def _checkpoint(index: int, row: Dict[str, Any]) -> None:
    ROWS_DIR.mkdir(parents=True, exist_ok=True)
    (ROWS_DIR / f"{index:03d}.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _trace_path(project_id: str) -> Path:
    return EVIDENCE / f"{project_id}_plus.trace.json"


def _load_plus(project_id: str) -> Dict[str, Any]:
    return json.loads(_trace_path(project_id).read_text(encoding="utf-8"))


def _hit_tests(plus: Dict[str, Any], file: str, line: int) -> List[str]:
    out = []
    for nodeid, files in plus.get("hits", {}).items():
        if line in files.get(file, []):
            out.append(nodeid)
    return sorted(out)


def _static_priority(row: Dict[str, Any]) -> Tuple:
    shape = row["static_shape"]
    return (
        0 if (shape["in_loop"] or shape["in_try"]) else 1,
        1 if shape["read_before_later_write"] else 0,
        len(row["later_assignments"]),
        -row["target_A"]["line"],
    )


def _round_robin(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    per_project: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        per_project[row["project_id"]].append(row)
    for project in per_project:
        per_project[project].sort(key=_static_priority, reverse=True)
    selected = []
    cursor = 0
    while len(selected) < limit:
        added = False
        for project in sorted(per_project):
            rows_p = per_project[project]
            if cursor < len(rows_p) and len(selected) < limit:
                selected.append(rows_p[cursor])
                added = True
        if not added:
            break
        cursor += 1
    return selected


def _select_review(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Deterministic selection over every distinct eligible candidate.

    The corrected budget covers all 403 distinct eligible candidates, so the
    selection is exhaustive and no static shape is privileged.  Round-robin
    over projects only fixes the execution order.
    """
    eligible = [r for r in rows if r["screening_status"] == "STATIC_ELIGIBLE"]
    return _round_robin(eligible, REVIEW_BUDGET)


def _safe(name: str) -> str:
    return (
        name.replace(":", "_").replace("/", "_").replace("\\", "_")
        .replace(".", "_")
    )[:120]


def _prepare_base(project_id: str) -> Path:
    source = PROJECTS[project_id]["root"]
    base = WORK_ROOT / f"{project_id}_minus_base"
    if not base.exists():
        copy_project(source, base)
    return base


def _restore_base(project_id: str, base: Path) -> None:
    source = PROJECTS[project_id]["root"]
    cfg = PROJECTS[project_id]
    for path in (source / cfg["source_dir"]).rglob("*.py"):
        rel = path.relative_to(source)
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(path, target)


def main() -> int:
    static = json.loads(STATIC_PATH.read_text(encoding="utf-8"))
    plus = {
        project_id: _load_plus(project_id)
        for project_id in PROJECTS
    }
    rows = []
    for row in static["candidates"]:
        project_id = row["project_id"]
        tests = _hit_tests(
            plus[project_id], row["file"], row["target_A"]["line"])
        row = dict(row)
        row["p_plus_hit_tests"] = tests
        row["p_plus_hit_test_count"] = len(tests)
        if not tests:
            row["screening_status"] = "NO_ORIGINAL_TEST_EXECUTES_A"
            row["reason"] = (
                "The P+ full-suite trace contains no test that executes A."
            )
        elif not (
            row["static_shape"]["read_before_later_write"]
            or row["static_shape"]["later_write_reads_A"]
        ):
            row["screening_status"] = "STATIC_REJECT_DEAD_BEFORE_READ"
            row["reason"] = (
                "The assigned value is neither read before the next write nor "
                "consumed by that write; deleting A is a dead store, not a "
                "value-change candidate."
            )
        else:
            row["screening_status"] = "STATIC_ELIGIBLE"
            row["reason"] = (
                "P+ coverage plus either a read-before-next-write or a "
                "later write that consumes A."
            )
        rows.append(row)

    eligible = [r for r in rows if r["screening_status"] == "STATIC_ELIGIBLE"]
    review = _select_review(eligible)
    review_ids = {r["candidate_id"] for r in review}
    for row in rows:
        if row["screening_status"] == "STATIC_ELIGIBLE" \
                and row["candidate_id"] not in review_ids:
            row["screening_status"] = "NOT_REVIEWED_BUDGET"
            row["reason"] = (
                f"Eligible but outside the predeclared review budget "
                f"({REVIEW_BUDGET}); no P- was run."
            )

    targeted_used = 0
    full_used = 0
    by_id = {row["candidate_id"]: row for row in rows}
    loaded_rows: Dict[str, Dict[str, Any]] = {}
    if ROWS_DIR.exists():
        for path in sorted(ROWS_DIR.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            loaded_rows[data["candidate_id"]] = data
            targeted_used += int(bool(data.get("targeted_minus")))
            full_used += int(bool(data.get("full_minus")))
    base_by_project: Dict[str, Path] = {}
    for index, row in enumerate(review):
        cid = row["candidate_id"]
        if cid in loaded_rows:
            target = by_id[cid]
            target.clear()
            target.update(loaded_rows[cid])
            continue
        if targeted_used >= TARGET_BUDGET:
            row["screening_status"] = "TARGETED_NOT_RUN_BUDGET"
            row["reason"] = (
                f"Eligible but the targeted-run budget ({TARGET_BUDGET}) was "
                f"exhausted; no P- was run."
            )
            _checkpoint(index, row)
            continue
        project_id = row["project_id"]
        base = base_by_project.setdefault(project_id, _prepare_base(project_id))
        _restore_base(project_id, base)
        deletion = delete_line(
            base, row["file"], row["target_A"]["line"])
        row["deletion"] = deletion
        test_ids = row["p_plus_hit_tests"]
        output = f"screen_{index:03d}_{_safe(row['candidate_id'])}_targeted"
        run = run_pytest(
            base, project_id, nodeids=test_ids, output_name=output,
            trace_files=None, timeout=TARGETED_TIMEOUT,
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
                "At least one original test that executes A fails or times "
                "out under P-."
            )
            _restore_base(project_id, base)
            _checkpoint(index, row)
            continue
        row["screening_status"] = "TARGETED_TESTS_SURVIVE"

        if full_used >= FULL_BUDGET:
            row["screening_status"] = "FULL_SUITE_NOT_RUN_BUDGET"
            row["reason"] = (
                f"Targeted tests survive, but the full-suite budget "
                f"({FULL_BUDGET}) was exhausted."
            )
            _restore_base(project_id, base)
            _checkpoint(index, row)
            continue

        full = run_pytest(
            base, project_id, nodeids=None,
            output_name=f"screen_{index:03d}_{_safe(row['candidate_id'])}_full",
            trace_files=None, timeout=FULL_TIMEOUT,
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
        _checkpoint(index, row)

    counts: Dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row["screening_status"]] += 1
    surviving = [
        row for row in rows
        if row["screening_status"] == "TEST_SURVIVING_DELETION"
    ]
    payload = {
        "protocol": "benchmark_real_v3",
        "budget": {
            **BUDGET,
            "targeted_runs_used": targeted_used,
            "full_suite_runs_used": full_used,
        },
        "counts": dict(sorted(counts.items())),
        "survivors": sorted(
            row["candidate_id"] for row in surviving),
        "candidates": rows,
        "p_plus_traces": {
            project_id: {
                "trace": str(_trace_path(project_id)),
                "tests": len(plus[project_id].get("reports", {})),
                "hits": len(plus[project_id].get("hits", {})),
            }
            for project_id in PROJECTS
        },
    }
    OUT_PATH.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(payload["counts"], ensure_ascii=False, indent=2))
    print("budget", payload["budget"])
    print("survivors", len(surviving))
    for row in surviving:
        print(" ", row["candidate_id"],
              f"tests={row['p_plus_hit_test_count']}")
    print(f"wrote {OUT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
