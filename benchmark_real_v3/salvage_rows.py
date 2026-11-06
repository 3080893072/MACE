"""Rebuild screening checkpoints for the 0..276 runs completed before the
infinite-loop hang was fixed.

The completed runs left their JUnit XML, log and select files behind.  This
script reconstructs the same row record that ``screen.py`` would have written,
so the resumable screening does not need to rerun 277 candidates.  It reads
only completed evidence; no new P- run is started here.
"""
from __future__ import annotations

import json
from pathlib import Path

from benchmark_real_v3.config import CANDIDATES, EVIDENCE, PROJECTS
from benchmark_real_v3.run_suite import _junit_summary
from benchmark_real_v3.screen import _hit_tests, _select_review, ROWS_DIR


def _command_from_log(path: Path) -> list[str] | None:
    if not path.exists():
        return None
    first = path.read_text(encoding="utf-8", errors="replace").splitlines()
    if not first or not first[0].startswith("$ "):
        return None
    return first[0][2:].split()


def main() -> int:
    static = json.loads(
        (CANDIDATES / "candidates_static.json").read_text(encoding="utf-8"))
    plus = {
        pid: json.loads(
            (EVIDENCE / f"{pid}_plus.trace.json").read_text(encoding="utf-8"))
        for pid in PROJECTS
    }
    rows = []
    for candidate in static["candidates"]:
        row = dict(candidate)
        tests = _hit_tests(
            plus[row["project_id"]], row["file"], row["target_A"]["line"])
        row["p_plus_hit_tests"] = tests
        row["p_plus_hit_test_count"] = len(tests)
        shape = row["static_shape"]
        if not tests:
            row["screening_status"] = "NO_ORIGINAL_TEST_EXECUTES_A"
        elif not (shape["read_before_later_write"]
                  or shape["later_write_reads_A"]):
            row["screening_status"] = "STATIC_REJECT_DEAD_BEFORE_READ"
        else:
            row["screening_status"] = "STATIC_ELIGIBLE"
        rows.append(row)
    review = _select_review(rows)
    ROWS_DIR.mkdir(parents=True, exist_ok=True)
    built = 0
    for index, row in enumerate(review):
        if index > 276:
            break
        targeted = sorted(EVIDENCE.glob(
            f"screen_{index:03d}_*_targeted.junit.xml"))
        if not targeted:
            raise RuntimeError(f"no targeted junit for index {index}")
        full = sorted(EVIDENCE.glob(f"screen_{index:03d}_*_full.junit.xml"))
        t_summary = _junit_summary(targeted[0])
        t_log = targeted[0].with_suffix("").with_suffix(".log")
        t_log = Path(str(targeted[0]).replace(".junit.xml", ".log"))
        row["deletion"] = {
            "file": row["file"],
            "line": row["target_A"]["line"],
            "original_line": row["target_A"]["code"],
            "replacement": "pass  # P-: target A deleted",
            "reconstructed": True,
        }
        row["targeted_minus"] = {
            "command": _command_from_log(t_log),
            "returncode": 0 if not t_summary["failed_nodeids"] else 1,
            "timed_out": False,
            "summary": t_summary,
            "log": str(t_log),
            "junit_xml": str(targeted[0]),
            "reconstructed_from_junit": True,
        }
        if t_summary["failed_nodeids"]:
            row["screening_status"] = "TARGETED_TEST_DETECTS_DELETION"
            row["reason"] = (
                "At least one original test that executes A fails or times "
                "out under P-."
            )
        else:
            row["screening_status"] = "TARGETED_TESTS_SURVIVE"
            if not full:
                row["screening_status"] = "FULL_SUITE_NOT_RUN_BUDGET"
                row["reason"] = (
                    "Targeted tests survive, but no full-suite P- run exists.")
            else:
                f_summary = _junit_summary(full[0])
                f_log = Path(str(full[0]).replace(".junit.xml", ".log"))
                row["full_minus"] = {
                    "command": _command_from_log(f_log),
                    "returncode": 0 if not f_summary["failed_nodeids"] else 1,
                    "timed_out": False,
                    "summary": f_summary,
                    "log": str(f_log),
                    "junit_xml": str(full[0]),
                    "reconstructed_from_junit": True,
                }
                if f_summary["failed_nodeids"]:
                    row["screening_status"] = "PROJECT_SUITE_DETECTS_DELETION"
                    row["reason"] = (
                        "Targeted hit tests pass, but the applicable project "
                        "suite fails under P-.")
                else:
                    row["screening_status"] = "TEST_SURVIVING_DELETION"
                    row["reason"] = (
                        "All original tests that execute A pass under P- and "
                        "the applicable project suite passes under P-.")
        path = ROWS_DIR / f"{index:03d}.json"
        path.write_text(
            json.dumps(row, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        built += 1
    print("reconstructed", built, "checkpoints")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
