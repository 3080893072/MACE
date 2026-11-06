"""Upstream qualification for click Choice.normalize_choice (line 333).

This is a single-target follow-up to run_upstream.py.  It copies the click
8.4.1 sdist into an isolated work directory, runs the original suite, then
runs the same suite with only the target statement replaced by ``pass``.
"""
from __future__ import annotations

import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from run_upstream import (  # noqa: E402
    OUT_ROOT,
    PROJECTS_ROOT,
    WORK_ROOT,
    copy_project,
    delete_line,
    run_suite,
    sha256,
)

PROJECT = "click-8.4.1"
FILE = "src/click/types.py"
LINE = 333
EXPECTED = "normed_value = ctx.token_normalize_func(normed_value)"
OUT = OUT_ROOT / "upstream_normalize_choice.json"


def summarize(run: dict) -> dict:
    trace = run.get("trace") or {}
    return {
        "returncode": run["returncode"],
        "timed_out": run["timed_out"],
        "stdout_tail": run["stdout_tail"],
        "stderr_tail": run["stderr_tail"],
        "log": str(OUT_ROOT / f"{run['output_name']}.log"),
        "trace": trace,
    }


def main() -> int:
    source = PROJECTS_ROOT / PROJECT
    if not source.exists():
        raise SystemExit(f"missing source tree: {source}")

    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    plus = WORK_ROOT / f"{PROJECT}_normalize_plus"
    copy_project(source, plus)
    plus_hash = sha256(plus / FILE)

    print(f"[{PROJECT}] P+ suite", flush=True)
    plus_run = run_suite(
        plus,
        PROJECT,
        "click",
        "tests",
        {"normalize_choice": {"file": FILE, "line": LINE, "expected": EXPECTED}},
        "click_normalize_choice_plus",
        sys.executable,
    )
    plus_run["output_name"] = "click_normalize_choice_plus"

    minus = WORK_ROOT / f"{PROJECT}_normalize_minus"
    copy_project(source, minus)
    deletion = delete_line(minus, {"file": FILE, "line": LINE, "expected": EXPECTED})
    print(f"[{PROJECT}] P- suite after deleting {FILE}:{LINE}", flush=True)
    minus_run = run_suite(
        minus,
        PROJECT,
        "click",
        "tests",
        {"normalize_choice": {"file": FILE, "line": LINE, "expected": EXPECTED}},
        "click_normalize_choice_minus",
        sys.executable,
    )
    minus_run["output_name"] = "click_normalize_choice_minus"

    def result_counts(run: dict) -> str:
        tail = run["stdout_tail"].strip().splitlines()
        return tail[-1].split(" in ", 1)[0] if tail else ""

    payload = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "project": PROJECT,
        "file": FILE,
        "line": LINE,
        "expected": EXPECTED,
        "plus_source_sha256": plus_hash,
        "deletion": deletion,
        "p_plus": summarize(plus_run),
        "p_minus": summarize(minus_run),
        "same_stdout_tail": plus_run["stdout_tail"] == minus_run["stdout_tail"],
        "same_result_counts": result_counts(plus_run) == result_counts(minus_run),
        "result_counts": result_counts(plus_run),
    }
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    print(f"P+ rc={plus_run['returncode']} P- rc={minus_run['returncode']}")
    print(f"P+ tail: {plus_run['stdout_tail'].strip().splitlines()[-1]}")
    print(f"P- tail: {minus_run['stdout_tail'].strip().splitlines()[-1]}")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
