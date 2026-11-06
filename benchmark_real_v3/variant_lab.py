"""Build executable program variants and run probes against them.

Every variant is an isolated copy of the fixed upstream tree with a small,
explicit set of statement deletions.  A probe is a separate script that
imports only the public project API and prints one JSON observation.

No observation is produced by importing the controller's copy of the project:
the child process gets ``PYTHONPATH`` pointing at the variant's ``src``.
"""
from __future__ import annotations

import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence

from benchmark_real_v3.config import PROJECTS, WORK_ROOT

VARIANT_ROOT = WORK_ROOT / "variants"
PROBES = Path(__file__).resolve().parent / "probes"
IGNORE = None


def _copy(source: Path, destination: Path) -> None:
    import shutil

    from benchmark_real_v3.run_suite import IGNORE

    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(source, destination, ignore=IGNORE)


def _replace_statement(path: Path, line: int, indent: str | None,
                       replacement: str) -> Dict[str, Any]:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    index = line - 1
    original = lines[index]
    if not original.strip():
        raise RuntimeError(f"line {line} in {path} is blank")
    actual_indent = original[: len(original) - len(original.lstrip())]
    if indent is not None and actual_indent != indent:
        raise RuntimeError(
            f"indent mismatch at {path}:{line}: {actual_indent!r} != {indent!r}")
    lines[index] = actual_indent + replacement + "\n"
    path.write_text("".join(lines), encoding="utf-8")
    return {
        "file": str(path),
        "line": line,
        "original_line": original.rstrip("\n"),
        "replacement": lines[index].rstrip("\n"),
    }


def disable_statement(project_root: Path, file: str, line: int,
                      replacement: str = "pass") -> Dict[str, Any]:
    """Disable one simple statement, keeping its indentation and line count."""
    return _replace_statement(project_root / file, line, None, replacement)


def disable_block(project_root: Path, file: str, first: int, last: int) -> Dict[str, Any]:
    """Disable a whole compound statement by replacing its lines with one pass.

    The replacement keeps the opener's indentation, so surrounding blocks stay
    syntactically valid.  Line numbers of later statements are preserved by
    padding with blank lines only when the caller needs it; the default keeps
    the file readable and the operation is recorded explicitly.
    """
    path = project_root / file
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    first_original = lines[first - 1]
    indent = first_original[: len(first_original) - len(first_original.lstrip())]
    detached = "".join(lines[first - 1:last])
    lines[first - 1:last] = [indent + "pass  # intervention: disabled block\n"]
    path.write_text("".join(lines), encoding="utf-8")
    return {
        "file": str(path),
        "first_line": first,
        "last_line": last,
        "original_block": detached,
        "replacement": indent + "pass  # intervention: disabled block",
    }


def build_variant(
    project_id: str,
    name: str,
    *,
    statement_deletions: Sequence[tuple[str, int]] = (),
    block_deletions: Sequence[tuple[str, int, int]] = (),
    replacements: Sequence[tuple[str, int, str]] = (),
) -> Dict[str, Any]:
    cfg = PROJECTS[project_id]
    root = VARIANT_ROOT / project_id / name
    _copy(cfg["root"], root)
    edits: List[Dict[str, Any]] = []
    for file, line in statement_deletions:
        edits.append(disable_statement(root, file, line))
    for file, first, last in block_deletions:
        edits.append(disable_block(root, file, first, last))
    for file, line, text in replacements:
        edits.append(_replace_statement(root / file, line, None, text))
    return {
        "project_id": project_id,
        "name": name,
        "root": str(root),
        "edits": edits,
        "source_dir": cfg["source_dir"],
    }


def _env(variant_root: Path, project_id: str) -> Dict[str, str]:
    cfg = PROJECTS[project_id]
    env = os.environ.copy()
    env["PYTHONPATH"] = str((variant_root / cfg["source_dir"]).resolve())
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def run_probe(project_id: str, variant_root: Path, probe: str,
              payload: Dict[str, Any], timeout: int = 180) -> Dict[str, Any]:
    cfg = PROJECTS[project_id]
    command = [cfg["python"], str(PROBES / probe)]
    completed = subprocess.run(
        command,
        input=json.dumps(payload),
        cwd=str(variant_root),
        env=_env(variant_root, project_id),
        capture_output=True,
        text=True,
        encoding="utf-8",
        timeout=timeout,
    )
    observation: Any
    try:
        observation = json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        observation = {
            "probe_crash": True,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }
    return {
        "probe": probe,
        "payload": payload,
        "command": command,
        "returncode": completed.returncode,
        "stderr_tail": completed.stderr[-4000:],
        "observation": observation,
    }


def observe(project_id: str, variant: Dict[str, Any], probe: str,
            payload: Dict[str, Any]) -> Dict[str, Any]:
    return run_probe(
        project_id, Path(variant["root"]), probe, payload)
