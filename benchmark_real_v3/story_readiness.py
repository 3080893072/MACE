"""Read-only checks for the first development-pilot baseline run.

Verifies the frozen public/hidden package, the leak report, the scorer
regression suite and the no-model end-to-end demo.  Writes a JSON record next
to the story-validation evidence.  It never edits the release package.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from benchmark_real_v3.config import EVIDENCE, KIT, V3

RELEASE = V3 / "release"
PUBLIC = RELEASE / "PUBLIC"
HIDDEN = RELEASE / "HIDDEN"
OUT = EVIDENCE / "story_validation" / "task4_readiness.json"


def _bundle(path: Path) -> Dict[str, Any]:
    files: Dict[str, str] = {}
    for file in sorted(path.rglob("*")):
        if file.is_file() and file.name not in ("manifest.json", "SHA256SUMS"):
            files[file.relative_to(path).as_posix()] = hashlib.sha256(
                file.read_bytes()).hexdigest()
    digest = hashlib.sha256()
    for rel, sha in sorted(files.items()):
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha.encode("ascii"))
        digest.update(b"\0")
    return {"bundle_sha256": digest.hexdigest(), "files": files}


def _run(command: list[str], timeout: int = 900) -> Dict[str, Any]:
    completed = subprocess.run(
        command, cwd=str(KIT), capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=timeout,
    )
    return {
        "command": command,
        "returncode": completed.returncode,
        "stdout": completed.stdout,
        "stdout_tail": completed.stdout[-4000:],
        "stderr_tail": completed.stderr[-2000:],
    }


def main() -> int:
    manifest = json.loads(
        (RELEASE / "manifest.json").read_text(encoding="utf-8"))
    computed = _bundle(RELEASE)
    leak = json.loads(
        (EVIDENCE / "acceptance" / "leak_report.json").read_text(
            encoding="utf-8"))
    public_files = sorted(
        p.relative_to(PUBLIC).as_posix()
        for p in PUBLIC.rglob("*") if p.is_file())
    hidden_files = sorted(
        p.relative_to(HIDDEN).as_posix()
        for p in HIDDEN.rglob("*") if p.is_file())

    tests = _run([
        sys.executable, "-m", "unittest", "discover",
        "-s", "benchmark_real_v3/scoring/tests", "-v",
    ])
    demo = _run([
        sys.executable, "-m", "benchmark_real_v3.scoring.demo",
    ])
    try:
        demo_payload = json.loads(demo["stdout"])
    except ValueError:
        demo_payload = None
    demo_ok = bool(
        demo_payload and demo_payload.get("all_expectations_met") is True)
    tests_ok = bool(
        tests["returncode"] == 0 and "\nOK" in tests["stderr_tail"]
        or tests["returncode"] == 0 and "\nOK" in tests["stdout_tail"])
    protocol_doc = (KIT / "docs" / "MACE_open_discovery_protocol.md").read_text(
        encoding="utf-8")
    baseline_doc = (KIT / "docs" / "MACE_executability_and_baseline.md").read_text(
        encoding="utf-8")
    full_mace_no_operations = (
        "没有** `relations[].operations`" in protocol_doc
        and "掩盖操作与组合" in baseline_doc
        and "`UNSUPPORTED_INTERFACE`" in baseline_doc)

    payload = {
        "schema": "mace_benchmark_v3_task4_readiness",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "release_version": manifest["release_version"],
        "label": manifest["label"],
        "public_file_count": len(public_files),
        "hidden_file_count": len(hidden_files),
        "public_files": public_files,
        "hidden_files": hidden_files,
        "hidden_outside_public": not any(
            path.startswith("HIDDEN/") for path in public_files),
        "bundle_sha256_manifest": manifest["bundle_sha256"],
        "bundle_sha256_recomputed": computed["bundle_sha256"],
        "bundle_matches_manifest": (
            manifest["bundle_sha256"] == computed["bundle_sha256"]),
        "leak_check_passed": leak["passed"],
        "leak_check_count": len(leak["checks"]),
        "leak_findings": leak["findings"],
        "scoring_tests_ok": tests_ok,
        "scoring_tests_output_tail": (
            tests["stdout_tail"] + tests["stderr_tail"])[-2000:],
        "demo_all_expectations_met": demo_ok,
        "demo_returncode": demo["returncode"],
        "full_mace_no_operations_field_confirmed": full_mace_no_operations,
        "full_mace_status": "UNSUPPORTED_INTERFACE",
        "full_mace_note": (
            "Original Full MACE exposes target_effects/upstream/observers/"
            "mask_guard and parameter-level attribution, but no relation-level "
            "operations field and no per-relation input.  This is an interface "
            "limit, not a semantic error and not 0% correctness."),
        "scoring_interface_blockers": [],
        "public_independent_of_hidden": bool(
            leak["passed"] and not any(
                path.startswith("HIDDEN/") for path in public_files)),
    }
    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "readiness": str(OUT),
        "public_file_count": len(public_files),
        "hidden_file_count": len(hidden_files),
        "bundle_matches_manifest": payload["bundle_matches_manifest"],
        "leak_check_passed": payload["leak_check_passed"],
        "scoring_tests_ok": tests_ok,
        "demo_all_expectations_met": demo_ok,
        "full_mace_status": payload["full_mace_status"],
        "blockers": payload["scoring_interface_blockers"],
    }, ensure_ascii=False, indent=2))
    ok = all([
        payload["bundle_matches_manifest"],
        payload["leak_check_passed"],
        tests_ok,
        demo_ok,
        payload["hidden_outside_public"],
        full_mace_no_operations,
    ])
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
