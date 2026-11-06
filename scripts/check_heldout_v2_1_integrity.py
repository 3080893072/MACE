# -*- coding: utf-8 -*-
"""HELDOUT v2.1 integrity precheck for blind prediction.

Verifies, for all 25 tasks:
  * case JSON bytes == seal sha256.case
  * evidence enumeration bytes == seal sha256.enumeration_json (hash only)
  * reference bytes == seal sha256.reference_json (hash only)
  * the isolated public-only copy is byte-identical to the formal source tree
  * the legacy probe path in each case remaps to an existing v2.1 probe with
    identical bytes

This script is NOT imported by the predictor.  It only computes SHA-256; no
hidden content is printed or persisted.
"""
from __future__ import annotations

import hashlib
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
KIT = Path(__file__).resolve().parents[1]
HELDOUT = KIT / "benchmark_v4_dataset" / "source_derived_v2_1" / "heldout"
LEGACY = KIT / "benchmark_v4_dataset" / "source_derived" / "heldout"
PUB = KIT / "runs" / "heldout_public_only"
OUT = KIT / "results" / "MACE_HELDOUT_v2_1_integrity_precheck.json"


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def main() -> int:
    seal = json.loads((HELDOUT / "seal" / "heldout_v2_1_seal.json")
                      .read_text("utf-8"))
    entries = {e["case_id"]: e for e in seal["entries"]}
    pub_manifest = json.loads((PUB / "public_manifest.json").read_text("utf-8"))
    copied = {f["path"]: f["sha256"] for f in pub_manifest["files"]}

    results, problems = {}, []
    for cid in sorted(entries):
        e = entries[cid]
        row = {}
        row["case_sha_matches_seal"] = sha(
            HELDOUT / "cases" / f"{cid}.json") == e["sha256"]["case"]
        row["enumeration_sha_matches_seal"] = sha(
            HELDOUT / "evidence" / cid / "enumeration.json"
        ) == e["sha256"]["enumeration_json"]
        ref = HELDOUT / "tasks" / cid / "reference.json"
        row["reference_sha_matches_seal"] = (
            ref.exists()
            and sha(ref) == e["sha256"]["reference_json"])

        # public copy integrity vs formal source
        pairs = [(f"cases/{cid}.json", HELDOUT / "cases" / f"{cid}.json"),
                 (f"probes/{cid}.py", HELDOUT / "probes" / f"{cid}.py")]
        ev = HELDOUT / "evidence" / cid
        for p in sorted(ev.rglob("*")):
            if not p.is_file():
                continue
            rel = p.relative_to(HELDOUT).as_posix()
            if rel.split("/")[-1].startswith("enumeration"):
                continue
            if rel.endswith("reference.json"):
                continue
            pairs.append((rel, p))
        row["public_copy_files"] = len(pairs)
        row["public_copy_identical"] = all(
            copied.get(rel) == sha(src) for rel, src in pairs)

        # source integrity: evidence/original == discovery upstream file
        spec = json.loads((HELDOUT / "cases" / f"{cid}.json").read_text("utf-8"))
        rel = spec["base"]["file"]
        sys.path.insert(0, str(KIT / "benchmark_v4_dataset" / "tools"))
        from sd_algorithm_pilot import stage0_row  # local import
        root_rel = stage0_row(spec["base"]["slug"])["root"]
        disc = (KIT / "benchmark_v4_dataset" / "discovery" / root_rel / rel)
        original = HELDOUT / "evidence" / cid / "original" / Path(rel).name
        row["original_sha_matches_discovery"] = (
            disc.exists() and original.exists() and sha(disc) == sha(original))

        # patch integrity: patch.diff applied to original == patched
        ok_patch = False
        with tempfile.TemporaryDirectory(prefix="mace_patch_") as td:
            tmp = Path(td)
            target = tmp / rel
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(original, target)
            proc = subprocess.run(
                ["patch", "-p1", "-s", "-i",
                 str(HELDOUT / "evidence" / cid / "patch.diff"), "-d", str(tmp)],
                capture_output=True, text=True)
            patched = HELDOUT / "evidence" / cid / "patched" / Path(rel).name
            ok_patch = (proc.returncode == 0 and patched.exists()
                        and sha(target) == sha(patched))
            row["patch_apply_stdout"] = proc.stdout[-300:]
            row["patch_apply_stderr"] = proc.stderr[-300:]
        row["patched_equals_original_plus_patch"] = ok_patch

        # probe remap
        declared = spec["probe"].replace("\\", "/")
        legacy_probe = KIT / declared
        v21_probe = HELDOUT / "probes" / f"{cid}.py"
        row["probe_remap"] = {
            "declared": declared,
            "resolved": str(v21_probe),
            "basename_match": Path(declared).name == v21_probe.name,
            "v21_exists": v21_probe.exists(),
            "legacy_exists": legacy_probe.exists(),
            "legacy_sha256": sha(legacy_probe) if legacy_probe.exists() else None,
            "v21_sha256": sha(v21_probe) if v21_probe.exists() else None,
        }
        row["probe_remap"]["bytes_identical"] = (
            row["probe_remap"]["legacy_sha256"] is not None
            and row["probe_remap"]["legacy_sha256"] == row["probe_remap"]["v21_sha256"])
        a = legacy_probe.read_bytes().replace(b"\r\n", b"\n") if legacy_probe.exists() else b""
        b = v21_probe.read_bytes().replace(b"\r\n", b"\n") if v21_probe.exists() else b"\0"
        row["probe_remap"]["content_identical_after_newline_normalization"] = (a == b)

        ok = (row["case_sha_matches_seal"]
              and row["enumeration_sha_matches_seal"]
              and row["reference_sha_matches_seal"]
              and row["public_copy_identical"]
              and row["original_sha_matches_discovery"]
              and row["patched_equals_original_plus_patch"]
              and row["probe_remap"]["basename_match"]
              and row["probe_remap"]["v21_exists"])
        row["ok"] = ok
        if not ok:
            problems.append(cid)
        results[cid] = row

    report = {
        "schema": "mace-heldout-v2.1-integrity-precheck/1",
        "heldout_root": str(HELDOUT),
        "task_count": len(results),
        "all_ok": not problems,
        "problems": problems,
        "checks": {
            "case_sha_all": all(r["case_sha_matches_seal"] for r in results.values()),
            "enumeration_sha_all": all(r["enumeration_sha_matches_seal"]
                                       for r in results.values()),
            "reference_sha_all": all(r["reference_sha_matches_seal"]
                                     for r in results.values()),
            "public_copy_all": all(r["public_copy_identical"]
                                   for r in results.values()),
            "original_sha_all": all(r["original_sha_matches_discovery"]
                                    for r in results.values()),
            "patch_apply_all": all(r["patched_equals_original_plus_patch"]
                                   for r in results.values()),
            "probe_remap_all": all(r["probe_remap"]["v21_exists"]
                                   and r["probe_remap"]["basename_match"]
                                   for r in results.values()),
            "probe_bytes_identical_all": all(r["probe_remap"]["bytes_identical"]
                                             for r in results.values()),
            "probe_content_identical_all": all(
                r["probe_remap"]["content_identical_after_newline_normalization"]
                for r in results.values()),
        },
        "note": ("Hidden files were opened for SHA-256 only; no content is "
                 "printed, stored, or exposed to the predictor."),
        "tasks": results,
    }
    OUT.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps(report["checks"], indent=1))
    print("problems:", problems)
    print("wrote", OUT)
    return 0 if report["all_ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
