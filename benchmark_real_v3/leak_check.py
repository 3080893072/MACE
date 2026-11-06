"""Check that the public package leaks no hidden reference material.

The checker treats the public ``task.json`` files, the index, the input
contracts, ``submission_format.md`` and ``README.md`` as metadata.  Source
files are *original upstream files*: they are checked byte-for-byte against
the frozen project trees, not scanned for tokens that already exist upstream.

Run after ``release_build``::

    python -m benchmark_real_v3.leak_check
    python -m benchmark_real_v3.leak_check --check-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

from benchmark_real_v3.config import EVIDENCE, PROJECTS, V3

RELEASE = V3 / "release"
PUBLIC = RELEASE / "PUBLIC"
HIDDEN = RELEASE / "HIDDEN"
REPORT = EVIDENCE / "acceptance" / "leak_report.json"

FORBIDDEN_KEYS = {
    "candidate_universe", "witnesses", "reference_relations",
    "reference_claims", "partial_truth", "masked_strict", "msms", "mmbs",
    "exposed", "witness_id", "expected_status", "deletion_method",
    "probe", "universe_notes", "independent_matrix", "acceptance_report",
}
FORBIDDEN_TEXT = {
    "release/HIDDEN", "HIDDEN/", "reference.json", "matrix.json",
    "evidence/", "<local-path>", "acceptance_report", "qualified_tasks",
    "reference_claims", "candidate_universe", "witness_id",
}
LINE_KEYS = {"line", "first_line", "last_line", "end_line"}


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _norm(text: str) -> str:
    return "".join(text.split())


def _metadata_files() -> List[Path]:
    return sorted(
        path for path in PUBLIC.rglob("*")
        if path.is_file()
        and path.suffix.lower() in {".json", ".md"}
        and "source" not in path.relative_to(PUBLIC).parts
    )


def _public_source_files() -> List[Path]:
    return sorted(
        path for path in PUBLIC.rglob("*")
        if path.is_file() and "source" in path.relative_to(PUBLIC).parts
    )


def _walk_json(value: Any, path: str = "$") -> Iterable[tuple[str, Any]]:
    yield path, value
    if isinstance(value, dict):
        for key, child in value.items():
            yield from _walk_json(child, f"{path}.{key}")
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk_json(child, f"{path}[{index}]")


def _hidden_refs() -> Dict[str, Dict[str, Any]]:
    refs = {}
    for path in sorted((HIDDEN / "tasks").glob("*/reference.json")):
        ref = json.loads(path.read_text(encoding="utf-8"))
        refs[ref["task_id"]] = ref
    return refs


def _check(expected_label: str = "DEVELOPMENT/PILOT") -> Dict[str, Any]:
    findings: List[Dict[str, str]] = []
    checks: List[Dict[str, Any]] = []
    refs = _hidden_refs()

    def add(name: str, passed: bool, detail: str = "") -> None:
        checks.append({"check": name, "passed": bool(passed), "detail": detail})
        if not passed:
            findings.append({"check": name, "detail": detail})

    def finding(check: str, file: Path | str, detail: str) -> None:
        findings.append({
            "check": check,
            "file": str(file),
            "detail": detail,
        })

    add("hidden_references_present", len(refs) == 5, f"{len(refs)} tasks")
    add("public_is_a_subset_of_hidden_tasks",
        {path.parent.name for path in (PUBLIC / "tasks").glob("*/task.json")}
        == set(refs),
        "public and hidden task ids differ")

    # 1. File inventory: metadata + exactly the declared target source file.
    expected_meta = {
        "README.md", "input_contracts.json", "submission_format.md",
        "tasks/index.json",
    }
    expected_meta |= {f"tasks/{task_id}/task.json" for task_id in refs}
    actual_meta = {
        path.relative_to(PUBLIC).as_posix() for path in _metadata_files()
    }
    add("public_metadata_inventory", actual_meta == expected_meta,
        f"actual={sorted(actual_meta)}")
    expected_sources = set()
    for task_id, ref in refs.items():
        expected_sources.add(
            f"tasks/{task_id}/source/{ref['target_operation']['file']}")
    actual_sources = {
        path.relative_to(PUBLIC).as_posix() for path in _public_source_files()
    }
    add("public_source_inventory", actual_sources == expected_sources,
        f"actual={sorted(actual_sources)}")

    # 2. Each public source is byte-identical to the frozen upstream file.
    for task_id, ref in refs.items():
        public = PUBLIC / "tasks" / task_id / "source" / ref["target_operation"]["file"]
        cfg = PROJECTS[ref["project_id"]]
        original = cfg["root"] / ref["target_operation"]["file"]
        public_digest = _sha256(public)
        original_digest = _sha256(original)
        meta = json.loads(
            (PUBLIC / "tasks" / task_id / "task.json").read_text(encoding="utf-8"))
        add(
            f"source_byte_identical:{task_id}",
            public_digest == original_digest
            and meta["source_sha256"] == public_digest,
            "public source differs from the frozen upstream file or hash")
        add(
            f"target_location_matches_hidden:{task_id}",
            int(meta["target_operation"]["line"])
            == int(ref["target_operation"]["line"])
            and meta["target_operation"]["file"]
            == ref["target_operation"]["file"],
            "published target A differs from hidden target A")

    # 3. Forbidden hidden identifiers in metadata text.
    hidden_ids = set()
    for ref in refs.values():
        hidden_ids.update(op["id"] for op in ref["candidate_universe"])
    metadata = _metadata_files()
    for path in metadata:
        text = path.read_text(encoding="utf-8")
        for token in sorted(hidden_ids) + sorted(
                witness for ref in refs.values()
                for witness in ref["witnesses"]):
            if token in text:
                finding("hidden_identifier_in_metadata", path, token)
    add("no_hidden_identifiers_in_metadata",
        not any(f["check"] == "hidden_identifier_in_metadata"
                for f in findings),
        f"{len(hidden_ids)} hidden operation ids and all witness ids scanned")

    # 4. Forbidden hidden paths and key names.
    for path in metadata:
        text = path.read_text(encoding="utf-8")
        for token in FORBIDDEN_TEXT:
            if token in text:
                finding("hidden_path_in_metadata", path, token)
    add("no_hidden_paths_in_metadata",
        not any(f["check"] == "hidden_path_in_metadata" for f in findings),
        "hidden filesystem/reference path tokens scanned")
    for path in metadata:
        if path.suffix.lower() != ".json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        for json_path, value in _walk_json(data):
            if isinstance(value, dict):
                for key in value:
                    if key in FORBIDDEN_KEYS:
                        finding("hidden_key_in_metadata", path,
                                f"{json_path}.{key}")
    add("no_hidden_reference_keys",
        not any(f["check"] == "hidden_key_in_metadata" for f in findings),
        f"{len(FORBIDDEN_KEYS)} forbidden keys scanned")

    # 5. Hidden non-A locations and codes must not be published.
    for task_id, ref in refs.items():
        meta_path = PUBLIC / "tasks" / task_id / "task.json"
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        target = ref["target_operation"]
        for json_path, value in _walk_json(meta):
            if isinstance(value, dict):
                for key in LINE_KEYS & set(value):
                    if (int(value[key]) != int(target["line"])
                            or key != "line"):
                        # Only the single target line field is allowed.
                        if json_path.endswith("target_operation"):
                            pass
                        else:
                            finding(
                                "hidden_location_in_metadata", meta_path,
                                f"{json_path}.{key}={value[key]}")
        text = meta_path.read_text(encoding="utf-8")
        target_code = _norm(target["code"])
        for op in ref["candidate_universe"]:
            op_code = _norm(op["code"])
            # A's own code is published by design.  If a hidden operation has
            # the identical text (e.g. a repeated normalization statement),
            # its presence is not additional disclosure.
            if op_code != target_code and op_code in _norm(text):
                finding("hidden_operation_code_in_metadata", meta_path,
                        op["id"])
    add("no_hidden_locations_or_codes",
        not any(f["check"] in ("hidden_location_in_metadata",
                               "hidden_operation_code_in_metadata")
                for f in findings),
        "only A's published source line is allowed")

    # 6. Public label and wording.
    for path in metadata:
        if path.suffix.lower() != ".json":
            continue
        data = json.loads(path.read_text(encoding="utf-8"))
        if "label" in data and data["label"] != expected_label:
            finding("wrong_label", path, str(data["label"]))
    for path in metadata:
        text = path.read_text(encoding="utf-8").lower()
        for phrase in ("held-out", "held out", "test set"):
            if phrase in text and "not a future held-out" not in text:
                finding("held_out_wording", path, phrase)
    add("label_and_wording",
        not any(f["check"] in ("wrong_label", "held_out_wording")
                for f in findings),
        expected_label)

    # 7. Manifest/SHA256SUMS consistency for the built package.
    manifest_path = RELEASE / "manifest.json"
    sums_path = RELEASE / "SHA256SUMS"
    if manifest_path.exists() and sums_path.exists():
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        listed = {}
        for line in sums_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                digest, rel = line.split(None, 1)
                listed[rel.strip()] = digest
        actual = {
            path.relative_to(RELEASE).as_posix(): _sha256(path)
            for path in RELEASE.rglob("*")
            if path.is_file() and path.name not in ("manifest.json", "SHA256SUMS")
        }
        add("sha256sums_cover_every_file", listed == actual,
            f"listed={len(listed)} actual={len(actual)}")
        bundle = hashlib.sha256()
        for rel, digest in sorted(actual.items()):
            bundle.update(rel.encode("utf-8"))
            bundle.update(b"\0")
            bundle.update(digest.encode("ascii"))
            bundle.update(b"\0")
        add("manifest_bundle_sha256",
            manifest.get("bundle_sha256") == bundle.hexdigest(),
            "manifest bundle digest does not match the package")
        add("manifest_task_counts",
            manifest.get("public_file_count")
            == sum(1 for rel in actual if rel.startswith("PUBLIC/"))
            and manifest.get("hidden_file_count")
            == sum(1 for rel in actual if rel.startswith("HIDDEN/")),
            "manifest file counts disagree with the package")
    else:
        add("manifest_present", False, "run release_build first")

    report = {
        "schema": "mace_benchmark_v3_leak_report",
        "release_version": (
            json.loads(manifest_path.read_text(encoding="utf-8"))
            .get("release_version") if manifest_path.exists() else None),
        "label": expected_label,
        "task_count": len(refs),
        "public_file_count": len(actual_meta) + len(actual_sources),
        "checks": checks,
        "findings": findings,
        "passed": not findings,
    }
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    parser.add_argument("--out", type=Path, default=REPORT)
    args = parser.parse_args()
    report = _check()
    if not args.check_only:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
        )
    print(json.dumps({
        "passed": report["passed"],
        "task_count": report["task_count"],
        "public_file_count": report["public_file_count"],
        "checks": len(report["checks"]),
        "findings": report["findings"],
        "report": str(args.out),
    }, ensure_ascii=False, indent=2))
    return 0 if report["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
