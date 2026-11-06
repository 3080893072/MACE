# -*- coding: utf-8 -*-
"""Build the isolated public-only HELDOUT workspace (MACE-Bench v2.1).

Copies ONLY files that are legitimately public for blind prediction:

  cases/<cid>.json
  evidence/<cid>/patched/*
  evidence/<cid>/original/*
  evidence/<cid>/patch.diff
  probes/<cid>.py

Never copied (hidden truth): tasks/, acceptance/, seal/, evidence/<cid>/
enumeration*.json.  The whitelist is explicit; anything not listed is refused.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
SRC = KIT / "benchmark_v4_dataset" / "source_derived_v2_1" / "heldout"
DST = KIT / "runs" / "heldout_public_only"

FORBIDDEN_NAMES = {
    "reference.json", "acceptance.json", "enumeration.json",
    "enumeration_v2_legacy.json",
}


def sha(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def allowed(rel: Path) -> str | None:
    parts = rel.parts
    if len(parts) == 2 and parts[0] == "cases" and rel.suffix == ".json":
        return "case"
    if len(parts) == 4 and parts[0] == "evidence" and parts[2] in (
            "patched", "original"):
        return "evidence_source"
    if len(parts) == 3 and parts[0] == "evidence" and parts[2] == "patch.diff":
        return "patch_diff"
    if len(parts) == 2 and parts[0] == "probes" and rel.suffix == ".py":
        return "probe"
    return None


def main() -> int:
    assert SRC.is_dir()
    if DST.exists():
        shutil.rmtree(DST)
    files, refused = [], []
    for path in sorted(SRC.rglob("*")):
        if path.is_dir():
            continue
        rel = path.relative_to(SRC)
        cls = allowed(rel)
        if cls is None or path.name in FORBIDDEN_NAMES:
            refused.append(rel.as_posix())
            continue
        out = DST / rel
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(path, out)
        files.append({
            "path": rel.as_posix(), "class": cls,
            "bytes": out.stat().st_size, "sha256": sha(out),
        })

    # The seal is read ONLY for public stratification flags and public hashes.
    seal = json.loads((SRC / "seal" / "heldout_v2_1_seal.json")
                      .read_text("utf-8"))
    strat = {}
    for entry in seal["entries"]:
        strat[entry["case_id"]] = {
            "project_disjoint_from_dev": bool(entry["project_disjoint_from_dev"]),
            "template_seen_in_dev": bool(entry["template_seen_in_dev"]),
            "template_class": entry.get("template_class"),
            "mechanism": entry.get("mechanism"),
        }
    (DST / "public_subset_flags.json").write_text(json.dumps({
        "note": ("Public stratification flags only: per-case disjointness "
                 "booleans. No roles, no reference counts, no answers."),
        "tasks": strat,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = {
        "schema": "mace-heldout-public-only/1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "source_root": str(SRC),
        "destination_root": str(DST),
        "whitelist": ["cases/*.json", "evidence/<cid>/patched/*",
                      "evidence/<cid>/original/*", "evidence/<cid>/patch.diff",
                      "probes/*.py"],
        "excluded_by_whitelist": sorted(refused),
        "file_count": len(files),
        "files": files,
        "public_subset_flags": "public_subset_flags.json",
    }
    (DST / "public_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"copied {len(files)} files -> {DST}")
    print(f"refused {len(refused)} non-public entries")
    from collections import Counter
    print(Counter(f["class"] for f in files))
    return 0


if __name__ == "__main__":
    sys.exit(main())
