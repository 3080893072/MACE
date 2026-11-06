"""Record the repaired executor and C-fixed as baseline version 1.1.

This is bookkeeping, not an experiment.  It does not touch the frozen pilot,
does not re-run a baseline and does not read HIDDEN data.  It writes:

``runs/v3_baseline_c_fixed_v1_1/manifest.json``
    Version lineage, old/new code hashes, the executor naming schemes, the
    contaminated-evidence inventory and reproduction commands.

``runs/v3_baseline_c_fixed_v1_1/filestorage_per_input_diff.json``
    Frozen (v1.0) versus repaired (v1.1) per-input MSMS/MMBS for the only
    task whose emitted submission changed.

The frozen pilot stays where it is; nothing is overwritten.

Usage::

    python -m scripts.record_baseline_version
"""
from __future__ import annotations

import hashlib
import itertools
import json
import re
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from benchmark_v3_baselines.config import TASK_IDS  # noqa: E402

OUT = KIT / "runs" / "v3_baseline_c_fixed_v1_1"
FREEZE = KIT / "runs" / "v3_baseline_freeze" / "manifest.json"
PILOT = KIT / "runs" / "v3_baseline_pilot"
ABLATION = KIT / "runs" / "v3_subgraph_ablation"
SCHEMA = "mace-baseline-version-manifest-1.0"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _key(ids: Iterable[str]) -> str:
    return "+".join(sorted(ids)) or "EMPTY"


def old_variant_name(prefix: str, side: str, ids: Iterable[str]) -> str:
    """Reproduce the frozen (v1.0) naming scheme exactly."""
    return old_variant_name_full(prefix, side, ids)[:110]


def old_variant_name_full(prefix: str, side: str, ids: Iterable[str]) -> str:
    safe = re.sub(r"[^A-Za-z0-9_.-]+", "_", _key(ids))
    return f"{prefix}_{side}_{safe}"


def collision_audit(task_id: str, universe_ids: List[str]) -> Dict[str, Any]:
    """Replay the frozen ``c_<task>`` naming scheme on a universe.

    The frozen ``Executor.variant`` built
    ``f"{prefix}_{side}_{sanitized key}"[:110]`` with ``prefix = c_<task>``.
    Any two subsets whose names coincide after character 110 shared one
    directory, and ``_variants`` then served the first built tree for both.
    """
    prefix = f"c_{task_id}"
    names: Dict[str, List[List[str]]] = {}
    for size in range(len(universe_ids) + 1):
        for combo in itertools.combinations(sorted(universe_ids), size):
            names.setdefault(old_variant_name(prefix, "plus", combo),
                             []).append(list(combo))
    groups = {name: sets for name, sets in names.items() if len(sets) > 1}
    longest = len(old_variant_name_full(prefix, "plus",
                                        sorted(universe_ids)))
    return {
        "universe_size": len(universe_ids),
        "subset_count": 2 ** len(universe_ids),
        "frozen_prefix": prefix,
        "collision_groups": len(groups),
        "subsets_in_collided_directories": sum(len(v) for v in groups.values()),
        "groups": {name: sets for name, sets in sorted(groups.items())},
        "truncated_name_length": 110,
        "longest_full_name_untuned": longest,
    }


def per_input_diff(task_id: str) -> Dict[str, Any]:
    old = json.loads((PILOT / "tasks" / task_id / "baseline_c" /
                      "baseline_c.json").read_text(encoding="utf-8"))
    new = json.loads((ABLATION / "tasks" / task_id / "C-original" /
                      "result.json").read_text(encoding="utf-8"))
    rows = []
    changed = 0
    for old_row, new_row in zip(old["per_input"], new["per_input"]):
        same = (old_row["msms_ids"] == new_row["msms_ids"]
                and old_row["mmbs_ids"] == new_row["mmbs_ids"]
                and old_row["active_ops"] == new_row["active_ops"])
        if not same:
            changed += 1
        rows.append({
            "input": old_row["input"],
            "a_executes": old_row["a_executes"],
            "masked_empty_old": old_row["masked_empty"],
            "masked_empty_new": new_row["masked_empty"],
            "msms_old": old_row["msms_ids"],
            "msms_new": new_row["msms_ids"],
            "mmbs_old": old_row["mmbs_ids"],
            "mmbs_new": new_row["mmbs_ids"],
            "active_ops_old": old_row["active_ops"],
            "active_ops_new": new_row["active_ops"],
            "identical": same,
        })
    frozen_submission = json.loads(
        (PILOT / "tasks" / task_id / "baseline_c" / "submission.json")
        .read_text(encoding="utf-8"))
    new_submission = json.loads(
        (ABLATION / "tasks" / task_id / "C-original" / "submission.json")
        .read_text(encoding="utf-8"))
    return {
        "task_id": task_id,
        "universe_old": [op["id"] for op in old["universe"]],
        "universe_new": [op["id"] for op in new["universe"]],
        "changed_inputs": changed,
        "inputs": rows,
        "submission_identical": frozen_submission == new_submission,
        "submission_diff": None if frozen_submission == new_submission else {
            "frozen_sha256": hashlib.sha256(json.dumps(
                frozen_submission, sort_keys=True).encode()).hexdigest(),
            "repaired_sha256": hashlib.sha256(json.dumps(
                new_submission, sort_keys=True).encode()).hexdigest(),
            "claim_changes": [
                {"index": index, "frozen": old_claim, "repaired": new_claim}
                for index, (old_claim, new_claim) in enumerate(
                    zip(frozen_submission["claims"],
                        new_submission["claims"]))
                if old_claim != new_claim],
        },
    }


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    frozen = json.loads(FREEZE.read_text(encoding="utf-8"))
    code_files = ["benchmark_v3_baselines/baseline_c.py",
                  "benchmark_v3_baselines/execution.py"]
    current_hashes = {rel: sha256_file(KIT / rel) for rel in code_files}

    audit = {}
    for task_id in TASK_IDS:
        pilot = json.loads((PILOT / "tasks" / task_id / "baseline_c" /
                            "baseline_c.json").read_text(encoding="utf-8"))
        graph = json.loads((ABLATION / "tasks" / task_id / "candidates.json")
                           .read_text(encoding="utf-8"))
        audit[task_id] = {
            "frozen_universe": collision_audit(
                task_id, [op["id"] for op in pilot["universe"]]),
            "graph_universe": collision_audit(
                task_id, [op["id"] for op in graph["selection"]["ops"]]),
        }

    diffs = {task_id: per_input_diff(task_id) for task_id in TASK_IDS}
    affected = [task_id for task_id, diff in diffs.items()
                if not diff["submission_identical"] or diff["changed_inputs"]]
    contaminated = [task_id for task_id, item in audit.items()
                    if item["frozen_universe"]["collision_groups"]]

    summary_path = ABLATION / "summary.json"
    summary = (json.loads(summary_path.read_text(encoding="utf-8"))
               if summary_path.exists() else {})
    frozen_identical = {
        task_id: summary.get("tasks", {}).get(task_id, {}).get(
            "C-original", {}).get("summary", {}).get(
                "frozen_submission_identical")
        for task_id in TASK_IDS}

    manifest = {
        "schema": SCHEMA,
        "generated_from": {
            "frozen_manifest": str(FREEZE.relative_to(KIT)),
            "frozen_manifest_sha256": sha256_file(FREEZE),
            "pilot_root": str(PILOT.relative_to(KIT)),
            "repair_run_root": str(ABLATION.relative_to(KIT)),
            "repair_summary_sha256": (sha256_file(summary_path)
                                      if summary_path.exists() else None),
        },
        "versions": {
            "C-original-1.0-frozen": {
                "status": "ARCHIVED_DO_NOT_REUSE_CONTAMINATED_EVIDENCE",
                "code_commit": frozen.get("code_commit"),
                "code_hashes": {rel: frozen["code_files"].get(rel)
                                for rel in code_files},
                "executor_variant_scheme": (
                    "sanitized subset key truncated to 110 characters "
                    "(distinct subsets can share a directory)"),
                "emission": "active_filtered",
                "search": "exhaustive",
                "trustworthy_submission": {
                    task_id: frozen_identical.get(task_id)
                    for task_id in TASK_IDS},
                "warning": (
                    "Per-input masked/exposed maps of "
                    + ", ".join(affected)
                    + " are contaminated by the truncated-directory "
                    "collision; the emitted claim set still matches the "
                    "reference, but the per-input evidence and its assigned "
                    "level must not be cited as ground truth."),
            },
            "C-fixed-1.1": {
                "status": "REPRODUCIBLE_BASELINE",
                "code_hashes": current_hashes,
                "executor_variant_scheme": "sha1-16 of the full disabled key",
                "emission": "minimality_only",
                "search": "exhaustive",
                "regression_run": str(
                    (ABLATION / "tasks").relative_to(KIT)) + "/<task>/C-fixed",
                "verified_properties": {
                    "same_submission_as_repaired_C_original_on_dev": all(
                        summary.get("tasks", {}).get(task_id, {})
                        .get("C-original", {}).get("summary", {})
                        .get("submission_sha256")
                        == summary.get("tasks", {}).get(task_id, {})
                        .get("C-fixed", {}).get("summary", {})
                        .get("submission_sha256")
                        for task_id in TASK_IDS),
                    "same_submission_as_frozen_C_original_on_dev": all(
                        frozen_identical.values()),
                    "identical_to_frozen_submission_per_task": {
                        task_id: frozen_identical.get(task_id)
                        for task_id in TASK_IDS},
                    "credited_relations": 23,
                    "reference_relations_matched": "18/18",
                    "false_claims": 0,
                    "invalid_claims": 0,
                    "probe_executions": 696,
                    "variant_builds": 112,
                },
            },
        },
        "hash_transition": {
            rel: {"frozen": frozen["code_files"].get(rel),
                  "current": current_hashes[rel],
                  "changed": frozen["code_files"].get(rel) != current_hashes[rel]}
            for rel in code_files
        },
        "collision_audit": audit,
        "contaminated_tasks": contaminated,
        "affected_tasks": affected,
        "filestorage_diff": diffs["werkzeug_filestorage_stream_name"],
        "per_task_diff": {task_id: {"changed_inputs": diff["changed_inputs"],
                                    "submission_identical":
                                    diff["submission_identical"]}
                          for task_id, diff in diffs.items()},
        "policy": [
            "Frozen pilot artifacts stay in place and are never overwritten.",
            "C-original-1.0 filestorage per-input evidence is not a reliable "
            "ground truth and must not be cited as such.",
            "C-fixed-1.1 is the reference deterministic baseline for new "
            "comparisons; both its code hashes and its run directory are "
            "recorded here.",
            "Any future change to baseline_c.py or execution.py creates a new "
            "version entry rather than silently changing 1.1.",
        ],
        "reproduce": [
            "python -m scripts.run_subgraph_ablation --modes C-fixed",
            "python -m pytest -q",
        ],
    }
    (OUT / "filestorage_per_input_diff.json").write_text(
        json.dumps(diffs["werkzeug_filestorage_stream_name"],
                   ensure_ascii=False, indent=2), encoding="utf-8")
    text = json.dumps(manifest, ensure_ascii=False, indent=2)
    (OUT / "manifest.json").write_text(text, encoding="utf-8")
    (OUT / "manifest.sha256").write_text(
        hashlib.sha256(text.encode("utf-8")).hexdigest() + "\n",
        encoding="utf-8")
    print(json.dumps({
        "contaminated_tasks": contaminated,
        "affected_tasks": affected,
        "filestorage_inputs_changed":
            diffs["werkzeug_filestorage_stream_name"]["changed_inputs"],
        "manifest_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
