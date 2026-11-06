"""Run upstream pytest suites for P+ and P- variants of the three real tasks.

The upstream sdists are copied into isolated work directories.  This script
lives outside those directories and treats them as data: it never imports the
packages itself, it only invokes pytest in the copy with a fixed environment.
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
from typing import Any, Dict, List

KIT = Path(__file__).resolve().parents[2]
QUAL_DIR = Path(__file__).resolve().parent
PROJECTS_ROOT = Path("<local-path>")
WORK_ROOT = Path("<local-path>")
OUT_ROOT = QUAL_DIR / "out"
PLUGIN_DIR = QUAL_DIR

PROJECTS: Dict[str, Dict[str, Any]] = {
    "click-8.4.1": {
        "package": "click",
        "tests": "tests",
        "source_fetch": PROJECTS_ROOT / "click-8.4.1",
        "targets": {
            "truncate_visible": {
                "file": "src/click/_textwrap.py",
                "line": 23,
                "expected": "cut = 0",
            },
        },
    },
    "werkzeug-2.2.3": {
        "package": "werkzeug",
        "tests": "tests",
        "python": "<local-path>",
        "extra_args": ["-m", "not dev_server"],
        "source_fetch": PROJECTS_ROOT / "werkzeug-2.2.3",
        "targets": {
            "url_unparse": {
                "file": "src/werkzeug/urls.py",
                "line": 605,
                "expected": "url = s(\"\")",
            },
            "headerset_update": {
                "file": "src/werkzeug/datastructures.py",
                "line": 2266,
                "expected": "inserted_any = False",
            },
        },
    },
}

COPY_IGNORE = shutil.ignore_patterns(
    "__pycache__",
    "*.pyc",
    "*.pyo",
    ".pytest_cache",
    ".git",
    ".tox",
    ".venv",
    "venv",
    "build",
    "dist",
    "*.egg-info",
)


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def copy_project(source: Path, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=COPY_IGNORE)


def delete_line(project_copy: Path, spec: Dict[str, Any]) -> Dict[str, Any]:
    path = project_copy / spec["file"]
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    index = spec["line"] - 1
    original = lines[index]
    expected = spec["expected"]
    if expected not in original:
        raise RuntimeError(
            f"line mismatch in {path}: expected {expected!r}, got {original!r}"
        )
    indent = original[: len(original) - len(original.lstrip())]
    lines[index] = indent + "pass  # P-: target A deleted\n"
    path.write_text("".join(lines), encoding="utf-8")
    return {
        "file": spec["file"],
        "line": spec["line"],
        "expected": expected,
        "original_line": original.rstrip("\n"),
        "replacement": lines[index].rstrip("\n"),
    }


def package_version(project_copy: Path, package: str) -> str | None:
    init = project_copy / "src" / package / "__init__.py"
    if not init.exists():
        return None
    for line in init.read_text(encoding="utf-8").splitlines():
        if line.strip().startswith("__version__"):
            return line.split("=", 1)[1].strip().strip("\"'")
    pkg_info = project_copy / "PKG-INFO"
    if pkg_info.exists():
        for line in pkg_info.read_text(encoding="utf-8", errors="replace").splitlines():
            if line.startswith("Version:"):
                return line.split(":", 1)[1].strip()
    return None


def run_suite(
    project_copy: Path,
    project: str,
    package: str,
    tests: str,
    targets: Dict[str, Dict[str, Any]],
    output_name: str,
    python_executable: str,
    extra_args: List[str] | None = None,
    timeout: int = 900,
) -> Dict[str, Any]:
    out_path = OUT_ROOT / f"{output_name}.json"
    log_path = OUT_ROOT / f"{output_name}.log"
    if out_path.exists():
        out_path.unlink()

    target_entries: List[str] = []
    for label, spec in targets.items():
        target_entries.append(
            f"{label}|{spec['line']}|{(project_copy / spec['file']).resolve()}"
        )

    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(PLUGIN_DIR), str((project_copy / "src").resolve())]
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env["REALBENCH_TRACE_TARGETS"] = ";".join(target_entries)
    env["REALBENCH_TRACE_OUT"] = str(out_path.resolve())
    env.pop("PYTEST_ADDOPTS", None)

    command = [
        python_executable,
        "-m",
        "pytest",
        tests,
        "-q",
        "--disable-warnings",
        *(extra_args or []),
        "-p",
        "pytest_trace_plugin",
    ]
    started = datetime.now(timezone.utc)
    try:
        completed = subprocess.run(
            command,
            cwd=project_copy,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        timed_out = False
        stdout, stderr, returncode = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        returncode = None

    log_path.write_text(
        "$ "
        + " ".join(command)
        + "\n\n--- stdout ---\n"
        + stdout
        + "\n--- stderr ---\n"
        + stderr,
        encoding="utf-8",
    )
    trace = json.loads(out_path.read_text(encoding="utf-8")) if out_path.exists() else None
    return {
        "project": project,
        "package": package,
        "work_dir": str(project_copy),
        "tests": tests,
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "started_utc": started.isoformat(),
        "duration_seconds": (datetime.now(timezone.utc) - started).total_seconds(),
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
        "trace_json": str(out_path),
        "trace": trace,
        "version": package_version(project_copy, package),
    }


def main() -> int:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    summary: Dict[str, Any] = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "python": sys.version,
        "executable": sys.executable,
        "pytest": subprocess.run(
            [sys.executable, "-m", "pytest", "--version"],
            capture_output=True,
            text=True,
        ).stdout.strip(),
        "projects": {},
    }

    for project, config in PROJECTS.items():
        source = config["source_fetch"]
        if not source.exists():
            raise SystemExit(f"missing source tree: {source}")
        plus = WORK_ROOT / f"{project}_plus"
        copy_project(source, plus)
        plus_hash = sha256(plus / config["targets"][next(iter(config["targets"]))]["file"])
        python_executable = str(config.get("python", sys.executable))
        print(f"[{project}] P+ suite via {python_executable}", flush=True)
        plus_run = run_suite(
            plus,
            project,
            config["package"],
            config["tests"],
            config["targets"],
            f"{project}_plus",
            python_executable,
            config.get("extra_args"),
        )

        project_record: Dict[str, Any] = {
            "source_fetch": str(source),
            "version": plus_run["version"],
            "python": python_executable,
            "plus": plus_run,
            "plus_target_file_sha256": plus_hash,
            "targets": {},
        }

        for label, spec in config["targets"].items():
            minus = WORK_ROOT / f"{project}_minus_{label}"
            copy_project(plus, minus)
            patch = delete_line(minus, spec)
            print(f"[{project}] P- {label} suite", flush=True)
            minus_run = run_suite(
                minus,
                project,
                config["package"],
                config["tests"],
                {label: spec},
                f"{project}_minus_{label}",
                python_executable,
                config.get("extra_args"),
            )
            project_record["targets"][label] = {
                "spec": spec,
                "patch": patch,
                "minus": minus_run,
            }
        summary["projects"][project] = project_record

    (OUT_ROOT / "upstream_runs.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(f"wrote {OUT_ROOT / 'upstream_runs.json'}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
