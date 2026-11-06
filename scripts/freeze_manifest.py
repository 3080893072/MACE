"""Freeze manifest for M1-M6.

Records the git state, the platform/runtime, and SHA-256 hashes of every
tracked artifact that can influence an M1-M6 result.  The manifest itself is
not hashed; it is written after the measured state and then committed.

Usage
-----
    python scripts/freeze_manifest.py
"""
from __future__ import annotations

import hashlib
import json
import platform
import subprocess
import sys
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
SCAN_DIRS = ("mace", "scripts", "tests", "experiments", "fixtures",
             "m5", "m6", "results", "docs")
SUFFIXES = {".py", ".json", ".md", ".jsonl", ".txt", ".log", ".sh", ".cfg",
            ".ini", ".tgz", ".csv"}
SKIP_NAMES = {"FREEZE_MANIFEST.md", "freeze_manifest.json"}


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                         text=True, timeout=30)
    return out.stdout.strip()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def version_of(module: str) -> str | None:
    try:
        mod = __import__(module)
        return getattr(mod, "__version__", "present")
    except Exception:
        return None


def collect() -> Dict[str, Any]:
    files: List[Dict[str, Any]] = []
    per_dir = Counter()
    for directory in SCAN_DIRS:
        base = ROOT / directory
        if not base.exists():
            continue
        for path in sorted(base.rglob("*")):
            if not path.is_file() or path.name in SKIP_NAMES:
                continue
            if path.suffix.lower() not in SUFFIXES and path.name != "pytest.ini":
                continue
            files.append({"path": path.relative_to(ROOT).as_posix(),
                          "bytes": path.stat().st_size,
                          "sha256": sha256(path)})
            per_dir[directory] += 1
    return {
        "frozen_through_commit": git("rev-parse", "HEAD"),
        "branch": git("rev-parse", "--abbrev-ref", "HEAD"),
        "tags": [t for t in git("tag", "--list").splitlines() if t],
        "dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
        "runtime": {
            "python": sys.version.split()[0],
            "implementation": platform.python_implementation(),
            "executable": sys.executable,
            "platform": platform.platform(),
            "machine": platform.machine(),
        },
        "packages": {name: version_of(name) for name in
                     ("pytest", "numpy", "scipy", "torch")},
        "model_runs": {
            "model": "qwen2.5-coder:32b (Ollama, stored M5 runs only)",
            "temperature": 0,
            "seeds": [42],
            "note": "M6 and this audit made no model calls.",
        },
        "split_seeds": {"fit_eval": 20261030, "learn_tune": 20261031},
        "counts": dict(per_dir),
        "files": files,
    }


def markdown(data: Dict[str, Any]) -> str:
    lines = ["# M1-M6 freeze manifest", "",
             f"* Frozen through commit: `{data['frozen_through_commit']}`",
             f"* Branch: `{data['branch']}`",
             f"* Tags: {', '.join('`%s`' % t for t in data['tags']) or '-'}",
             f"* Working tree dirty at scan time: **{data['dirty']}**",
             f"* Python: {data['runtime']['implementation']} "
             f"{data['runtime']['python']} ({data['runtime']['platform']})",
             f"* Model: {data['model_runs']['model']}; temperature "
             f"{data['model_runs']['temperature']}; seeds "
             f"{data['model_runs']['seeds']}",
             f"* Split seeds: {data['split_seeds']}", "",
             "## Coverage", "", "| directory | files hashed |", "|---|---|"]
    for name, count in sorted(data["counts"].items()):
        lines.append(f"| `{name}/` | {count} |")
    lines += ["", "## Runtime packages", "", "| package | version |", "|---|---|"]
    for name, version in data["packages"].items():
        lines.append(f"| {name} | {version} |")
    lines += ["", "## Artifacts", "",
              "Every file below is hashed with SHA-256 and reproduced in "
              "`m6/freeze_manifest.json`.", "",
              "| sha256 | bytes | path |", "|---|---|---|"]
    for item in data["files"]:
        lines.append(f"| `{item['sha256'][:16]}…` | {item['bytes']} | "
                     f"`{item['path']}` |")
    lines.append("")
    return "\n".join(lines)


def main() -> int:
    data = collect()
    json_path = ROOT / "m6" / "freeze_manifest.json"
    md_path = ROOT / "docs" / "FREEZE_MANIFEST.md"
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    md_path.write_text(markdown(data), encoding="utf-8")
    print(f"hashed {len(data['files'])} files; dirty={data['dirty']}; "
          f"HEAD={data['frozen_through_commit'][:12]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
