#!/usr/bin/env python
"""Fetch and verify the upstream sdists that MACE-Bench tasks are built from.

The repository does not redistribute upstream source trees.  It pins every
sdist by URL, size and SHA-256 in
``benchmark_v4_dataset/discovery/manifest/source_registry.json``; this script
downloads exactly those bytes and extracts them where the dataset tools
expect them.

Layout produced::

    benchmark_v4_dataset/discovery/sdists/<filename>.tar.gz
    benchmark_v4_dataset/discovery/sources/<slug>/<top_dir>/...

Usage::

    python reproduction/fetch_sdists.py --verify-only
    python reproduction/fetch_sdists.py              # 23 projects used by v2.1
    python reproduction/fetch_sdists.py --all        # all 70 discovery projects

Set ``MACE_SDIST_CACHE`` to download into a shared cache instead of the
repository, and ``--link`` to symlink/copy from there.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import tarfile
import urllib.request
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
DISC = KIT / "benchmark_v4_dataset" / "discovery"
REGISTRY = DISC / "manifest" / "source_registry.json"
STAGE0 = DISC / "stage0" / "projects.json"
V21 = KIT / "benchmark_v4_dataset" / "source_derived_v2_1"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def needed_projects() -> set[str]:
    names = set()
    for split in (V21, V21 / "heldout"):
        for task_path in (split / "tasks").glob("*/task.json"):
            task = json.loads(task_path.read_text("utf-8"))
            names.add(task["project"])
    return names


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true",
                    help="fetch all 70 discovery projects instead of the 23 used by v2.1")
    ap.add_argument("--project", action="append", default=[],
                    help="fetch a single project by name (repeatable)")
    ap.add_argument("--verify-only", action="store_true")
    ap.add_argument("--cache", type=Path,
                    default=Path(os.environ.get("MACE_SDIST_CACHE", DISC / "sdists")))
    args = ap.parse_args()

    registry = json.loads(REGISTRY.read_text("utf-8"))["projects"]
    stage0 = {row["slug"]: row for row in
              json.loads(STAGE0.read_text("utf-8"))["projects"]}
    want = needed_projects()
    if args.project:
        want |= set(args.project)

    selected = [row for row in registry
                if args.all or row["name"] in want]
    if not selected:
        print("nothing selected", file=sys.stderr)
        return 1

    args.cache.mkdir(parents=True, exist_ok=True)
    failures = 0
    for row in sorted(selected, key=lambda r: r["slug"]):
        target = args.cache / row["filename"]
        if target.exists():
            ok = sha256(target) == row["sha256"]
            state = "cached" if ok else "cached-but-corrupt"
        else:
            state = "missing"
            ok = False
        print(f"[{state:18}] {row['slug']}")
        if not ok and not args.verify_only:
            print(f"  downloading {row['url']}")
            tmp = target.with_suffix(target.suffix + ".part")
            with urllib.request.urlopen(row["url"], timeout=120) as response:
                with tmp.open("wb") as handle:
                    shutil.copyfileobj(response, handle)
            ok = sha256(tmp) == row["sha256"] and tmp.stat().st_size == row["size"]
            if not ok:
                print("  SHA-256/size mismatch; keeping .part for inspection")
                failures += 1
                continue
            tmp.replace(target)
        if not ok:
            failures += 1
            continue
        if args.verify_only:
            continue
        meta = stage0.get(row["slug"])
        if meta is None:
            print("  no stage0 entry; skipping extraction")
            continue
        root = KIT / "benchmark_v4_dataset" / "discovery" / meta["root"]
        if root.exists():
            continue
        dest = (KIT / "benchmark_v4_dataset" / "discovery" / "sources" / row["slug"])
        dest.mkdir(parents=True, exist_ok=True)
        with tarfile.open(target, "r:gz") as tar:
            tar.extractall(dest, filter="data") if sys.version_info >= (3, 12) \
                else tar.extractall(dest)
        print(f"  extracted to {dest.relative_to(KIT)}")

    # Symlink-free portability: when a cache outside the repo is used, copy the
    # pinned archives into the repository location expected by the dataset tools.
    repo_sdists = DISC / "sdists"
    if args.cache.resolve() != repo_sdists.resolve():
        repo_sdists.mkdir(parents=True, exist_ok=True)
        for row in selected:
            src = args.cache / row["filename"]
            dst = repo_sdists / row["filename"]
            if src.exists() and not dst.exists():
                shutil.copy2(src, dst)

    print(f"\n{len(selected) - failures}/{len(selected)} sdists verified")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
