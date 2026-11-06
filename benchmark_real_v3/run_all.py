"""Reproduce the v3 pilot end to end.

Usage::

    python -m benchmark_real_v3.run_all scan
    python -m benchmark_real_v3.run_all trace
    python -m benchmark_real_v3.run_all screen
    python -m benchmark_real_v3.run_all verify
    python -m benchmark_real_v3.run_all report

Stages are independent; each writes only inside ``benchmark_real_v3`` or the
isolated work root ``<local-path>``.  The upstream project trees are
never modified.
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
STAGES = {
    "scan": ["-m", "benchmark_real_v3.scan_candidates"],
    "trace": ["-m", "benchmark_real_v3.run_suite_all"],
    "screen": ["-m", "benchmark_real_v3.screen"],
    "verify": ["-m", "benchmark_real_v3.verify_all"],
    "registry": ["-m", "benchmark_real_v3.build_registry"],
    "report": ["-m", "benchmark_real_v3.make_report"],
}


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in STAGES:
        print("usage: python -m benchmark_real_v3.run_all "
              + "|".join(STAGES))
        return 2
    steps = [STAGES[sys.argv[1]]]
    if sys.argv[1] == "report":
        # Rebuild the hand-reviewed verdict map first: it fails if a survivor
        # has no recorded verdict, so the report can never silently drop one.
        steps.insert(0, STAGES["registry"])
    for step in steps:
        command = [sys.executable, *step]
        print("$", " ".join(command))
        code = subprocess.call(command, cwd=str(KIT))
        if code:
            return code
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
