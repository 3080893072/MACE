"""Run the v3 baseline pilot.

Usage::

    python -m benchmark_v3_baselines.run_pilot              # honest run
    python -m benchmark_v3_baselines.run_pilot --dry-run    # plumbing only

The honest run executes Baseline C (no model) and, only if a real Qwen
service answers, Baselines A and B.  If the service is unavailable it writes
``NOT_RUN`` with the availability evidence; it never substitutes a fake
client for a live run.

Scoring is delegated to the frozen official scorer in a subprocess, so this
package itself never opens the hidden reference.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional

from benchmark_v3_baselines import baseline_c, direct_qwen
from benchmark_v3_baselines.config import (
    BUDGET, MODEL, RUN_ROOT, TASK_IDS, TASK_STORY, config_sha256,
    experiment_config)
from benchmark_v3_baselines.public_io import load_task
from benchmark_v3_baselines.verifier import verify_submission

KIT = Path(__file__).resolve().parents[1]
DRY_FIXTURES = Path(__file__).resolve().parent / "fixtures" / "dry_run"


# --------------------------------------------------------------------- model
def _get(url: str, timeout: int = 3) -> Any:
    with urllib.request.urlopen(url, timeout=timeout) as response:
        return json.loads(response.read().decode("utf-8"))


def check_availability() -> Dict[str, Any]:
    binary = shutil.which("ollama")
    endpoint_ok = False
    endpoint_error = ""
    tags: Any = None
    try:
        tags = _get(MODEL["endpoint"] + "/api/tags")
        endpoint_ok = True
    except Exception as exc:  # noqa: BLE001
        endpoint_error = f"{type(exc).__name__}: {exc}"
    model_present = False
    if endpoint_ok:
        try:
            names = [item.get("name") for item in tags.get("models", [])]
            model_present = MODEL["model"] in names
        except Exception:  # noqa: BLE001
            model_present = False
    return {
        "checked_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "provider": MODEL["provider"],
        "model": MODEL["model"],
        "endpoint": MODEL["endpoint"],
        "ollama_binary": binary,
        "endpoint_reachable": endpoint_ok,
        "endpoint_error": endpoint_error,
        "endpoint_models": (tags or {}).get("models") if isinstance(tags, dict) else None,
        "model_present": model_present,
        "dashscope_key_present": bool(os.environ.get("DASHSCOPE_API_KEY")),
        "available": bool(endpoint_ok and model_present),
    }


class ScriptedClient:
    """DRY_RUN only: returns a stored response; never used as a live run."""

    provider = "scripted-dry-run"
    model = "scripted-fixture"

    def __init__(self, path: Path):
        self.path = path
        self.calls: List[Dict[str, Any]] = []

    def chat(self, messages, purpose="", json_mode=True):
        from mace.qwen import Response

        content = self.path.read_text(encoding="utf-8")
        stats = {"prompt_tokens": 0, "completion_tokens": 0,
                 "wall_seconds": 0.0, "dry_run": True}
        self.calls.append({"purpose": purpose, "messages": messages,
                           "stats": stats, "response": content})
        return Response(content=content, stats=stats, request_messages=messages)


def _live_client():
    from mace.qwen import QwenClient

    return QwenClient(
        provider=MODEL["provider"], model=MODEL["model"],
        endpoint=MODEL["endpoint"], num_ctx=MODEL["num_ctx"],
        temperature=MODEL["temperature"], seed=MODEL["seed"],
        timeout=MODEL["timeout_seconds"], retries=MODEL["retries"])


# -------------------------------------------------------------------- scoring
def score(task_id: str, submission_path: Path, out_path: Path) -> Dict[str, Any]:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    completed = subprocess.run(
        [sys.executable, "-m", "benchmark_real_v3.scoring.score",
         str(submission_path), "--out", str(out_path)],
        cwd=str(KIT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=1800,
    )
    if not out_path.exists():
        return {"status": "SCORING_FAILED",
                "stderr_tail": completed.stderr[-4000:]}
    return json.loads(out_path.read_text(encoding="utf-8"))


# ---------------------------------------------------------------------- main
def run_task(task_id: str, out_root: Path, availability: Dict[str, Any],
             dry_run: bool = False, run_c: bool = True) -> Dict[str, Any]:
    task_dir = out_root / "tasks" / task_id
    task_dir.mkdir(parents=True, exist_ok=True)
    summary: Dict[str, Any] = {
        "task_id": task_id,
        "story": TASK_STORY[task_id],
        "baselines": {},
    }

    # ---- Baseline A / B -------------------------------------------------
    if not availability["available"] and not dry_run:
        reason = (
            "real Qwen service unavailable: "
            f"ollama_binary={availability['ollama_binary']!r}, "
            f"endpoint_reachable={availability['endpoint_reachable']}, "
            f"model_present={availability['model_present']}, "
            f"dashscope_key_present={availability['dashscope_key_present']}")
        summary["baselines"]["A_direct_qwen"] = {
            "run_label": "NOT_RUN", "reason": reason}
        summary["baselines"]["B_qwen_verifier"] = {
            "run_label": "NOT_RUN", "reason": reason}
    else:
        run_label = "DRY_RUN" if dry_run else "LIVE_MODEL_RUN"
        client = (ScriptedClient(DRY_FIXTURES / f"{task_id}.json")
                  if dry_run else _live_client())
        started = time.time()
        try:
            record = direct_qwen.run(
                client, task_id, out_dir=task_dir / "baseline_a",
                submission_id="baseline-A")
            record["run_label"] = run_label
            record["model_calls"] = 1
            record["wall_seconds"] = round(time.time() - started, 3)
            (task_dir / "baseline_a" / "run.json").write_text(
                json.dumps(record, ensure_ascii=False, indent=2),
                encoding="utf-8")
            a_score = score(task_id, task_dir / "baseline_a" / "submission.json",
                            task_dir / "scores" / "A.json")
            summary["baselines"]["A_direct_qwen"] = {
                "run_label": run_label,
                "submission": record["submission"],
                "score": a_score,
                "model_calls": 1,
                "usage": record.get("response_stats"),
                "input_contract_errors": record["input_contract_errors"],
            }

            b_started = time.time()
            verified = verify_submission(
                task_id, record["submission"], max_ops=BUDGET["max_candidate_ops"])
            b_dir = task_dir / "baseline_b"
            b_dir.mkdir(parents=True, exist_ok=True)
            (b_dir / "verifier.json").write_text(
                json.dumps(verified, ensure_ascii=False, indent=2),
                encoding="utf-8")
            (b_dir / "verified_submission.json").write_text(
                json.dumps(verified["verified_submission"], ensure_ascii=False,
                           indent=2), encoding="utf-8")
            b_score = score(task_id, b_dir / "verified_submission.json",
                            task_dir / "scores" / "B.json")
            summary["baselines"]["B_qwen_verifier"] = {
                "run_label": run_label,
                "condition": "pure_verification",
                "feedback_regeneration": "NOT_RUN (not executed in this pilot)",
                "verifier_counts": verified["counts"],
                "score": b_score,
                "model_calls": 1,
                "probe_executions": verified["probe_executions"],
                "wall_seconds": round(time.time() - b_started, 3),
            }
        except Exception as exc:  # noqa: BLE001 - recorded, never faked
            summary["baselines"]["A_direct_qwen"] = {
                "run_label": run_label, "error": f"{type(exc).__name__}: {exc}"}
            summary["baselines"]["B_qwen_verifier"] = {
                "run_label": run_label, "error": f"{type(exc).__name__}: {exc}"}

    # ---- Baseline C -----------------------------------------------------
    if run_c:
        c_started = time.time()
        c_result = baseline_c.run_and_write(task_id, task_dir / "baseline_c")
        c_score = score(task_id, task_dir / "baseline_c" / "submission.json",
                        task_dir / "scores" / "C.json")
        summary["baselines"]["C_ast_intervention"] = {
            "run_label": "NO_MODEL_DETERMINISTIC_RUN",
            "universe": c_result["universe"],
            "pruning": c_result["pruning"],
            "per_input": c_result["per_input"],
            "submission": c_result["submission"],
            "unknowns": c_result["unknowns"],
            "score": c_score,
            "model_calls": 0,
            "probe_executions": c_result["probe_executions"],
            "variant_builds": c_result["variant_builds"],
            "wall_seconds": round(time.time() - c_started, 3),
        }

    # ---- legacy Full MACE ----------------------------------------------
    summary["baselines"]["legacy_full_mace"] = {
        "run_label": "UNSUPPORTED_INTERFACE",
        "reason": (
            "The historical Full MACE run loop emits code-level guards and "
            "does not expose an operation-level MSMS/MMBS submission "
            "interface. It is recorded as unsupported, not as zero."),
    }

    (task_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", nargs="*", choices=TASK_IDS,
                        default=TASK_IDS)
    parser.add_argument("--out", type=Path, default=RUN_ROOT)
    parser.add_argument("--dry-run", action="store_true",
                        help="exercise A/B plumbing with stored responses")
    parser.add_argument("--skip-c", action="store_true")
    args = parser.parse_args(argv)

    out_root = args.out
    out_root.mkdir(parents=True, exist_ok=True)
    config = experiment_config()
    (out_root / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_root / "config.sha256").write_text(
        config_sha256(config) + "\n", encoding="utf-8")
    availability = check_availability()
    (out_root / "availability.json").write_text(
        json.dumps(availability, ensure_ascii=False, indent=2),
        encoding="utf-8")

    summaries = []
    for task_id in args.tasks:
        print(f"[v3-baseline] {task_id}", flush=True)
        summaries.append(run_task(task_id, out_root, availability,
                                  dry_run=args.dry_run,
                                  run_c=not args.skip_c))

    payload = {
        "experiment": config["experiment"],
        "release_version": config["release_version"],
        "git_commit": config["git_commit"],
        "config_sha256": config_sha256(config),
        "availability": availability,
        "dry_run": args.dry_run,
        "tasks": summaries,
    }
    (out_root / "summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({
        "available": availability["available"],
        "dry_run": args.dry_run,
        "tasks": [s["task_id"] for s in summaries],
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
