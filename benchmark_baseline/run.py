"""Run the frozen development baseline on the five v3 dev tasks.

Methods
-------
``direct``     one Qwen call per task, no feedback
``validator``  up to three Qwen calls per task, status-only validator feedback
``ast``        deterministic AST + execution intervention, zero model calls

Full MACE is not run: the original system has no relation-level
``operations`` interface, so it is reported as ``UNSUPPORTED_INTERFACE`` and
no score is assigned.

Every raw response is written before scoring.  Scoring is one pass per saved
submission and never feeds hidden values back to the model.

Usage::

    python -m benchmark_baseline.run direct
    python -m benchmark_baseline.run validator
    python -m benchmark_baseline.run ast
    python -m benchmark_baseline.run summarize
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from benchmark_baseline import ast_method
from benchmark_baseline.freeze import load_frozen
from benchmark_baseline.prompts import feedback_message, messages_for

BASELINE = Path(__file__).resolve().parents[1] / "benchmark_baseline"
RUNS = BASELINE / "runs"
TASKS = [
    "jinja2_bytecode_cache_read",
    "werkzeug_bind_server_name_lower",
    "werkzeug_filestorage_stream_name",
    "werkzeug_get_host_default_empty",
    "werkzeug_secure_filename_ascii_filter",
]
STATUS_NOTE = {
    "WITNESS_VERIFIED": "verified by execution on the submitted witness",
    "FINITE_DOMAIN_EXACT": "verified on the submitted finite input list",
    "PROVEN": "this scorer cannot check proofs",
    "FALSE": "execution contradicted the claim",
    "INVALID": "the claim or input violates the published contract",
    "UNVERIFIED": ("the operation is outside the declared candidate universe "
                   "or the claim cannot be checked by execution"),
    "UNSUPPORTED": "unsupported claim type",
    "DUPLICATE": "duplicate of an earlier claim; no credit",
}


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2,
                               sort_keys=True) + "\n", encoding="utf-8")


def _extract(raw: str) -> Dict[str, Any]:
    from mace.qwen import extract_json
    try:
        value = extract_json(raw)
    except ValueError:
        return {"task_id": None, "claims": [], "_parse_error": "no JSON object"}
    if not isinstance(value, dict):
        return {"task_id": None, "claims": [], "_parse_error": "JSON is not an object"}
    return value


def _submission(task_id: str, parsed: Dict[str, Any],
                submission_id: str) -> Dict[str, Any]:
    claims = parsed.get("claims")
    if not isinstance(claims, list):
        claims = []
    test_gap = parsed.get("test_gap")
    if not isinstance(test_gap, dict):
        test_gap = {"summary": "not supplied", "tests": []}
    return {
        "submission_id": submission_id,
        "task_id": task_id,
        "claims": [claim for claim in claims if isinstance(claim, dict)],
        "test_gap": test_gap,
    }


def _score(submission: Dict[str, Any]) -> Dict[str, Any]:
    from benchmark_real_v3.scoring.engine import score_submission
    return score_submission(submission)


def _all_credited(score: Dict[str, Any]) -> bool:
    counts = score.get("status_counts", {})
    credited = counts.get("WITNESS_VERIFIED", 0) + counts.get("FINITE_DOMAIN_EXACT", 0)
    total = sum(counts.values())
    return total > 0 and credited == total


def _feedback(score: Dict[str, Any]) -> Dict[str, Any]:
    """Status-only rows; never operation lists, observations or hidden data."""
    rows = []
    for claim in score.get("claims", []):
        status = claim.get("status")
        rows.append({
            "index": claim.get("index"),
            "type": claim.get("type"),
            "status": status,
            "note": STATUS_NOTE.get(status, ""),
        })
    return {"claims": rows}


def _resume_task(task_dir: Path) -> tuple[List[Dict[str, Any]], Dict[str, Any]] | None:
    """Reuse a completed task after an interrupted run (no extra model calls)."""
    final_path = task_dir / "final_score.json"
    if not final_path.exists():
        return None
    rounds = []
    for round_dir in sorted(task_dir.glob("round-*")):
        stats_path = round_dir / "stats.json"
        score_path = round_dir / "score.json"
        sub_path = round_dir / "submission.json"
        if not (stats_path.exists() and score_path.exists()):
            return None
        stats = json.loads(stats_path.read_text(encoding="utf-8"))
        score = json.loads(score_path.read_text(encoding="utf-8"))
        submission = (json.loads(sub_path.read_text(encoding="utf-8"))
                      if sub_path.exists() else {"claims": []})
        rounds.append({
            "round": int(round_dir.name.split("-")[-1]),
            "stats": stats,
            "parsed_claims": len(submission.get("claims", [])),
            "status_counts": score.get("status_counts"),
            "credited_relations": score.get("score", {}).get(
                "credited_relations"),
            "raw": str(round_dir / "raw_response.txt"),
        })
    if not rounds:
        return None
    return rounds, json.loads(final_path.read_text(encoding="utf-8"))


def _run_qwen(method: str) -> int:
    frozen = load_frozen()
    model = frozen["model"]
    budget = frozen["budget"][method]
    from scripts.local_qwen_client import LocalQwenClient

    client = LocalQwenClient(
        model["path"], max_new_tokens=model["max_new_tokens"],
        temperature=model["temperature"], seed=model["seed"],
        device=model["device"])
    root = RUNS / method
    started = time.perf_counter()
    summary = {
        "method": method,
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "model": model,
        "budget": budget,
        "tasks": {},
    }
    for task_id in TASKS:
        task_dir = root / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        resumed = _resume_task(task_dir)
        if resumed is not None:
            rounds, final_score = resumed
            summary["tasks"][task_id] = {
                "rounds": rounds,
                "final_status_counts": final_score.get("status_counts"),
                "final_credited_relations": final_score.get("score", {}).get(
                    "credited_relations"),
                "final_claim_credit": final_score.get("score", {}).get(
                    "claim_credit"),
                "model_calls": len(rounds),
                "tokens": {
                    "prompt": sum(
                        r["stats"].get("prompt_tokens", 0) for r in rounds),
                    "completion": sum(
                        r["stats"].get("completion_tokens", 0) for r in rounds),
                    "total": sum(
                        r["stats"].get("total_tokens", 0) for r in rounds),
                },
                "wall_seconds": round(
                    sum(r["stats"].get("wall_seconds", 0) for r in rounds), 3),
                "resumed": True,
            }
            continue
        messages = messages_for(task_id)
        rounds: List[Dict[str, Any]] = []
        final_score = None
        max_rounds = 1 if method == "direct" else budget["model_calls_per_task"]
        for round_index in range(1, max_rounds + 1):
            response = client.chat(messages, purpose=f"{method}:{task_id}",
                                   json_mode=True)
            round_dir = task_dir / f"round-{round_index:02d}"
            round_dir.mkdir(parents=True, exist_ok=True)
            (round_dir / "raw_response.txt").write_text(
                response.content + "\n", encoding="utf-8")
            _write_json(round_dir / "request_messages.json", messages)
            _write_json(round_dir / "stats.json", response.stats)
            parsed = _extract(response.content)
            _write_json(round_dir / "parsed.json", parsed)
            submission = _submission(
                task_id, parsed, f"{method}-{task_id}-r{round_index}")
            _write_json(round_dir / "submission.json", submission)
            score = _score(submission)
            _write_json(round_dir / "score.json", score)
            rounds.append({
                "round": round_index,
                "stats": response.stats,
                "parsed_claims": len(submission["claims"]),
                "status_counts": score.get("status_counts"),
                "credited_relations": score.get("score", {}).get(
                    "credited_relations"),
                "raw": str(round_dir / "raw_response.txt"),
            })
            final_score = score
            if method == "direct" or _all_credited(score) \
                    or not submission["claims"]:
                break
            messages = messages + [
                {"role": "assistant", "content": response.content},
                {"role": "user",
                 "content": feedback_message(_feedback(score), round_index)},
            ]
        (task_dir / "final_submission.json").write_text(
            (task_dir / f"round-{len(rounds):02d}" / "submission.json")
            .read_text(encoding="utf-8"), encoding="utf-8")
        (task_dir / "final_score.json").write_text(
            (task_dir / f"round-{len(rounds):02d}" / "score.json")
            .read_text(encoding="utf-8"), encoding="utf-8")
        summary["tasks"][task_id] = {
            "rounds": rounds,
            "final_status_counts": final_score.get("status_counts"),
            "final_credited_relations": final_score.get("score", {}).get(
                "credited_relations"),
            "final_claim_credit": final_score.get("score", {}).get(
                "claim_credit"),
            "model_calls": len(rounds),
            "tokens": {
                "prompt": sum(r["stats"].get("prompt_tokens", 0) for r in rounds),
                "completion": sum(
                    r["stats"].get("completion_tokens", 0) for r in rounds),
                "total": sum(r["stats"].get("total_tokens", 0) for r in rounds),
            },
            "wall_seconds": round(
                sum(r["stats"].get("wall_seconds", 0) for r in rounds), 3),
        }
    summary["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    summary["model_info"] = client.model_info()
    _write_json(root / "run_summary.json", summary)
    print(json.dumps({
        "method": method,
        "elapsed_seconds": summary["elapsed_seconds"],
        "tasks": {
            task: {
                "calls": row["model_calls"],
                "tokens": row["tokens"]["total"],
                "credited": row["final_credited_relations"],
                "status_counts": row["final_status_counts"],
            }
            for task, row in summary["tasks"].items()
        },
    }, ensure_ascii=False, indent=2))
    return 0


def _run_ast() -> int:
    load_frozen()
    root = RUNS / "ast"
    started = time.perf_counter()
    summary = {
        "method": "ast",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "model_calls_per_task": 0,
        "tasks": {},
    }
    for task_id in TASKS:
        task_started = time.perf_counter()
        task_dir = root / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        saved = task_dir / "score.json"
        saved_work = task_dir / "work.json"
        saved_sub = task_dir / "submission.json"
        if saved.exists() and saved_work.exists() and saved_sub.exists():
            submission = json.loads(saved_sub.read_text(encoding="utf-8"))
            work = json.loads(saved_work.read_text(encoding="utf-8"))
            score = json.loads(saved.read_text(encoding="utf-8"))
            resumed = True
        else:
            payload = ast_method.submission_for(task_id)
            submission = payload["submission"]
            work = payload["work"]
            _write_json(task_dir / "submission.json", submission)
            _write_json(task_dir / "work.json", work)
            score = _score(submission)
            _write_json(task_dir / "score.json", score)
            resumed = False
        submission_sha256 = hashlib.sha256(json.dumps(
            submission, ensure_ascii=False, sort_keys=True).encode(
                "utf-8")).hexdigest()
        summary["tasks"][task_id] = {
            "submission_sha256": submission_sha256,
            "claims": len(submission["claims"]),
            "status_counts": score.get("status_counts"),
            "credited_relations": score.get("score", {}).get(
                "credited_relations"),
            "claim_credit": score.get("score", {}).get("claim_credit"),
            "variant_builds": work["variant_builds"],
            "wall_seconds": round(time.perf_counter() - task_started, 3),
            "resumed": resumed,
        }
    summary["elapsed_seconds"] = round(time.perf_counter() - started, 3)
    _write_json(root / "run_summary.json", summary)
    print(json.dumps({
        "method": "ast",
        "elapsed_seconds": summary["elapsed_seconds"],
        "tasks": {
            task: {
                "claims": row["claims"],
                "credited": row["credited_relations"],
                "status_counts": row["status_counts"],
                "variant_builds": row["variant_builds"],
                "seconds": row["wall_seconds"],
            }
            for task, row in summary["tasks"].items()
        },
    }, ensure_ascii=False, indent=2))
    return 0


def summarize() -> int:
    """Aggregate the saved runs; compare test-gap verdicts with story evidence."""
    from benchmark_real_v3.config import EVIDENCE
    story_root = EVIDENCE / "story_validation"
    verdict_map = {
        "MASKED_EFFECT": "masked",
        "NO_LOCAL_EFFECT": "no_local_effect",
        "ASSERTION_GAP": "assertion_gap",
        "NOT_EXECUTED": "not_executed",
    }
    truth = {}
    for task_id in TASKS:
        path = story_root / f"{task_id}_tests.json"
        if not path.exists():
            continue
        rows = json.loads(path.read_text(encoding="utf-8"))
        truth[task_id] = {
            row["nodeid"]: verdict_map.get(row["classification"], "unknown")
            for row in rows if row.get("nodeid")
        }

    out = {
        "schema": "mace_benchmark_v3_baseline_summary",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "dev_only": True,
        "methods": {},
    }
    for method in ("direct", "validator", "ast"):
        summary_path = RUNS / method / "run_summary.json"
        if not summary_path.exists():
            out["methods"][method] = {"status": "NOT_RUN"}
            continue
        run = json.loads(summary_path.read_text(encoding="utf-8"))
        rows = {}
        for task_id in TASKS:
            score_path = RUNS / method / task_id / "final_score.json"
            if not score_path.exists():
                score_path = RUNS / method / task_id / "score.json"
            score = json.loads(score_path.read_text(encoding="utf-8")) \
                if score_path.exists() else {}
            claims = score.get("claims", [])
            correct_types = [c.get("type") for c in claims
                             if c.get("status") in ("WITNESS_VERIFIED",
                                                    "FINITE_DOMAIN_EXACT")]
            wrong_types = [c.get("type") for c in claims
                           if c.get("status") in ("FALSE", "INVALID",
                                                  "UNVERIFIED", "UNSUPPORTED")]
            gap_rows = []
            if method in ("direct", "validator"):
                sub_path = (RUNS / method / task_id / "final_submission.json")
                if sub_path.exists():
                    sub = json.loads(sub_path.read_text(encoding="utf-8"))
                    answered = {
                        item.get("name"): item.get("verdict")
                        for item in (sub.get("test_gap", {}) or {}).get(
                            "tests", []) if isinstance(item, dict)}
                    truth_task = truth.get(task_id, {})
                    for name, verdict in answered.items():
                        gap_rows.append({
                            "name": name,
                            "verdict": verdict,
                            "truth": truth_task.get(name),
                            "correct": truth_task.get(name) == verdict,
                        })
            rows[task_id] = {
                "claims": len(claims),
                "correct_relation_types": correct_types,
                "wrong_relation_types": wrong_types,
                "credited_relations": score.get("score", {}).get(
                    "credited_relations"),
                "claim_credit": score.get("score", {}).get("claim_credit"),
                "status_counts": score.get("status_counts"),
                "test_gap_answered": len(gap_rows),
                "test_gap_correct": sum(1 for row in gap_rows if row["correct"]),
                "test_gap_rows": gap_rows,
                "model_calls": run["tasks"].get(task_id, {}).get("model_calls"),
                "tokens": run["tasks"].get(task_id, {}).get("tokens"),
                "wall_seconds": run["tasks"].get(task_id, {}).get(
                    "wall_seconds"),
            }
        out["methods"][method] = {
            "elapsed_seconds": run.get("elapsed_seconds"),
            "tasks": rows,
            "totals": {
                "claims": sum(r["claims"] for r in rows.values()),
                "credited_relations": sum(
                    r["credited_relations"] or 0 for r in rows.values()),
                "correct_relation_claims": sum(
                    len(r["correct_relation_types"]) for r in rows.values()),
                "wrong_relation_claims": sum(
                    len(r["wrong_relation_types"]) for r in rows.values()),
                "test_gap_answered": sum(
                    r["test_gap_answered"] for r in rows.values()),
                "test_gap_correct": sum(
                    r["test_gap_correct"] for r in rows.values()),
                "model_calls": sum(
                    r["model_calls"] or 0 for r in rows.values()),
                "tokens": sum(
                    (r["tokens"] or {}).get("total", 0) for r in rows.values()),
                "wall_seconds": round(sum(
                    r["wall_seconds"] or 0 for r in rows.values()), 3),
            },
        }
    out["full_mace"] = {
        "status": "UNSUPPORTED_INTERFACE",
        "score": None,
        "note": ("The original Full MACE has no relation-level operations "
                 "field and no per-relation legal input, so it cannot submit "
                 "this benchmark's claim format.  No 0% is reported."),
    }
    _write_json(RUNS / "baseline_summary.json", out)
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {
            "freeze-check", "direct", "validator", "ast", "summarize"}:
        print("usage: python -m benchmark_baseline.run "
              "freeze-check|direct|validator|ast|summarize")
        return 2
    command = sys.argv[1]
    if command == "freeze-check":
        frozen = load_frozen()
        print(json.dumps({
            "prompt_sha256": frozen["prompt"]["prompt_sha256"],
            "bundle_sha256": frozen["bundle_sha256"],
            "model": frozen["model"]["model"],
            "verified": True,
        }, ensure_ascii=False, indent=2))
        return 0
    if command == "direct":
        return _run_qwen("direct")
    if command == "validator":
        return _run_qwen("validator")
    if command == "ast":
        return _run_ast()
    return summarize()


if __name__ == "__main__":
    raise SystemExit(main())
