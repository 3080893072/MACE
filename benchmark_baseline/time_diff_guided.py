"""Measure wall time and score for the phase-3 methods (dev tasks only)."""
from __future__ import annotations

import json
import time
from pathlib import Path

from benchmark_baseline.diff_guided import METHODS, run_task
from benchmark_real_v3.scoring.engine import score_submission

TASKS = [
    "jinja2_bytecode_cache_read",
    "werkzeug_bind_server_name_lower",
    "werkzeug_filestorage_stream_name",
    "werkzeug_get_host_default_empty",
    "werkzeug_secure_filename_ascii_filter",
]
OUT = Path(__file__).resolve().parent / "runs" / "diff_guided" / "timing.json"


def main() -> int:
    rows = {}
    for method in METHODS:
        rows[method] = {}
        for task_id in TASKS:
            start = time.time()
            result = run_task(task_id, method)
            elapsed = time.time() - start
            score = score_submission({
                "task_id": task_id, "claims": result["claims"]})
            rows[method][task_id] = {
                "wall_seconds": round(elapsed, 3),
                "claims": len(result["claims"]),
                "credited_relations": score.get("score", {}).get(
                    "credited_relations"),
                "status_counts": score.get("status_counts"),
                "variant_builds": result["variant_builds"],
                "masked_rows_used": result["masked_rows_used"],
            }
            print(json.dumps({"method": method, "task": task_id,
                              "seconds": round(elapsed, 2)}, ensure_ascii=False),
                  flush=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
