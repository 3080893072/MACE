"""Freeze the pre-registered M1 screening pool before seeing any candidate.

This implements steps 1-2 of the selection-independence protocol in
``docs/MACE_next_stage_research_readiness.md`` section 3.5:

* the project pool and versions are pinned from PyPI and hashed;
* the seed, budgets and selection rule are written before any candidate is
  inspected;
* every function/method in the pinned sources is enumerated, deduplicated and
  hash-ordered by the pre-registered seed; the review budget is enforced here,
  not adjusted later.

Nothing in this script runs C, A, B or any graph search, and no test outcome
is observed.  The output is a frozen numerator/denominator for the later
stages, not an M1 verdict.

Usage::

    python -m scripts.m1_protocol_freeze
    python -m scripts.m1_protocol_freeze --fetch-only
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import ssl
import subprocess
import sys
import tarfile
import time
import urllib.request
import zipfile
from pathlib import Path
from typing import Any, Dict, List

import certifi

KIT = Path(__file__).resolve().parents[1]
OUT = KIT / "runs" / "v3_m1_screening"
DIST = OUT / "sdists"
SRC = OUT / "projects"

POOL = [
    ("urllib3", "urllib3"),
    ("requests", "requests"),
    ("starlette", "starlette"),
    ("httpx", "httpx"),
    ("attrs", "attr"),
    ("sqlalchemy", "sqlalchemy"),
    ("python-dateutil", "dateutil"),
    ("rich", "rich"),
    ("packaging", "packaging"),
    ("more-itertools", "more_itertools"),
]
SEED = "mace-m1-2026-11-03"
BUDGETS = {
    "static_reviewed": 2500,
    "targeted_minus_runs": 800,
    "full_suite_minus_runs": 150,
    "target_qualified_tasks": 15,
    "per_mechanism": 3,
    "surviving_candidates": 30,
}
SELECTION_RULE = (
    "Within each mechanism stratum, sort qualified candidate IDs by "
    "sha256(f'{seed}:{candidate_id}') ascending and take the first 3.  "
    "Never substitute across strata; report a gap instead.")
SKIP_DIR_PARTS = {"test", "tests", "testing", "doc", "docs", "examples",
                  "example", "benchmarks", "benchmark", "__pycache__",
                  "build", "dist"}


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def http_json(url: str, retries: int = 3) -> Dict[str, Any]:
    ctx = ssl.create_default_context(cafile=certifi.where())
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "mace-screening/1.0"})
            with urllib.request.urlopen(request, timeout=60,
                                        context=ctx) as response:
                return json.load(response)
        except Exception as exc:  # noqa: BLE001 - retry then report
            last = exc
            time.sleep(2 + attempt * 3)
    raise RuntimeError(f"cannot fetch {url}: {last}")


def download(url: str, dest: Path, retries: int = 3) -> str:
    if dest.exists():
        return sha256_file(dest)
    ctx = ssl.create_default_context(cafile=certifi.where())
    last: Exception | None = None
    for attempt in range(retries):
        try:
            request = urllib.request.Request(
                url, headers={"User-Agent": "mace-screening/1.0"})
            with urllib.request.urlopen(request, timeout=180,
                                        context=ctx) as response:
                data = response.read()
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return sha256_bytes(data)
        except Exception as exc:  # noqa: BLE001
            last = exc
            time.sleep(2 + attempt * 5)
    raise RuntimeError(f"cannot download {url}: {last}")


def latest_stable(project: str) -> str:
    """Latest non-prerelease version, straight from the package index.

    ``pip index versions`` is used instead of the all-releases JSON endpoint:
    for projects with a long release history that endpoint is tens of MB and
    regularly stalls, while this query returns only the effective version
    list.  pip excludes pre-releases unless asked.
    """
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "index", "versions", project],
        capture_output=True, text=True, timeout=120)
    for line in completed.stdout.splitlines():
        if line.startswith(project + " ("):
            return line.split("(", 1)[1].rstrip(")")
    raise RuntimeError(f"cannot resolve version for {project}: "
                       f"{completed.stderr[-500:]}")


def pick_release(project: str) -> Dict[str, Any]:
    """Metadata for the latest stable sdist release at freeze time."""
    version = latest_stable(project)
    meta = http_json(f"https://pypi.org/pypi/{project}/{version}/json")
    sdists = [item for item in meta["urls"]
              if item["packagetype"] == "sdist" and not item.get("yanked")]
    if not sdists:
        raise RuntimeError(f"no sdist for {project} {version}")
    item = sdists[0]
    return {"version": version,
            "uploaded": item["upload_time_iso_8601"],
            "url": item["url"], "sha256": item["digests"]["sha256"],
            "filename": item["filename"], "size": item["size"]}


def extract(archive: Path, project: str, version: str) -> Path:
    target = SRC / f"{project}-{version}"
    if target.exists() and any(target.iterdir()):
        return target
    staging = SRC / f"_extract_{project}-{version}"
    if staging.exists():
        import shutil
        shutil.rmtree(staging)
    staging.mkdir(parents=True)
    if archive.suffix == ".zip":
        with zipfile.ZipFile(archive) as bundle:
            bundle.extractall(staging)
    else:
        with tarfile.open(archive) as bundle:
            bundle.extractall(staging)
    roots = [item for item in staging.iterdir() if item.is_dir()]
    if len(roots) != 1:
        raise RuntimeError(f"unexpected sdist layout for {project}: {roots}")
    roots[0].rename(target)
    staging.rmdir()
    return target


def package_root(extracted: Path, package: str) -> Path:
    for base in (extracted, extracted / "src", extracted / "lib"):
        direct = base / package
        if direct.is_dir():
            return direct
        parent = base / f"{package}-{package}"
        if parent.is_dir():
            return parent
        for pattern in (f"{package}-*", f"{package}_*"):
            for item in base.glob(pattern):
                if item.is_dir() and (item / "__init__.py").exists():
                    return item
    raise RuntimeError(f"cannot locate package {package} in {extracted}")


def enumerate_candidates(project: str, root: Path) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for path in sorted(root.rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        if SKIP_DIR_PARTS & set(Path(relative).parts):
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        for node in ast.walk(tree):
            if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            qualname = node.name
            candidate_id = f"{project}:{relative}:{node.lineno}:{qualname}"
            if candidate_id in seen:
                continue
            seen.add(candidate_id)
            out.append({
                "candidate_id": candidate_id,
                "project": project,
                "file": relative,
                "function": qualname,
                "line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
                "async": isinstance(node, ast.AsyncFunctionDef),
            })
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--fetch-only", action="store_true")
    args = parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "protocol.json").write_text(json.dumps({
        "schema": "mace-m1-screening-protocol-1.0",
        "frozen_at_local_date": "2026-11-03",
        "seed": SEED,
        "project_pool": [name for name, _ in POOL],
        "excluded_development_projects": ["jinja2", "werkzeug"],
        "budgets": BUDGETS,
        "selection_rule": SELECTION_RULE,
        "stages": [
            "static_enumeration",
            "plus_test_coverage",
            "targeted_minus",
            "full_suite_minus",
            "mechanism_acceptance",
            "quota_selection",
        ],
        "independence": [
            "No C / A / B / graph run during screening.",
            "Classification uses the M1 definition only, never an algorithm "
            "score.",
            "Budget order is hash(seed, candidate_id); it is fixed before any "
            "test outcome exists.",
            "A shortfall is reported as NO_QUALIFIED_TASK; no synthetic "
            "case and no cross-stratum substitution is allowed.",
        ],
        "hidden_data_in_scope": False,
        "model_calls": 0,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    releases = {}
    for project, package in POOL:
        release = pick_release(project)
        archive = DIST / release["filename"]
        digest = download(release["url"], archive)
        if digest != release["sha256"]:
            raise RuntimeError(f"sha256 mismatch for {archive}")
        releases[project] = {
            "package": package,
            "version": release["version"],
            "uploaded": release["uploaded"],
            "filename": release["filename"],
            "url": release["url"],
            "sha256": digest,
            "size": release["size"],
        }
        print(f"[freeze] {project} {release['version']} {digest[:12]}",
              flush=True)
    (OUT / "releases.json").write_text(
        json.dumps(releases, ensure_ascii=False, indent=2), encoding="utf-8")
    if args.fetch_only:
        return 0

    candidates: List[Dict[str, Any]] = []
    per_project: Dict[str, Any] = {}
    for project, package in POOL:
        extracted = extract(DIST / releases[project]["filename"], project,
                            releases[project]["version"])
        root = package_root(extracted, package)
        rows = enumerate_candidates(project, root)
        candidates.extend(rows)
        per_project[project] = {
            "package_root": str(root.relative_to(OUT)).replace("\\", "/"),
            "functions": len(rows),
            "files": len({row["file"] for row in rows}),
        }
        print(f"[static] {project}: {len(rows)} functions", flush=True)

    for row in candidates:
        row["order"] = sha256_bytes(
            f"{SEED}:{row['candidate_id']}".encode("utf-8"))
    ordered = sorted(candidates, key=lambda row: (row["order"],
                                                  row["candidate_id"]))
    selected = ordered[:BUDGETS["static_reviewed"]]
    (OUT / "static_candidates.json").write_text(json.dumps({
        "seed": SEED,
        "total_enumerated": len(candidates),
        "review_budget": BUDGETS["static_reviewed"],
        "selected": len(selected),
        "per_project": per_project,
        "candidates": candidates,
        "review_order": [row["candidate_id"] for row in selected],
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    ledger = {
        "stage": "static_enumeration_complete",
        "per_project": per_project,
        "total_enumerated": len(candidates),
        "review_budget": BUDGETS["static_reviewed"],
        "reviewed": len(selected),
        "truncated": len(candidates) - len(selected),
        "next_stage": "plus_test_coverage",
        "note": (
            "Enumerating functions/methods is not an M1 claim.  A candidate "
            "still needs a P+ trace, a P- failure, and a joint masking "
            "witness before it can enter a mechanism stratum."),
    }
    (OUT / "funnel_ledger.json").write_text(
        json.dumps(ledger, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({key: ledger[key] for key in (
        "total_enumerated", "reviewed", "truncated")}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
