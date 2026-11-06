"""Check that the frozen original T_task actually executes operation A.

For each qualified task this copies the frozen project, installs a pytest
plugin that traces one absolute file/line, runs the frozen T_task node ids on
P+ and records whether A was executed.  This is a supplemental independent
check; it does not call ``verify_task`` or ``run_suite``.

Usage::

    python -m benchmark_real_v3.acceptance_t_task_trace
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

from benchmark_real_v3.config import EVIDENCE, KIT, PROJECTS, V3

WORK = Path("<local-path>")
OUT = EVIDENCE / "acceptance" / "t_task_execution.json"
QUALIFIED = V3 / "tasks" / "qualified_tasks.json"


def _copy_project(root: Path, destination: Path) -> Path:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(
        root, destination,
        ignore=shutil.ignore_patterns(
            "__pycache__", ".pytest_cache", "*.pyc", ".git", ".tox"),
    )
    return destination


def _run(task_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    project_id = payload["project_id"]
    cfg = PROJECTS[project_id]
    copy = _copy_project(cfg["root"], WORK / task_id / "project")
    target = copy / payload["target_operation"]["file"]
    marker = WORK / task_id / "trace_marker.txt"
    junit = WORK / task_id / f"{task_id}_t_task_traced.junit.xml"
    junit.parent.mkdir(parents=True, exist_ok=True)
    env = dict(os.environ)
    env.update({
        "PYTHONPATH": os.pathsep.join([
            str(copy / cfg["source_dir"]), str(KIT)]),
        "PYTHONIOENCODING": "utf-8",
        "MACE_TRACE_FILE": str(target),
        "MACE_TRACE_LINE": str(int(payload["target_operation"]["line"])),
        "MACE_TRACE_MARKER": str(marker),
    })
    command = [
        cfg["python"], "-m", "pytest", *payload["t_task"],
        "-q", "--disable-warnings",
        f"--junitxml={junit}",
        "-p", "benchmark_real_v3.acceptance_trace_plugin",
        *cfg["extra_args"],
    ]
    completed = subprocess.run(
        command, cwd=copy, env=env, timeout=900,
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    executed = marker.exists() and marker.read_text(encoding="utf-8").strip() == "1"
    return {
        "task_id": task_id,
        "command": command,
        "returncode": completed.returncode,
        "executed": executed,
        "stdout_tail": completed.stdout[-1500:],
        "stderr_tail": completed.stderr[-1500:],
        "ok": completed.returncode == 0 and executed,
    }


def main() -> int:
    payloads = json.loads(QUALIFIED.read_text(encoding="utf-8"))["tasks"]
    results: List[Dict[str, Any]] = []
    for payload in payloads:
        result = _run(payload["task_id"], payload)
        results.append(result)
        print(json.dumps({
            "task_id": result["task_id"],
            "ok": result["ok"],
            "executed": result["executed"],
            "returncode": result["returncode"],
        }, ensure_ascii=False))
    report = {
        "schema": "mace_benchmark_v3_t_task_execution",
        "method": (
            "Fresh project copies; sys.settrace plugin; frozen T_task on P+; "
            "separate from verify_task/variant_lab/run_suite."),
        "task_count": len(results),
        "all_executed": all(result["ok"] for result in results),
        "tasks": results,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "all_executed": report["all_executed"],
        "report": str(OUT),
    }, ensure_ascii=False))
    return 0 if report["all_executed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
