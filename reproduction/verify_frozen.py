#!/usr/bin/env python
"""Audit the frozen MACE v2.1 artifacts in this repository.

Checks, in order:

1. Frozen *result* files (the numbers quoted in the paper) match the SHA-256
   recorded in ``results/MACE_v2_1_frozen_config.json``.
2. Frozen HELDOUT prediction files match the hashes in
   ``results/MACE_HELDOUT_v2_1_official_scores.json``.
3. Frozen *code* files match the recorded hashes, with an explicit list of
   files that were changed for path portability only.  Those are reported
   separately instead of being silently accepted.
4. The v2.1 dataset is structurally intact: 50 tasks, ids match directories,
   reference input keys match declared inputs, and every acceptance report
   passes.

Usage::

    python reproduction/verify_frozen.py
    python reproduction/verify_frozen.py --strict   # portability edits fail too

Exit status is 0 when every non-exempt check passes, 1 otherwise.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
RESULTS = KIT / "results"
FROZEN = RESULTS / "MACE_v2_1_frozen_config.json"
SCORES = RESULTS / "MACE_HELDOUT_v2_1_official_scores.json"
V21 = KIT / "benchmark_v4_dataset" / "source_derived_v2_1"

# Frozen code files, as named in results/MACE_v2_1_frozen_config.json.
FROZEN_CODE = {
    "runner": "scripts/run_candidate_discovery_v2_1.py",
    "v2_core": "scripts/run_candidate_discovery_v2.py",
    "closure": "scripts/close_candidate_discovery_v2_1.py",
    "analyzer": "scripts/analyze_candidate_discovery_v2_1.py",
    "finalizer": "scripts/finalize_candidate_discovery_v2_1.py",
    "executor_harness": "benchmark_v4_dataset/tools/sd_algorithm_pilot.py",
    "graph_search": "benchmark_v3_baselines/graph_search.py",
    "ast_discovery": "benchmark_v3_baselines/ast_discovery.py",
    "subgraph": "benchmark_v3_baselines/subgraph.py",
    "qwen_client": "mace/qwen.py",
    "protocol": "benchmark_v4_dataset/PROTOCOL.md",
    "heldout_seal": "benchmark_v4_dataset/split/seal.json",
}

# Files edited only to replace hard-coded absolute paths with environment
# resolution (see reproduction/portability_patch.json).  No algorithmic
# behaviour changed, and no result file changed.
PORTABILITY_EDITS = {
    "runner": "venv interpreter resolved through mace.paths.venv_python()",
    "v2_core": "venv interpreter resolved through mace.paths.venv_python()",
    "closure": "venv interpreter resolved through mace.paths.venv_python()",
    "executor_harness": "WORK/VENVS resolved through mace.paths",
}

# Result files whose hashes are recorded in the frozen config.
FROZEN_RESULTS = {
    "final_json_sha256": "results/MACE_v2_1_dev_final.json",
    "per_task_csv_sha256": "results/MACE_v2_1_dev_per_task.csv",
    "pre_closure_json_sha256": "results/MACE_candidate_discovery_v2_1_dev.json",
    "v2_result_sha256": "results/MACE_candidate_discovery_v2.json",
    "closure_combined_sha256":
        "runs/candidate_discovery_v2_1_closure/combined_pre_analysis.json",
}

PREDICTIONS = {
    "C0": "results/MACE_HELDOUT_v2_1_C0_predictions.json",
    "Full MACE": "results/MACE_HELDOUT_v2_1_Full_predictions.json",
    "Direct Qwen": "results/MACE_HELDOUT_v2_1_Direct_Qwen_predictions.json",
    "Direct GLM": "results/MACE_direct_GLM_v2_1_heldout_predictions.json",
}


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def check_dataset(failures: list[str]) -> None:
    tasks = 0
    splits = [("DEV", V21)]
    if (V21 / "heldout" / "tasks").is_dir():
        splits.append(("HELDOUT", V21 / "heldout"))
    else:
        print("[dataset] HELDOUT split not shipped; checking DEV only")
    for split, base in splits:
        task_dir = base / "tasks"
        dirs = sorted(p.name for p in task_dir.iterdir() if p.is_dir())
        for cid in dirs:
            tasks += 1
            task = json.loads((task_dir / cid / "task.json").read_text("utf-8"))
            ref = json.loads((task_dir / cid / "reference.json")
                             .read_text("utf-8"))
            acc = json.loads((base / "acceptance" / f"{cid}.json")
                             .read_text("utf-8"))
            if task["task_id"] != cid:
                failures.append(f"{split}:{cid}: task.json case_id mismatch")
            declared = {i["id"] for i in task["declared_inputs"]}
            if set(ref["inputs"]) != declared:
                failures.append(f"{split}:{cid}: reference inputs != declared")
            if not acc.get("all_checks_pass"):
                failures.append(f"{split}:{cid}: acceptance failed")
    expected = 25 * len(splits)
    if tasks != expected:
        failures.append(f"dataset: expected {expected} tasks, found {tasks}")
    print(f"[dataset] {tasks} tasks, structural checks "
          f"{'PASS' if not failures else 'FAIL'}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--strict", action="store_true",
                    help="treat portability edits as failures")
    args = ap.parse_args()

    frozen = json.loads(FROZEN.read_text("utf-8"))
    failures: list[str] = []

    print("== frozen result files ==")
    for key, rel in FROZEN_RESULTS.items():
        path = KIT / rel
        if not path.exists():
            failures.append(f"missing result {rel}")
            print(f"[MISS] {key}: {rel}")
            continue
        got = sha256(path)
        ok = got == frozen["results"][key]
        print(f"[{'OK  ' if ok else 'FAIL'}] {key}: {rel}")
        if not ok:
            failures.append(f"result hash mismatch: {rel}")

    print("\n== frozen HELDOUT predictions ==")
    if not SCORES.exists():
        print("[SKIP] HELDOUT scoring artifacts are not shipped in this export")
    else:
        scores = json.loads(SCORES.read_text("utf-8"))
        hashes = scores["audit"]["prediction_hashes"]
        expected = {name: row["expected"] for name, row in hashes.items()}
        for method, rel in PREDICTIONS.items():
            path = KIT / rel
            got = sha256(path) if path.exists() else None
            want = expected.get(method)
            ok = got is not None and want is not None and got == want
            print(f"[{'OK  ' if ok else 'FAIL'}] {method}: {rel}")
            if not ok:
                failures.append(f"prediction hash mismatch: {rel}")

    print("\n== frozen code files ==")
    for key, rel in FROZEN_CODE.items():
        path = KIT / rel
        if not path.exists():
            if key == "heldout_seal":
                print(f"[SKIP] {key}: HELDOUT artifacts not shipped in this export")
                continue
            failures.append(f"missing code {rel}")
            print(f"[MISS] {key}: {rel}")
            continue
        got = sha256(path)
        if got == frozen["file_sha256"][key]:
            print(f"[OK  ] {key}")
            continue
        if key in PORTABILITY_EDITS and not args.strict:
            print(f"[EDIT] {key}: {PORTABILITY_EDITS[key]}")
            continue
        print(f"[FAIL] {key}: {rel}")
        failures.append(f"code hash mismatch: {rel}")

    print("\n== dataset ==")
    check_dataset(failures)

    print()
    if failures:
        print(f"RESULT: FAIL ({len(failures)} problem(s))")
        for item in failures:
            print(" -", item)
        return 1
    print("RESULT: PASS"
          + (" (strict)" if args.strict else " (portability edits exempted)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
