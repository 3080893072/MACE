#!/usr/bin/env python
"""Build a public-release tree from this repository.

The private working repository contains HELDOUT reference answers, frozen
predictions, historical evidence logs and legacy generations.  A public
artifact should not ship all of that by default.  This script copies the
repository through an explicit filter and refuses to finish if it finds what
looks like a live credential.

Usage::

    python reproduction/export_public.py --dest /tmp/mace_public --dry-run
    python reproduction/export_public.py --dest /tmp/mace_public
    python reproduction/export_public.py --dest /tmp/mace_public --keep-heldout

The default policy excludes:

- the whole HELDOUT split (tasks, references, evidence, seal) and every
  HELDOUT-derived score, prediction and comparison table;
- **upstream source copies**: the `original/` and `patched/` directories under
  any `evidence/` tree.  Those bytes are third-party code whose redistribution
  carries per-project notice obligations (docutils is compound and includes a
  GPL-3.0 component).  The task definitions, patches and enumeration records
  remain, so the sources can be rebuilt with `fetch_sdists.py` plus the patch;
- downloaded upstream sources and sdists;
- legacy evidence trees (hundreds of MB; one of them historically contained a
  credential in a run log);
- caches, virtual environments and editor state.

Legacy code packages are kept because the test suite imports them. In the
exported copy, absolute Windows home/repository paths in historical logs and
notes are rewritten to `<home>` / `<local-path>` so the artifact does not carry
the author's account name.

`--with-evidence` re-includes the upstream source copies.  Only use it when the
per-project LICENSE/NOTICE obligations in THIRD_PARTY_LICENSES.md are met.

It does not modify this repository.
"""
from __future__ import annotations

import argparse
import re
import shutil
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]

# Directory names excluded anywhere in the tree.
EXCLUDE_DIRS = {
    ".git", "__pycache__", ".pytest_cache", ".hypothesis", ".mypy_cache",
    ".ruff_cache", ".venv", "venv", "build", "dist", ".vscode", ".idea",
}
# Repository-relative prefixes excluded by default.
EXCLUDE_PREFIXES = [
    "runs/v3_m1_screening",
    "runs/heldout_v2_1_blind",
    "benchmark_v4_dataset/discovery/sources",
    "benchmark_v4_dataset/discovery/sdists",
    "benchmark_v4_dataset/discovery/stage1",
    "benchmark_v4_dataset/discovery/stage2_3",
    # Legacy evidence trees: hundreds of MB and the only place a historical
    # log ever contained a credential.  Not needed by any test.
    "benchmark_real_v3/evidence",
    "benchmark_real_v4/evidence",
]
HELDOUT_PREFIXES = [
    # The whole split: tasks, references, evidence, probes, seal.
    "benchmark_v4_dataset/source_derived_v2_1/heldout",
    "benchmark_v4_dataset/split/seal.json",
    "results/MACE_direct_GLM_v2_1_heldout_predictions.json",
    "results/heldout",
]
# Filename prefixes (not directory prefixes) for HELDOUT-derived scores and
# predictions.  Per-input rows also carry the hidden input roles, so they are
# released only with --keep-heldout.
HELDOUT_FILE_PREFIXES = [
    "results/MACE_HELDOUT_v2_1_",
    "results/MACE_direct_GLM_v2_1_HELDOUT",
    "results/MACE_v2_1_DEV_vs_HELDOUT",
]
# Third-party source copies live in these two subdirectory names under any
# evidence tree.  Excluded from the public package by default (see docstring).
EVIDENCE_SOURCE_DIRS = {"/original/", "/patched/"}
LEGACY_BULK = ["benchmark_real_v3/candidates"]
# The provider variable name is assembled from two literals so that this
# scanner does not itself look like a leaked credential to other scanners.
SECRET_PATTERN = re.compile(r"(sk-[A-Za-z0-9]{16,}|ANTHROPIC_AUTH" r"_TOKEN\s*=|api[_-]?key\s*[:=]\s*['\"][A-Za-z0-9]{16,})")
# Upstream test-vector private keys (e.g. the ecdsa sdist).  Not credentials,
# but shipping PEM key blocks makes any secret scanner flag the artifact, so
# files containing them are withheld from the public package.
KEY_MATERIAL_PATTERN = re.compile(
    rb"-----BEGIN [A-Z ]*PRIVATE KEY-----")
MAX_TEXT_BYTES = 32_000_000
TEXT_SUFFIXES = {".py", ".md", ".json", ".jsonl", ".csv", ".txt", ".cff",
                 ".toml", ".yml", ".yaml", ".cfg", ".ini", ".sh", ".log", ""}
# Byte-level substitutions applied to the exported copy only; the source tree
# keeps its historical strings.  They remove the author's local account name
# and repository location from logs and notes written during development.
# {1,2} after each colon/separator because Windows paths inside JSON are
# stored with doubled backslashes (<home>
REDACTIONS = [
    (re.compile(rb"[A-Za-z]:[\\/]{1,2}Users[\\/]{1,2}[^\\/\s\"',]+"), b"<home>"),
    (re.compile(rb"[A-Za-z]:[\\/]{1,2}(?:4_____|3_____|1_P_RS|0_Semantic"
                rb"|tmp[\\/]{1,2}realbench)"
                rb"(?:[\\/]{1,2}[^\\/\s\"'`,]+)*"), b"<local-path>"),
    # pytest embeds the account name in its temporary directory prefix.
    (re.compile(rb"pytest-of-<user>\\/\s\"',]+"), b"pytest-of-<user>"),
]


def excluded(rel: str, keep_heldout: bool, keep_evidence: bool) -> bool:
    if any(rel == p or rel.startswith(p + "/") for p in EXCLUDE_PREFIXES):
        return True
    if any(rel.startswith(p + "/") for p in LEGACY_BULK):
        return True
    if not keep_evidence and "/evidence/" in rel:
        if any(marker in rel for marker in EVIDENCE_SOURCE_DIRS):
            return True
    if not keep_heldout:
        if any(rel == p or rel.startswith(p + "/") for p in HELDOUT_PREFIXES):
            return True
        if any(rel.startswith(p) for p in HELDOUT_FILE_PREFIXES):
            return True
        # Any directory whose name starts with "heldout", in any benchmark
        # generation or run tree (source_derived/heldout,
        # runs/heldout_public_only, runs/direct_*/heldout, ...).
        if any(part.lower().startswith("heldout") for part in rel.split("/")):
            return True
    return False


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--dest", type=Path, required=True)
    ap.add_argument("--keep-heldout", action="store_true",
                    help="include HELDOUT answers and predictions")
    ap.add_argument("--with-evidence", action="store_true",
                    help="include upstream original/patched file copies "
                         "(requires per-project NOTICE compliance)")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()

    dest = args.dest.resolve()
    if dest == KIT or KIT in dest.parents:
        print("refusing to export into the repository itself", file=sys.stderr)
        return 2

    copied = 0
    skipped = 0
    redacted = 0
    findings: list[str] = []
    withheld: list[str] = []
    for src in sorted(KIT.rglob("*")):
        rel = src.relative_to(KIT).as_posix()
        if any(part in EXCLUDE_DIRS for part in src.parts):
            continue
        if src.is_dir():
            continue
        if excluded(rel, args.keep_heldout, args.with_evidence):
            skipped += 1
            continue
        payload = None
        if src.suffix.lower() in TEXT_SUFFIXES and src.stat().st_size < MAX_TEXT_BYTES:
            try:
                data = src.read_bytes()
            except OSError:
                data = b""
            if KEY_MATERIAL_PATTERN.search(data):
                withheld.append(rel)
                skipped += 1
                continue
            if SECRET_PATTERN.search(data.decode("utf-8", errors="ignore")):
                findings.append(rel)
            for pattern, replacement in REDACTIONS:
                data, n = pattern.subn(replacement, data)
                if n:
                    redacted += 1
            payload = data
        copied += 1
        if args.dry_run:
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        if payload is None:
            shutil.copy2(src, target)
        else:
            target.write_bytes(payload)

    print(f"{'would copy' if args.dry_run else 'copied'}: {copied} files")
    print(f"excluded: {skipped} files")
    print(f"files with local path/account strings rewritten: {redacted}")
    if withheld:
        print(f"files withheld for upstream key material: {len(withheld)}")
        for rel in withheld[:10]:
            print("   -", rel)
    print("upstream evidence source copies: "
          + ("INCLUDED (--with-evidence)" if args.with_evidence else "excluded"))
    if args.keep_heldout:
        print("HELDOUT answers and predictions are INCLUDED (--keep-heldout)")
    else:
        print("HELDOUT answers and predictions are excluded")
    if findings:
        print("\nSECRET-LIKE STRINGS FOUND:")
        for rel in findings:
            print(" -", rel)
        print("Refusing to declare the export clean.")
        return 1
    print("\nNo secret-like strings found in shipped text files.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
