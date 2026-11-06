"""Stage-2 environment survey for the pre-registered M1 pool.

The M1 funnel's second stage needs each candidate's P+ test trace.  Before
running any trace, this script records whether the pinned project's own suite
can even be collected on this host, with the frozen source tree and a pinned
interpreter.  Failures are recorded per project and are *not* replaced by
another project.

It does not run C, A, B, graph search or any M1 classification.

Usage::

    python -m scripts.m1_stage2_survey
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

KIT = Path(__file__).resolve().parents[1]
OUT = KIT / "runs" / "v3_m1_screening"
COVERAGE_DIR = OUT / "tools"


def _src_root(project_root: Path) -> Path:
    for name in ("src", "lib"):
        if (project_root / name).is_dir():
            return project_root / name
    return project_root


def _test_args(project_root: Path) -> List[str]:
    for name in ("tests", "test"):
        if (project_root / name).is_dir():
            return [name, "--collect-only", "-q"]
    return ["--collect-only", "-q"]


def main() -> int:
    releases = json.loads((OUT / "releases.json").read_text(encoding="utf-8"))
    ledger = json.loads((OUT / "funnel_ledger.json").read_text(
        encoding="utf-8"))
    rows: Dict[str, Any] = {}
    for project, release in releases.items():
        root = OUT / "projects" / f"{project}-{release['version']}"
        if not root.exists():
            rows[project] = {"status": "SOURCE_MISSING"}
            continue
        env = os.environ.copy()
        env["PYTHONPATH"] = str(_src_root(root))
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONHASHSEED"] = "0"
        env.pop("PYTEST_ADDOPTS", None)
        started = time.perf_counter()
        try:
            completed = subprocess.run(
                [sys.executable, "-m", "pytest", *_test_args(root)],
                cwd=str(root), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=120, env=env)
            output = (completed.stdout + completed.stderr).strip().splitlines()
            rows[project] = {
                "status": "COLLECTED" if completed.returncode == 0
                          else "COLLECT_FAILED",
                "returncode": completed.returncode,
                "wall_seconds": round(time.perf_counter() - started, 2),
                "tail": output[-8:],
            }
        except subprocess.TimeoutExpired:
            rows[project] = {"status": "COLLECT_TIMEOUT",
                             "wall_seconds": round(
                                 time.perf_counter() - started, 2)}
        print(f"[stage2] {project}: {rows[project]['status']}", flush=True)
    collected = [p for p, row in rows.items()
                 if row["status"] == "COLLECTED"]
    coverage_available = False
    try:
        completed = subprocess.run(
            [sys.executable, "-c", "import coverage; print(coverage.__version__)"],
            cwd=str(KIT), capture_output=True, text=True, timeout=30,
            env={**os.environ, "PYTHONPATH": str(COVERAGE_DIR)})
        coverage_available = completed.returncode == 0
    except Exception:  # noqa: BLE001
        coverage_available = False
    report = {
        "stage": "plus_test_coverage_survey",
        "projects": rows,
        "collectable": collected,
        "collect_failed_or_missing": sorted(set(releases) - set(collected)),
        "coverage_tool_available": coverage_available,
        "coverage_tool_location": str(COVERAGE_DIR.relative_to(KIT)),
        "candidates_review_budget": ledger["review_budget"],
        "reviewed_static_candidates": ledger["reviewed"],
        "targeted_minus_budget": 800,
        "full_suite_minus_budget": 150,
        "note": (
            "Collection is the entry condition for stage 2, not a P+ trace. "
            "No candidate has a witness yet, so no M1 verdict exists."),
    }
    (OUT / "stage2_survey.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"collectable": collected,
                      "failed": report["collect_failed_or_missing"],
                      "coverage_available": coverage_available},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
