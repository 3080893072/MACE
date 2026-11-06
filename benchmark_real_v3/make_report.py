"""Assemble the v3 candidate list, qualified task list and funnel counts."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

from benchmark_real_v3.config import CANDIDATES, EVIDENCE, PROJECTS
from benchmark_real_v3.verify_task import TASKS

STATIC = CANDIDATES / "candidates_static.json"
FUNNEL = EVIDENCE / "screening_funnel.json"
REGISTRY = EVIDENCE / "qualification_registry.json"
OUT_CANDIDATES = CANDIDATES / "candidates_full.json"
OUT_TASKS = TASKS / "qualified_tasks.json"
OUT_FUNNEL = EVIDENCE / "funnel_summary.json"


def _hit_tests(project_id: str, file: str, line: int) -> List[str]:
    path = EVIDENCE / f"{project_id}_plus.trace.json"
    trace = json.loads(path.read_text(encoding="utf-8"))
    return sorted(
        nodeid
        for nodeid, files in trace.get("hits", {}).items()
        if line in files.get(file, [])
    )


def main() -> int:
    static = json.loads(STATIC.read_text(encoding="utf-8"))
    funnel = json.loads(FUNNEL.read_text(encoding="utf-8"))
    registry_payload = (
        json.loads(REGISTRY.read_text(encoding="utf-8"))
        if REGISTRY.exists() else {}
    )
    registry = registry_payload.get("candidates", registry_payload)
    status_by_id = {
        row["candidate_id"]: row for row in funnel["candidates"]
    }

    def _screening_for(project_id: str, target: Dict[str, Any]) -> Dict[str, Any]:
        for candidate in static["candidates"]:
            if (
                candidate["project_id"] == project_id
                and candidate["file"] == target["file"]
                and candidate["target_A"]["line"] == target["line"]
            ):
                return status_by_id.get(candidate["candidate_id"], {})
        return {}

    rows = []
    for candidate in static["candidates"]:
        cid = candidate["candidate_id"]
        screen = status_by_id.get(cid, {})
        evaluation = registry.get(cid, {})
        rows.append({
            **candidate,
            "screening_status": screen.get("screening_status", "NOT_SCREENED"),
            "screening_reason": screen.get("reason", ""),
            "p_plus_hit_tests": screen.get("p_plus_hit_tests", []),
            "p_plus_hit_test_count": screen.get(
                "p_plus_hit_test_count", 0),
            "minus_evidence": {
                key: screen.get(key)
                for key in ("targeted_minus", "full_minus")
                if screen.get(key)
            },
            "qualification": evaluation,
        })
    OUT_CANDIDATES.write_text(
        json.dumps({
            "protocol": "benchmark_real_v3",
            "total_static_candidates": len(rows),
            "candidates": rows,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    counts = Counter(row["screening_status"] for row in rows)
    qualified = []
    for task_dir in sorted(p for p in TASKS.iterdir() if p.is_dir()):
        spec_path = task_dir / "spec.json"
        if not spec_path.exists():
            continue
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        matrix_path = EVIDENCE / f"{spec['task_id']}_matrix.json"
        if not matrix_path.exists():
            continue
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        target = spec["target_operation"]
        screen = _screening_for(spec["project_id"], target)
        hit = _hit_tests(
            spec["project_id"], target["file"], target["line"])
        qualified.append({
            "task_id": spec["task_id"],
            "project_id": spec["project_id"],
            "project": spec["source_version"],
            "difficulty": spec["difficulty"],
            "mechanism": spec["mechanism"],
            "target_operation": target,
            "deletion_method": spec["deletion_method"],
            "test_scope": spec["test_scope"],
            "t_task_selection": (
                "All original tests that execute A in the P+ full-suite "
                "trace; selected from P+ coverage only."
            ),
            "t_task": hit,
            "t_task_count": len(hit),
            "candidate_id": screen.get("candidate_id"),
            "screening_status": screen.get("screening_status"),
            "screening_reason": screen.get("reason"),
            "p_minus_full_suite": screen.get("full_minus"),
            "candidate_universe": spec["candidate_universe"],
            "universe_notes": spec["universe_notes"],
            "inputs": {
                iid: {
                    "role": data["role"],
                    "payload": data["payload"],
                    "msms": data["msms"],
                    "mmbs": data["mmbs"],
                    "masked_strict_EMPTY": data["masked_strict"].get("EMPTY"),
                    "exposed_EMPTY": data["exposed"].get("EMPTY"),
                    "exposed_with_universe_disabled": data["exposed"],
                }
                for iid, data in matrix["inputs"].items()
            },
            "scope": matrix["scope"],
            "matrix_evidence": str(matrix_path),
            "spec": str(spec_path),
        })
    OUT_TASKS.write_text(
        json.dumps({
            "protocol": "benchmark_real_v3",
            "qualified_count": len(qualified),
            "tasks": qualified,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    survivors = [
        row for row in rows
        if row["screening_status"] == "TEST_SURVIVING_DELETION"
    ]
    verdict_counts = Counter(
        row["qualification"].get("verdict", "NOT_EVALUATED")
        for row in survivors
    )
    summary = {
        "static_candidates_distinct": len(rows),
        "static_candidates_rows_before_dedupe": (
            len(rows) + len(static.get("duplicate_rows_removed", []))
        ),
        "screening_counts": dict(sorted(counts.items())),
        "survivors": len(survivors),
        "survivor_verdicts": dict(sorted(verdict_counts.items())),
        "qualified_tasks": [task["task_id"] for task in qualified],
        "budget": funnel.get("budget"),
        "p_plus_traces": funnel.get("p_plus_traces"),
        "projects": {
            pid: {
                "project": cfg["project"],
                "version": cfg["version"],
                "python": cfg["python"],
                "pytest": cfg["pytest"],
                "extra_args": cfg["extra_args"],
                "suite_note": cfg["suite_note"],
            }
            for pid, cfg in PROJECTS.items()
        },
    }
    OUT_FUNNEL.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
