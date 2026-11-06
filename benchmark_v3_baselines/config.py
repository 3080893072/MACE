"""Frozen run configuration for the v3 baseline pilot.

Everything that could change a baseline result is fixed here *before* the
run: model identity, generation parameters, budgets, the public input scope,
the verifier limits and the output layout.  The values are written to
``config.json`` next to the run artifacts so the report can cite a hash.
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict

KIT = Path(__file__).resolve().parents[1]
PUBLIC = KIT / "benchmark_real_v3" / "release" / "PUBLIC"
PROBES = KIT / "benchmark_real_v3" / "probes"
RUN_ROOT = KIT / "runs" / "v3_baseline_pilot"

TASK_IDS = [
    "jinja2_bytecode_cache_read",
    "werkzeug_bind_server_name_lower",
    "werkzeug_filestorage_stream_name",
    "werkzeug_get_host_default_empty",
    "werkzeug_secure_filename_ascii_filter",
]

TASK_STORY = {
    "jinja2_bytecode_cache_read": "NO_LOCAL_EFFECT",
    "werkzeug_filestorage_stream_name": "ASSERTION_GAP_STORY",
    "werkzeug_bind_server_name_lower": "NO_LOCAL_EFFECT",
    "werkzeug_get_host_default_empty": "FULL_MASKING_STORY",
    "werkzeug_secure_filename_ascii_filter": "FULL_MASKING_STORY",
}

# The frozen M5 experiments used this model.  Keeping the same identity makes
# the baseline a fair comparison against historical Full MACE runs.
MODEL = {
    "provider": "ollama",
    "model": "qwen2.5-coder:32b",
    "endpoint": "http://127.0.0.1:11434",
    "temperature": 0.0,
    "seed": 42,
    "num_ctx": 32768,
    "num_predict": 4096,
    "json_mode": True,
    "timeout_seconds": 900,
    "retries": 1,
}

BUDGET = {
    "max_model_calls_per_task": 3,
    "max_model_calls_total": 15,
    "max_completion_tokens_per_task": 3 * 4096,
    "max_probe_executions_per_task": 6000,
    "max_probe_executions_total": 30000,
    "max_candidate_ops": 6,
    "max_inputs": 8,
    "probe_timeout_seconds": 180,
    "max_claims_per_task": 40,
}

# Baseline A is one call only; baseline B is one call plus deterministic
# verification.  A feedback/regeneration condition is declared but *not*
# executed in this pilot (it would need the live model).
B_CONDITIONS = ["pure_verification", "feedback_regeneration"]


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"], cwd=str(KIT),
            capture_output=True, text=True, timeout=30)
        return out.stdout.strip() or "unknown"
    except Exception:  # noqa: BLE001 - recorded as-is
        return "unknown"


def experiment_config() -> Dict[str, Any]:
    from benchmark_v3_baselines.claims import SUBMISSION_SCHEMA_VERSION

    task_hashes = {}
    for task_id in TASK_IDS:
        task_path = PUBLIC / "tasks" / task_id / "task.json"
        source_rel = json.loads(
            task_path.read_text(encoding="utf-8"))["source_path"]
        source_path = PUBLIC / "tasks" / task_id / source_rel
        task_hashes[task_id] = {
            "task_json_sha256": _sha256_file(task_path),
            "source_sha256": _sha256_file(source_path),
        }
    return {
        "experiment": "mace_v3_baseline_pilot",
        "schema_version": SUBMISSION_SCHEMA_VERSION,
        "release_version": "v3.0-dev-pilot-2026-11-02",
        "git_commit": _git_commit(),
        "git_branch": os.environ.get("MACE_BASELINE_BRANCH", "baseline/mace-v3-pilot"),
        "model": MODEL,
        "budget": BUDGET,
        "b_conditions": B_CONDITIONS,
        "task_ids": TASK_IDS,
        "task_story": TASK_STORY,
        "task_hashes": task_hashes,
        "public_root": str(PUBLIC),
        "probe_root": str(PROBES),
        "hidden_data_in_scope": False,
    }


def config_sha256(config: Dict[str, Any]) -> str:
    text = json.dumps(config, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))
    return hashlib.sha256(text.encode("utf-8")).hexdigest()
