"""Task 1 regression on the five frozen development tasks.

This does not modify any historical run.  It writes only new files under
``reliable_ast_v1/runs/``.
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from benchmark_real_v3.scoring.engine import score_submission
from reliable_ast_v1 import NAME, VERSION
from reliable_ast_v1.analyzer import analyze_spec
from reliable_ast_v1.cases import DEV_TASKS, _v3_spec

OUT = Path(__file__).resolve().parent / "runs"
EXPECTED = 17


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    rows = {}
    total_claims = total_credited = total_builds = total_exec = 0
    total_wall = 0.0
    for task_id in DEV_TASKS:
        start = time.time()
        result = analyze_spec(_v3_spec(task_id))
        elapsed = round(time.time() - start, 3)
        score = score_submission({"task_id": task_id,
                                  "claims": result["claims"]})
        scores = score.get("score", {})
        credited = int(scores.get("credited_relations") or 0)
        rows[task_id] = {
            "claims": len(result["claims"]),
            "credited_relations": credited,
            "status_counts": score.get("status_counts"),
            "variant_builds": result["variant_builds"],
            "executions": result["executions"],
            "wall_seconds": elapsed,
            "analysis_status": result["status"],
            "submitted_claims": result["claims"],
            "uncredited_details": score.get("claims"),
        }
        total_claims += len(result["claims"])
        total_credited += credited
        total_builds += result["variant_builds"]
        total_exec += result["executions"]
        total_wall += elapsed
        print(json.dumps({"task": task_id, "claims": len(result["claims"]),
                          "credited": credited,
                          "builds": result["variant_builds"],
                          "executions": result["executions"],
                          "wall": elapsed}, ensure_ascii=False), flush=True)
    summary = {
        "analyzer": NAME,
        "version": VERSION,
        "scope": "five frozen development tasks only",
        "global_relation_completeness": False,
        "note": ("17/17 means all known development-set relations were "
                 "credited; it is not a claim of global relation completeness "
                 "or an independent generalization result."),
        "expected_credited": EXPECTED,
        "credited_relations": total_credited,
        "claims": total_claims,
        "variant_builds": total_builds,
        "executions": total_exec,
        "wall_seconds": round(total_wall, 3),
        "tasks": rows,
    }
    (OUT / "regression.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
    print(json.dumps({k: summary[k] for k in (
        "analyzer", "version", "credited_relations", "claims",
        "variant_builds", "executions", "wall_seconds")}, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
