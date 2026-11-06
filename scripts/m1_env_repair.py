"""Repair the pinned M1 projects' *test environments* without touching source.

The frozen screening protocol (``runs/v3_m1_screening/protocol.json``) pins ten
projects by sdist and hash.  The first stage-2 survey ran every suite with the
host interpreter and failed on missing test dependencies.  This script creates
one isolated virtual environment per project, installs the project's declared
test dependencies (and runtime dependencies) into it, and re-runs collection.

Rules enforced here:

* the extracted project trees are data: their files are hashed before and
  after, and no file inside them is written by this script;
* the dependency list is recorded per project before installation; the exact
  resolved versions come from ``pip freeze``;
* no project, candidate or hash order is changed; a project whose sdist does
  not ship its tests (rich) stays uncollectable and is reported as such.

Usage::

    python -m scripts.m1_env_repair
    python -m scripts.m1_env_repair --projects requests more-itertools
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

KIT = Path(__file__).resolve().parents[1]
OUT = KIT / "runs" / "v3_m1_screening"
PROJECTS = OUT / "projects"
VENVS = OUT / "venvs"
REPORT = OUT / "stage2_repair.json"

# Frozen dependency specification.  Every entry is a *test/runtime* package
# named by the pinned project's own pyproject/tox metadata; nothing here
# changes project source or test selection.
DEPS: Dict[str, List[str]] = {
    "urllib3": [
        "pytest>=8.3.4", "trustme>=1.2.1", "trio>=0.27.0",
        "anyio[trio]>=4.8.0", "quart-trio>=0.12.0", "httpx>=0.28.1",
        "pytest-socket>=0.7.0", "pytest-timeout>=2.3.1", "pytest-cov",
        "pysocks>=1.7.1",
    ],
    "requests": [
        "pytest>=7", "pytest-httpbin==2.1.0", "pytest-cov",
        "pytest-mock", "pytest-xdist", "trustme",
        "urllib3", "certifi", "charset_normalizer",
    ],
    "starlette": [
        "pytest>=9.1.1", "httpx2[zstd]>=2.0.0", "trio>=0.34.0",
        "anyio", "coverage>=7.8.2", "jinja2", "python-multipart",
        "pytest-cov", "itsdangerous", "httpx>=0.28.1", "opentelemetry-api",
        "opentelemetry-sdk",
    ],
    "httpx": [
        "pytest", "trio", "anyio", "certifi", "httpcore", "idna",
        "trustme", "uvicorn", "chardet", "pytest-cov",
        "zstandard", "brotli",
    ],
    "attrs": [
        "pytest", "hypothesis", "pytest-xdist[psutil]", "cloudpickle", "pytest-cov",
        "pytest-mypy-plugins",
    ],
    "sqlalchemy": [
        "pytest>=7,<10", "pytest-xdist", "greenlet", "typing-extensions", "pytest-cov",
    ],
    "python-dateutil": [
        "pytest", "hypothesis", "pytest-cov", "six", "attrs",
        "freezegun", "tzdata",
    ],
    "packaging": [
        "pytest", "hypothesis", "coverage[toml]", "pretend", "tomli-w", "pytest-cov",
    ],
    "more-itertools": ["pytest", "pytest-cov"],
    # rich's sdist contains no test directory; no environment can fix that.
    "rich": [],
}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def tree_hash(root: Path) -> str:
    digest = hashlib.sha256()
    for path in sorted(root.rglob("*")):
        if path.is_file():
            digest.update(path.relative_to(root).as_posix().encode())
            digest.update(b"\0")
            digest.update(sha256_file(path).encode())
            digest.update(b"\0")
    return digest.hexdigest()


def src_root(root: Path) -> Path:
    for name in ("src", "lib"):
        if (root / name).is_dir():
            return root / name
    return root


def venv_python(project: str) -> Path:
    return VENVS / project / "Scripts" / "python.exe"


def run(command: List[str], cwd: Path, env: Dict[str, str],
        timeout: int = 1800) -> Dict[str, Any]:
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command, cwd=str(cwd), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout)
        return {
            "command": command,
            "returncode": completed.returncode,
            "wall_seconds": round(time.perf_counter() - started, 2),
            "stdout_tail": completed.stdout.strip().splitlines()[-20:],
            "stderr_tail": completed.stderr.strip().splitlines()[-20:],
        }
    except subprocess.TimeoutExpired:
        return {"command": command, "returncode": None,
                "timed_out": True,
                "wall_seconds": round(time.perf_counter() - started, 2)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects", nargs="*", default=list(DEPS))
    args = parser.parse_args(argv)
    VENVS.mkdir(parents=True, exist_ok=True)
    releases = json.loads((OUT / "releases.json").read_text(encoding="utf-8"))
    old = (json.loads(REPORT.read_text(encoding="utf-8"))
           if REPORT.exists() else {"projects": {}})
    report: Dict[str, Any] = {
        "stage": "stage2_environment_repair",
        "tool": "uv",
        "index_url": "https://pypi.tuna.tsinghua.edu.cn/simple",
        "rules": [
            "Project trees are hashed before and after; no source file is "
            "written.",
            "Dependency lists are derived from each project's own test "
            "metadata and recorded before installation.",
            "The frozen project pool, versions, candidates and hash order are "
            "unchanged.",
        ],
        "projects": dict(old.get("projects", {})),
    }
    for project in args.projects:
        release = releases[project]
        root = PROJECTS / f"{project}-{release['version']}"
        record: Dict[str, Any] = {
            "version": release["version"],
            "source_sha256": release["sha256"],
            "deps_requested": DEPS.get(project, []),
        }
        if not root.exists():
            record["status"] = "SOURCE_MISSING"
            report["projects"][project] = record
            continue
        if project == "rich":
            record["status"] = "TESTS_NOT_IN_SDIST"
            record["reason"] = (
                "The pinned rich-15.0.0 sdist ships only the rich/ package; "
                "pyproject testpaths=['tests'] points at a directory that "
                "does not exist in the sdist.  No environment change can "
                "supply the project's original tests, and fetching a git "
                "tree would change the pinned artifact.")
            report["projects"][project] = record
            continue
        before = tree_hash(root)
        py = venv_python(project)
        if not py.exists():
            record["venv"] = run(
                ["uv", "venv", "--python", "3.11", str(VENVS / project)],
                KIT, os.environ.copy())
        install = run(
            ["uv", "pip", "install", "--python", str(py),
             "--index-url", report["index_url"], *DEPS.get(project, [])],
            KIT, os.environ.copy())
        record["install"] = install
        freeze = run(["uv", "pip", "freeze", "--python", str(py)], KIT,
                     os.environ.copy())
        record["freeze"] = freeze.get("stdout_tail", [])
        env = os.environ.copy()
        env["PYTHONPATH"] = str(src_root(root))
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONHASHSEED"] = "0"
        env.pop("PYTEST_ADDOPTS", None)
        tests = next((name for name in ("tests", "test")
                      if (root / name).is_dir()), None)
        args_tests = [tests] if tests else []
        collect = run([str(py), "-m", "pytest", *args_tests,
                       "--collect-only", "-q"],
                      root, env, timeout=300)
        record["collect"] = collect
        record["collected"] = collect.get("returncode") == 0
        after = tree_hash(root)
        record["tree_sha256_before"] = before
        record["tree_sha256_after"] = after
        record["tree_unchanged"] = before == after
        record["status"] = ("COLLECTED" if record["collected"]
                            else "COLLECT_FAILED")
        report["projects"][project] = record
        print(f"[repair] {project}: {record['status']} "
              f"(install rc={install.get('returncode')}, "
              f"collect rc={collect.get('returncode')})", flush=True)
    report["collectable"] = sorted(
        name for name, row in report["projects"].items()
        if row.get("status") == "COLLECTED")
    report["failed"] = sorted(
        name for name, row in report["projects"].items()
        if row.get("status") not in ("COLLECTED",))
    REPORT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                      encoding="utf-8")
    print(json.dumps({"collectable": report["collectable"],
                      "failed": report["failed"]}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
