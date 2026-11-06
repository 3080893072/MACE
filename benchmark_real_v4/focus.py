"""Focused screening of a chosen project, outside the round-robin queue.

The round-robin reviewer spends its budget in project order.  When a specific
mechanism (for example object-state overwrite in a small project with a cheap
suite) is worth reviewing first, this driver runs the same frozen screening
pipeline over a project subset and writes to its own evidence directory, so
the round-robin bookkeeping is untouched.

Usage::

    python -m benchmark_real_v4.focus screen six-1.16.0 itsdangerous-2.0.1
    python -m benchmark_real_v4.focus qualify <candidate_id>   # same as qualify
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import List

import benchmark_real_v4.pipeline as pipeline
from benchmark_real_v4.config import CANDIDATES, EVIDENCE, PROJECTS

FOCUS_STATIC = CANDIDATES / "candidates_static_focus.json"
FOCUS_FUNNEL = EVIDENCE / "screening_funnel_focus.json"
FOCUS_ROWS = EVIDENCE / "screening_rows_focus"
FOCUS_WORK = Path("<local-path>")

FOCUS_BUDGET = {
    "max_candidates_reviewed": 80,
    "max_targeted_minus_runs": 80,
    "max_full_suite_minus_runs": 40,
    "targeted_timeout": 180,
    "full_timeout": 900,
}


def screen(project_ids: List[str]) -> int:
    wanted = set(project_ids)
    data = json.loads((CANDIDATES / "candidates_static.json").read_text(
        encoding="utf-8"))
    data["candidates"] = [row for row in data["candidates"]
                          if row["project_id"] in wanted]
    data["counts"] = {pid: sum(1 for row in data["candidates"]
                               if row["project_id"] == pid)
                      for pid in project_ids}
    FOCUS_STATIC.parent.mkdir(parents=True, exist_ok=True)
    FOCUS_STATIC.write_text(json.dumps(data, ensure_ascii=False, indent=2)
                            + "\n", encoding="utf-8")
    pipeline.PROJECTS = {pid: PROJECTS[pid] for pid in project_ids}
    pipeline.STATIC_PATH = FOCUS_STATIC
    pipeline.FUNNEL_PATH = FOCUS_FUNNEL
    pipeline.ROWS_DIR = FOCUS_ROWS
    pipeline.BUDGET = FOCUS_BUDGET
    pipeline.WORK_ROOT = FOCUS_WORK
    return pipeline.cmd_screen()


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in {"screen"}:
        print("usage: python -m benchmark_real_v4.focus screen <project> [...]")
        return 2
    return screen(sys.argv[2:])


if __name__ == "__main__":
    raise SystemExit(main())
