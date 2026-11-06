"""Execute one upstream project suite with per-test line tracing.

This module treats every project tree as data.  It copies the tree to an
isolated work directory, invokes the project's own pytest suite from outside
the source tree, and never imports the candidate package in the controller.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List

from benchmark_real_v3.config import EVIDENCE, PROJECTS, WORK_ROOT

PLUGIN_DIR = Path(__file__).resolve().parent.parent
IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "*.pyo", ".pytest_cache", ".git", ".tox",
    ".venv", "venv", "build", "dist", "*.egg-info",
)


def copy_project(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=IGNORE)


def delete_line(project_root: Path, file: str, line: int,
                expected: str | None = None) -> Dict[str, Any]:
    path = project_root / file
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    index = line - 1
    original = lines[index]
    if expected is not None and expected not in original:
        raise RuntimeError(
            f"line mismatch in {path}: expected {expected!r}, got {original!r}")
    if not original.strip():
        raise RuntimeError(f"line {line} in {path} is blank")
    indent = original[: len(original) - len(original.lstrip())]
    lines[index] = indent + "pass  # P-: target A deleted\n"
    path.write_text("".join(lines), encoding="utf-8")
    return {
        "file": file,
        "line": line,
        "original_line": original.rstrip("\n"),
        "replacement": lines[index].rstrip("\n"),
    }


def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)],
            capture_output=True,
        )
    else:
        import signal

        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError:
            pass


def _test_report_summary(trace: Dict[str, Any] | None) -> Dict[str, Any]:
    reports = (trace or {}).get("reports") or {}
    counts = {"passed": 0, "failed": 0, "error": 0, "skipped": 0, "xfailed": 0}
    for report in reports.values():
        outcome = report.get("outcome")
        if outcome in counts:
            counts[outcome] += 1
    return {
        "reports": len(reports),
        "outcomes": counts,
        "passed_nodeids": sorted(
            nodeid for nodeid, report in reports.items()
            if report.get("outcome") == "passed"
        ),
        "failed_nodeids": sorted(
            nodeid for nodeid, report in reports.items()
            if report.get("outcome") in ("failed", "error")
        ),
    }


def _junit_summary(path: Path) -> Dict[str, Any]:
    if not path.exists():
        return {"reports": 0, "outcomes": {}, "failed_nodeids": []}
    import xml.etree.ElementTree as ET

    root = ET.parse(path).getroot()
    cases = root.findall(".//testcase")
    passed, failed = [], []
    for case in cases:
        nodeid = case.attrib.get("classname", "") + "::" + case.attrib.get(
            "name", "")
        bad = case.find("failure") is not None or case.find("error") is not None
        if bad:
            failed.append(nodeid)
        elif case.find("skipped") is None:
            passed.append(nodeid)
    return {
        "reports": len(cases),
        "outcomes": {"passed": len(passed), "failed": len(failed)},
        "passed_nodeids": sorted(passed),
        "failed_nodeids": sorted(failed),
    }


def run_pytest(
    project_root: Path,
    project_id: str,
    *,
    nodeids: Iterable[str] | None,
    output_name: str,
    trace_files: Iterable[str] | None,
    timeout: int = 1200,
) -> Dict[str, Any]:
    cfg = PROJECTS[project_id]
    EVIDENCE.mkdir(parents=True, exist_ok=True)
    trace_path = EVIDENCE / f"{output_name}.trace.json"
    log_path = EVIDENCE / f"{output_name}.log"
    junit_path = EVIDENCE / f"{output_name}.junit.xml"
    for path in (trace_path, log_path, junit_path):
        if path.exists():
            path.unlink()

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(PLUGIN_DIR), str((project_root / cfg["source_dir"]).resolve())]
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env.pop("PYTEST_ADDOPTS", None)
    if trace_files is not None:
        env["V3_TRACE_ROOT"] = str(project_root.resolve())
        env["V3_TRACE_FILES"] = "\n".join(sorted(trace_files))
        env["V3_TRACE_OUT"] = str(trace_path.resolve())

    select_path = EVIDENCE / f"{output_name}.select.txt"
    if nodeids is not None:
        wanted = sorted(nodeids)
        select_path.write_text("\n".join(wanted) + "\n", encoding="utf-8")
        test_args = sorted({nodeid.split("::", 1)[0] for nodeid in wanted})
        env["V3_SELECT_FILE"] = str(select_path.resolve())
    else:
        test_args = list(cfg["tests"])

    command = [
        cfg["python"], "-m", "pytest",
        *test_args,
        "-q", "--disable-warnings",
        f"--junitxml={junit_path.resolve()}",
        *list(cfg["extra_args"]),
    ]
    if nodeids is not None:
        command.extend(["-p", "benchmark_real_v3.select_plugin"])
    if trace_files is not None:
        command.extend(["-p", "benchmark_real_v3.trace_plugin"])

    started = datetime.now(timezone.utc)
    process = subprocess.Popen(
        command, cwd=project_root, env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace",
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        returncode = process.returncode
    except subprocess.TimeoutExpired:
        # A deleted statement can turn a loop into an infinite loop.  Kill the
        # whole tree: pytest itself is the looping process, but a killed child
        # can leave pipe-holding grandchildren behind on Windows.
        timed_out = True
        _kill_tree(process.pid)
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        returncode = None
        stdout = stdout or ""
        stderr = stderr or ""

    log_path.write_text(
        "$ " + " ".join(command)
        + "\n\n--- stdout ---\n" + stdout
        + "\n--- stderr ---\n" + stderr,
        encoding="utf-8",
    )
    trace = None
    if trace_path.exists():
        trace = json.loads(trace_path.read_text(encoding="utf-8"))
    summary = _test_report_summary(trace)
    if not summary["reports"]:
        summary = _junit_summary(junit_path)
    return {
        "project_id": project_id,
        "variant": output_name,
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_seconds": (
            datetime.now(timezone.utc) - started
        ).total_seconds(),
        "started_utc": started.isoformat(),
        "stdout_tail": stdout[-6000:],
        "stderr_tail": stderr[-6000:],
        "trace": trace,
        "summary": summary,
        "log": str(log_path),
        "trace_json": str(trace_path),
        "junit_xml": str(junit_path),
    }


def source_files(project_id: str) -> List[str]:
    cfg = PROJECTS[project_id]
    root = cfg["root"]
    return sorted(
        path.relative_to(root).as_posix()
        for path in (root / cfg["source_dir"]).rglob("*.py")
    )


def project_source_hash(project_id: str) -> str:
    cfg = PROJECTS[project_id]
    digest = hashlib.sha256()
    for rel in source_files(project_id):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update((cfg["root"] / rel).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def run_plus(project_id: str) -> Dict[str, Any]:
    cfg = PROJECTS[project_id]
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    root = WORK_ROOT / f"{project_id}_plus"
    copy_project(cfg["root"], root)
    run = run_pytest(
        root,
        project_id,
        nodeids=None,
        output_name=f"{project_id}_plus",
        trace_files=source_files(project_id),
    )
    run["source_tree_sha256"] = project_source_hash(project_id)
    run["work_root"] = str(root)
    return run


if __name__ == "__main__":
    project_id = sys.argv[1]
    run = run_plus(project_id)
    print(json.dumps(run["summary"], ensure_ascii=False, indent=2))
    print("rc", run["returncode"], "log", run["log"])
