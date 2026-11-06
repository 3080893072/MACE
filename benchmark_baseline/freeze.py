"""Freeze the development baseline before any model call.

The frozen record pins the prompt bytes, the public bundle, the submission
interface, the model checkpoint and the run budget.  ``run.py`` refuses to
start unless the live files still match this record.

Usage::

    python -m benchmark_baseline.freeze            # write / verify
    python -m benchmark_baseline.freeze --write    # write (refuses overwrite)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict

from benchmark_baseline.prompts import prompt_manifest
from benchmark_real_v3.config import V3
from benchmark_real_v3.scoring.engine import SCORER_VERSION

BASELINE = Path(__file__).resolve().parents[1] / "benchmark_baseline"
FREEZE_PATH = BASELINE / "freeze.json"

MODEL = {
    "provider": "transformers-local",
    "path": "D:/tmp/qwen15b",
    "model": "qwen15b",
    "family": "Qwen2.5-Coder-1.5B-Instruct",
    "dtype": "bfloat16",
    "device": "cuda",
    "do_sample": False,
    "temperature": 0.0,
    "seed": 42,
    "max_new_tokens": 1536,
    "context_window": 32768,
    "json_mode": "prompt-only (the local generator has no grammar hook)",
    "credentials": "none; local read-only checkpoint",
}
MODEL_FILES = [
    "model.safetensors",
    "config.json",
    "generation_config.json",
    "tokenizer.json",
    "tokenizer_config.json",
    "vocab.json",
    "merges.txt",
]

BUDGET = {
    "task_count": 5,
    "direct": {
        "model_calls_per_task": 1,
        "validator_rounds": 0,
    },
    "validator": {
        "model_calls_per_task": 3,
        "validator_rounds": 3,
        "feedback": "status only; no hidden labels, no operation lists",
    },
    "ast_intervention": {
        "model_calls_per_task": 0,
        "max_inputs_per_task": 12,
        "max_candidate_operations_per_task": 32,
        "max_variant_builds_per_task": 64,
    },
    "scoring_runs_per_saved_submission": 1,
}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                               sort_keys=True) + "\n", encoding="utf-8")


def model_fingerprint() -> Dict[str, Any]:
    root = Path(MODEL["path"])
    files = {}
    digest = hashlib.sha256()
    for name in MODEL_FILES:
        path = root / name
        if not path.exists():
            files[name] = None
            continue
        sha = hashlib.sha256(path.read_bytes()).hexdigest()
        files[name] = {"sha256": sha, "bytes": path.stat().st_size}
        digest.update(name.encode("utf-8"))
        digest.update(b"\0")
        digest.update(sha.encode("ascii"))
        digest.update(b"\0")
    return {"root": str(root), "files": files,
            "checkpoint_sha256": digest.hexdigest()}


def build_record() -> Dict[str, Any]:
    manifest = json.loads(
        (V3 / "release" / "manifest.json").read_text(encoding="utf-8"))
    prompt = prompt_manifest()
    model = dict(MODEL)
    model["fingerprint"] = model_fingerprint()
    return {
        "schema": "mace_benchmark_v3_baseline_freeze",
        "frozen_utc": datetime.now(timezone.utc).isoformat(),
        "release_version": manifest["release_version"],
        "label": manifest["label"],
        "dev_only": True,
        "generalization_claim": (
            "Development pilot only.  The five tasks are the construction "
            "set; they are not an independent evaluation set."),
        "bundle_sha256": manifest["bundle_sha256"],
        "scorer_version": SCORER_VERSION,
        "refreeze_note": (
            "v1.0 was frozen, then aborted after one direct call: the local "
            "RTX 5060 torch build has only the math SDPA kernel, so a 14.5k-"
            "token prompt exhausted 8 GiB during prefill.  v1.1 keeps the same "
            "task/contract/interface and shortens only the deterministic "
            "source window (+/-120 lines, 20k chars).  No hidden data and no "
            "task content changed.  The aborted v1.0 run is archived, not "
            "scored."),
        "prompt": prompt,
        "submission_format_sha256": prompt["submission_format_sha256"],
        "model": model,
        "budget": BUDGET,
        "full_mace": {
            "status": "UNSUPPORTED_INTERFACE",
            "reason": (
                "The original Full MACE reports parameter/effect-level "
                "attribution (target_effects, upstream, observers, "
                "mask_guard) and has no relation-level operations field and "
                "no per-relation legal input.  No score is assigned."),
        },
        "leakage_rules": [
            "Prompts contain only files inside release/PUBLIC.",
            "Hidden references, matrices, story labels and witnesses are "
            "never read by the prompt builder.",
            "Validator feedback carries statuses only.",
            "No model output is edited using private ground truth.",
        ],
    }


def load_frozen() -> Dict[str, Any]:
    if not FREEZE_PATH.exists():
        raise SystemExit(
            f"no frozen baseline at {FREEZE_PATH}; run "
            "`python -m benchmark_baseline.freeze --write` first")
    frozen = json.loads(FREEZE_PATH.read_text(encoding="utf-8"))
    live_prompt = prompt_manifest()
    if live_prompt != frozen["prompt"]:
        raise SystemExit(
            "prompt, public bundle or submission format changed after the "
            "freeze; refusing to run.  Re-freeze deliberately with a new "
            "version if this is intended.")
    live_model = model_fingerprint()
    if live_model != frozen["model"].get("fingerprint"):
        raise SystemExit(
            "the local Qwen checkpoint changed after the freeze; refusing to "
            "run.  Re-freeze deliberately if this is intended.")
    return frozen


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    args = parser.parse_args()
    if not args.write:
        frozen = load_frozen()
        print(json.dumps({
            "freeze": str(FREEZE_PATH),
            "prompt_sha256": frozen["prompt"]["prompt_sha256"],
            "bundle_sha256": frozen["bundle_sha256"],
            "model": frozen["model"]["model"],
            "budget": frozen["budget"],
            "verified": True,
        }, ensure_ascii=False, indent=2))
        return 0
    if FREEZE_PATH.exists():
        print(f"refusing to overwrite {FREEZE_PATH}", file=sys.stderr)
        return 1
    record = build_record()
    _write_json(FREEZE_PATH, record)
    print(json.dumps({
        "written": str(FREEZE_PATH),
        "prompt_sha256": record["prompt"]["prompt_sha256"],
        "bundle_sha256": record["bundle_sha256"],
        "frozen_utc": record["frozen_utc"],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
