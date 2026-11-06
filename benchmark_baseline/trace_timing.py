"""Measure one P+ trace per development task (phase-1 timing evidence).

Adds a new file only; it does not alter the frozen AST run logs.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from benchmark_baseline.ast_method import (
    PROBE_BY_TASK,
    PUBLIC_FILE_CACHE,
    _build,
    _observe,
    _trace,
    input_pool,
)
from benchmark_baseline.prompts import public_task

TASKS = [
    "jinja2_bytecode_cache_read",
    "werkzeug_bind_server_name_lower",
    "werkzeug_filestorage_stream_name",
    "werkzeug_get_host_default_empty",
    "werkzeug_secure_filename_ascii_filter",
]
OUT = Path(__file__).resolve().parent / "runs" / "ast" / "trace_timing.json"


def main() -> int:
    rows = {}
    for task_id in TASKS:
        task = public_task(task_id)
        project_id = task["project_id"]
        PUBLIC_FILE_CACHE[task_id] = task["target_operation"]["file"]
        probe = PROBE_BY_TASK[task_id]
        cache = {}
        start = time.time()
        plus = _build(project_id, task_id, "plus", [], cache)
        build_seconds = time.time() - start
        payload = input_pool(task_id)[0]
        start = time.time()
        observation = _observe(project_id, plus, probe, payload)
        probe_seconds = time.time() - start
        start = time.time()
        lines = _trace(project_id, plus, probe,
                       task["target_operation"]["file"], payload)
        trace_seconds = time.time() - start
        rows[task_id] = {
            "build_seconds": round(build_seconds, 3),
            "probe_seconds": round(probe_seconds, 3),
            "trace_seconds": round(trace_seconds, 3),
            "trace_line_count": len(lines),
            "probe_ok": observation["ok"],
        }
        print(json.dumps({"task": task_id, **rows[task_id]},
                         ensure_ascii=False), flush=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
