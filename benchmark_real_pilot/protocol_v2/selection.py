"""Freeze T_task from P+ coverage and source association only.

There is intentionally no P- parameter in this module.  A caller cannot make
test selection depend on whether the deleted-target variant passes or fails.
"""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from .config import COVERAGE_SOURCE, PROTOCOL_VERSION, TASKS

SELECTION_BASIS = (
    "source_association",
    "original_test_structure",
    "p_plus_coverage",
)


def _sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def compute_selection_hash(task_id: str, selected_test_ids: Iterable[str]) -> str:
    """Stable hash of the selection only, not of any run result."""
    payload = {
        "task_id": task_id,
        "selected_test_ids": sorted(selected_test_ids),
        "basis": list(SELECTION_BASIS),
        "protocol_version": PROTOCOL_VERSION,
    }
    return _sha256_text(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    )


def test_file(nodeid: str) -> str:
    return nodeid.split("::", 1)[0]


def _project_plus_hits(upstream: Dict[str, Any], project_id: str) -> Dict[str, Dict[str, int]]:
    """Read only the P+ trace, never the P- records."""
    record = upstream["projects"][project_id]["plus"]
    trace = record.get("trace") or {}
    return trace.get("hits") or {}


def load_plus_coverage(
    coverage_path: Path,
    tasks: Dict[str, Dict[str, Any]] = TASKS,
) -> Dict[str, Any]:
    """Return the P+-only coverage used to select T_task."""
    upstream = json.loads(coverage_path.read_text(encoding="utf-8"))
    out: Dict[str, Any] = {
        "source": str(coverage_path),
        "contains_p_minus": False,
        "tasks": {},
    }
    for task_id, task in tasks.items():
        project_hits = _project_plus_hits(upstream, task["project_id"])
        label = task["trace_label"]
        tests = {
            nodeid: int(counts[label])
            for nodeid, counts in project_hits.items()
            if label in counts and counts[label] > 0
        }
        out["tasks"][task_id] = {
            "project_id": task["project_id"],
            "trace_label": label,
            "p_plus_hit_tests": dict(sorted(tests.items())),
            "p_plus_hit_test_count": len(tests),
        }
    return out


def select_task_tests(
    task_id: str,
    task: Dict[str, Any],
    plus_hits: Dict[str, int],
) -> List[Dict[str, Any]]:
    """Pure, deterministic selection from P+ hits and allowed source files.

    Every test in an allowed original file that traced to A is retained.  No
    test is removed because of its P- outcome; this function cannot see one.
    """
    allowed = set(task["allowed_test_files"])
    selected = []
    for nodeid, hit_count in sorted(plus_hits.items()):
        if test_file(nodeid) not in allowed:
            continue
        if hit_count <= 0:
            continue
        selected.append(
            {
                "nodeid": nodeid,
                "original_test_file": test_file(nodeid),
                "plus_hit_count": int(hit_count),
                "association": "original_test_calls_target_path",
                "reason": (
                    "P+ trace hit on the target line inside an allowed "
                    "source-associated original test file."
                ),
            }
        )
    if not selected:
        raise ValueError(f"{task_id}: no source-associated P+ trace hits")
    return selected


def build_selection(
    coverage_path: Path,
    tasks: Dict[str, Dict[str, Any]] = TASKS,
) -> Dict[str, Any]:
    coverage = load_plus_coverage(coverage_path, tasks)
    frozen: Dict[str, Any] = {
        "protocol_version": PROTOCOL_VERSION,
        "frozen_at_utc": datetime.now(timezone.utc).isoformat(),
        "selection_basis": list(SELECTION_BASIS),
        "p_minus_consulted": False,
        "coverage_source": str(coverage_path),
        "note": (
            "T_task is frozen from P+ coverage and source association. "
            "P- outcomes are recorded later and never used to add or remove "
            "a selected test."
        ),
        "tasks": {},
    }
    for task_id, task in tasks.items():
        coverage_task = coverage["tasks"][task_id]
        pool = coverage_task["p_plus_hit_tests"]
        selected = select_task_tests(task_id, task, pool)
        selected_ids = [row["nodeid"] for row in selected]
        source_associated_pool = [
            nodeid
            for nodeid in pool
            if test_file(nodeid) in set(task["allowed_test_files"])
        ]
        frozen["tasks"][task_id] = {
            "task_id": task_id,
            "project_id": task["project_id"],
            "project": task["project"],
            "version": task["version"],
            "package": task["package"],
            "source_file": task["source_file"],
            "source_symbol": task["source_symbol"],
            "target_upstream_line": task["target_upstream_line"],
            "target_expected": task["target_expected"],
            "trace_label": task["trace_label"],
            "test_python": task["test_python"],
            "test_pytest": task["test_pytest"],
            "original_test_ids": selected_ids,
            "original_test_source": {
                row["nodeid"]: row["original_test_file"] for row in selected
            },
            "selected_tests": selected,
            "candidate_pool_size": len(pool),
            "source_associated_pool_size": len(source_associated_pool),
            "selection_rule": (
                "all P+ trace-hit tests whose original file is in "
                "allowed_test_files"
            ),
            "selection_reason": task["selection_reason"],
            "test_scope_note": task["test_scope_note"],
            "selection_hash": compute_selection_hash(task_id, selected_ids),
            "t_project": dict(task["project_suite"]),
        }
    return frozen


def freeze_selection(
    out_path: Path,
    coverage_path: Path = Path(COVERAGE_SOURCE),
    tasks: Dict[str, Dict[str, Any]] = TASKS,
) -> Dict[str, Any]:
    selection = build_selection(coverage_path, tasks)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(
        json.dumps(selection, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return selection


def load_selection(path: Path) -> Dict[str, Any]:
    selection = json.loads(path.read_text(encoding="utf-8"))
    if selection.get("p_minus_consulted") is not False:
        raise ValueError("selection file does not prove P- was not consulted")
    for task_id, row in selection["tasks"].items():
        expected = compute_selection_hash(task_id, row["original_test_ids"])
        if row.get("selection_hash") != expected:
            raise ValueError(f"{task_id}: selection hash mismatch")
    return selection
