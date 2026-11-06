"""Four-mode ablation for EXP-1 and the subgraph-guided search prototype.

Modes (all deterministic, no model, no hidden data):

``C-original``
    Frozen C rules and original exhaustive enumeration.  The default
    ``baseline_c.run`` path; its submission is checked against the frozen
    pilot artifact.
``C-fixed``
    Same discovery/enumeration, EXP-1 ``minimality_only`` emission.
``Graph-candidates``
    Graph-selected candidates, EXP-1 emission, original exhaustive
    enumeration.
``Graph-full``
    Graph-selected candidates, EXP-1 emission, graph-ordered three-valued
    search over *all* subsets (no budget pruning).

Scoring is a separate phase after every task/mode has been executed, so no
score can influence the algorithm.  Usage::

    python -m scripts.run_subgraph_ablation
    python -m scripts.run_subgraph_ablation --tasks werkzeug_get_host_default_empty
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List

from benchmark_v3_baselines import baseline_c
from benchmark_v3_baselines.config import (
    BUDGET, PUBLIC, RUN_ROOT, TASK_IDS, TASK_STORY, config_sha256,
    experiment_config)
from benchmark_v3_baselines.public_io import load_task
from benchmark_v3_baselines.subgraph import (
    build as build_subgraph, candidate_selection)

KIT = Path(__file__).resolve().parents[1]
OUT_ROOT = KIT / "runs" / "v3_subgraph_ablation"
MODE_ORDER = ["C-original", "C-fixed", "Graph-candidates", "Graph-full"]
CODE_FILES = [
    "benchmark_v3_baselines/baseline_c.py",
    "benchmark_v3_baselines/execution.py",
    "benchmark_v3_baselines/graph_search.py",
    "benchmark_v3_baselines/subgraph.py",
    "benchmark_v3_baselines/synthetic_cases.py",
    "tests/test_subgraph_search.py",
    "scripts/run_subgraph_ablation.py",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def git(*args: str) -> str:
    try:
        out = subprocess.run(["git", *args], cwd=str(KIT),
                             capture_output=True, text=True, timeout=30)
        return out.stdout.strip()
    except Exception:  # noqa: BLE001 - provenance is best effort
        return "unknown"


def build_config(task_ids: List[str]) -> Dict[str, Any]:
    base = experiment_config()
    task_hashes = {}
    for task_id in task_ids:
        task_path = PUBLIC / "tasks" / task_id / "task.json"
        loaded = load_task(task_id)
        task_hashes[task_id] = {
            "task_json_sha256": sha256_file(task_path),
            "source_sha256": hashlib.sha256(
                loaded["source_text"].encode("utf-8")).hexdigest(),
        }
    return {
        "experiment": "mace_subgraph_search_exp1",
        "release_version": base["release_version"],
        "schema_version": base["schema_version"],
        "git_commit": base["git_commit"],
        "git_branch": git("branch", "--show-current"),
        "git_status_short": git("status", "--short"),
        "task_ids": task_ids,
        "task_story": {task_id: TASK_STORY[task_id] for task_id in task_ids},
        "task_hashes": task_hashes,
        "budget": BUDGET,
        "modes": {
            "C-original": {"emission": "active_filtered",
                           "discovery": "ast_effect_pruned",
                           "search": "exhaustive"},
            "C-fixed": {"emission": "minimality_only",
                        "discovery": "ast_effect_pruned",
                        "search": "exhaustive"},
            "Graph-candidates": {"emission": "minimality_only",
                                 "discovery": "subgraph_topk",
                                 "search": "exhaustive"},
            "Graph-full": {"emission": "minimality_only",
                           "discovery": "subgraph_topk",
                           "search": "graph_ordered_all_subsets"},
        },
        "max_candidate_ops": BUDGET["max_candidate_ops"],
        "search_budget_per_input": None,
        "model_calls": 0,
        "hidden_data_in_scope": False,
        "scoring_phase": "after_all_runs",
        "execution_fix": (
            "Variant directory names now use a digest of the full disabled "
            "set. The frozen naming scheme truncated the sanitized subset "
            "key at 110 characters, so distinct subsets of three or more "
            "operations shared a directory and a cached probe could read "
            "another subset's tree. The fix is applied identically to all "
            "four modes; frozen pilot artifacts are left untouched."),
        "code_sha256": {rel: sha256_file(KIT / rel) for rel in CODE_FILES},
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
            "executable": sys.executable,
            "cpu_count": os.cpu_count(),
        },
    }


def _first(values: List[float]) -> Dict[str, Any]:
    values = [value for value in values if value is not None]
    if not values:
        return {"count": 0, "min": None, "mean": None, "max": None}
    return {"count": len(values), "min": min(values),
            "mean": round(sum(values) / len(values), 3), "max": max(values)}


def summarize(result: Dict[str, Any], wall_seconds: float,
              mode: str) -> Dict[str, Any]:
    masked = [row for row in result["per_input"]
              if row["a_executes"] and row["masked_empty"]]
    metrics = [row["search_metrics"] for row in masked
               if row.get("search_metrics")]
    first_msms = _first([item["first_msms"]["evaluations"]
                         for item in metrics if item.get("first_msms")])
    first_mmbs = _first([item["first_mmbs"]["evaluations"]
                         for item in metrics if item.get("first_mmbs")])
    verified_msms = sum(len(row["msms_ids"]) for row in masked)
    verified_mmbs = sum(len(row["mmbs_ids"]) for row in masked)
    return {
        "mode": mode,
        "universe_size": len(result["universe"]),
        "universe_ids": [op["id"] for op in result["universe"]],
        "emission_mode": result.get("emission_mode", "active_filtered"),
        "filter_stats": result.get("filter_stats"),
        "masked_inputs": len(masked),
        "evaluations": sum(item["evaluations"] for item in metrics),
        "subsets_total": sum(item["subsets_total"] for item in metrics),
        "evidence_complete": all(item.get("evidence_complete", True)
                                 for item in metrics),
        "unknown_subsets": sum(item.get("unknown_subsets", 0)
                               for item in metrics),
        "invalid_subsets": sum(item.get("invalid_subsets", 0)
                               for item in metrics),
        "msms_unknown": sum(len(item.get("msms_unknown", []))
                            for item in metrics),
        "mmbs_unknown": sum(len(item.get("mmbs_unknown", []))
                            for item in metrics),
        "executor_cache_hits": sum(int(item.get("executor_cache_hits") or 0)
                                   for item in metrics),
        "verified_msms": verified_msms,
        "verified_mmbs": verified_mmbs,
        "emitted_claims": len(result["submission"]["claims"]),
        "first_msms_evaluations": first_msms,
        "first_mmbs_evaluations": first_mmbs,
        "probe_executions": result["probe_executions"],
        "variant_builds": result["variant_builds"],
        "wall_seconds": round(wall_seconds, 3),
        "unknowns": result["unknowns"],
        "search": result.get("search"),
    }


def run_mode(task_id: str, mode: str, task_dir: Path,
             selection: Dict[str, Any], graph_scores: Dict[str, float],
             graph_meta: Dict[str, Any]) -> Dict[str, Any]:
    mode_dir = task_dir / mode
    mode_dir.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    if mode == "C-original":
        result = baseline_c.run(task_id, record_diagnostics=True)
    elif mode == "C-fixed":
        result = baseline_c.run(task_id, emission_mode="minimality_only",
                                record_diagnostics=True)
    elif mode == "Graph-candidates":
        result = baseline_c.run(
            task_id, emission_mode="minimality_only",
            candidate_ops=selection["ops"], candidate_source="subgraph",
            search="exhaustive", graph_meta=graph_meta,
            record_diagnostics=True)
    elif mode == "Graph-full":
        result = baseline_c.run(
            task_id, emission_mode="minimality_only",
            candidate_ops=selection["ops"], candidate_source="subgraph",
            search="graph", graph_scores=graph_scores,
            graph_meta=graph_meta, record_diagnostics=True)
    else:
        raise ValueError(mode)
    wall = time.perf_counter() - started
    result["mode"] = mode
    result["wall_seconds"] = round(wall, 3)
    (mode_dir / "result.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (mode_dir / "submission.json").write_text(
        json.dumps(result["submission"], ensure_ascii=False, indent=2),
        encoding="utf-8")
    summary = summarize(result, wall, mode)
    frozen_path = (RUN_ROOT / "tasks" / task_id / "baseline_c" /
                   "submission.json")
    if mode == "C-original" and frozen_path.exists():
        frozen = json.loads(frozen_path.read_text(encoding="utf-8"))
        summary["frozen_submission_identical"] = (
            result["submission"] == frozen)
        summary["frozen_submission_sha256"] = sha256_file(frozen_path)
    summary["submission_sha256"] = sha256_file(mode_dir / "submission.json")
    (mode_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return summary


def score_task(task_id: str, mode: str, task_dir: Path) -> Dict[str, Any]:
    mode_dir = task_dir / mode
    out_path = mode_dir / "score.json"
    completed = subprocess.run(
        [sys.executable, "-m", "benchmark_real_v3.scoring.score",
         str(mode_dir / "submission.json"), "--out", str(out_path)],
        cwd=str(KIT), capture_output=True, text=True, encoding="utf-8",
        errors="replace", timeout=1800)
    if not out_path.exists():
        return {"status": "SCORING_FAILED",
                "stderr_tail": completed.stderr[-4000:]}
    return json.loads(out_path.read_text(encoding="utf-8"))


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", nargs="*", choices=TASK_IDS,
                        default=TASK_IDS)
    parser.add_argument("--modes", nargs="*", choices=MODE_ORDER,
                        default=MODE_ORDER)
    parser.add_argument("--out", type=Path, default=OUT_ROOT)
    parser.add_argument("--skip-score", action="store_true")
    args = parser.parse_args(argv)

    out_root = args.out
    out_root.mkdir(parents=True, exist_ok=True)
    config = build_config(list(args.tasks))
    (out_root / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    (out_root / "config.sha256").write_text(
        config_sha256(config) + "\n", encoding="utf-8")

    mode_summaries: Dict[str, Dict[str, Any]] = {}
    for task_id in args.tasks:
        task_dir = out_root / "tasks" / task_id
        task_dir.mkdir(parents=True, exist_ok=True)
        loaded = load_task(task_id)
        graph = build_subgraph(loaded["task"], loaded["source_text"])
        graph_path = task_dir / "subgraph.json"
        graph_path.write_text(json.dumps(graph, ensure_ascii=False, indent=2),
                              encoding="utf-8")
        selection = candidate_selection(graph, config["max_candidate_ops"])
        graph_scores = {op["id"]: op["graph_score"]
                        for op in selection["ops"]}
        graph_meta = {
            "subgraph_sha256": sha256_file(graph_path),
            "stats": graph["stats"],
            "selection": {key: selection[key]
                          for key in ("eligible", "selected", "truncated",
                                      "omitted")},
            "unknowns": graph["unknowns"],
            "discovery_rule": graph["discovery_rule"],
        }
        (task_dir / "candidates.json").write_text(
            json.dumps({"selection": selection, "graph_scores": graph_scores},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        mode_summaries[task_id] = {}
        for mode in args.modes:
            print(f"[ablation] {task_id} {mode}", flush=True)
            mode_summaries[task_id][mode] = run_mode(
                task_id, mode, task_dir, selection, graph_scores, graph_meta)

    # ---- scoring phase: only after every run completed -------------------
    scores: Dict[str, Dict[str, Any]] = {}
    if not args.skip_score:
        for task_id in args.tasks:
            task_dir = out_root / "tasks" / task_id
            scores[task_id] = {}
            for mode in args.modes:
                print(f"[score] {task_id} {mode}", flush=True)
                result = score_task(task_id, mode, task_dir)
                scores[task_id][mode] = result
                path = task_dir / mode / "score.json"
                if path.exists():
                    (task_dir / mode / "score_summary.json").write_text(
                        json.dumps({
                            "status_counts": result.get("status_counts"),
                            "score": result.get("score"),
                            "scorer_version": result.get("scorer_version"),
                        }, ensure_ascii=False, indent=2), encoding="utf-8")

    def aggregate(mode: str, key: str) -> Any:
        return sum(mode_summaries[task_id][mode].get(key) or 0
                   for task_id in args.tasks)

    totals = {}
    for mode in args.modes:
        totals[mode] = {
            key: aggregate(mode, key) for key in (
                "probe_executions", "variant_builds", "evaluations",
                "subsets_total", "verified_msms", "verified_mmbs",
                "emitted_claims", "unknown_subsets", "invalid_subsets",
                "msms_unknown", "mmbs_unknown", "executor_cache_hits")
        }
        totals[mode]["credited_relations"] = sum(
            (scores.get(task_id, {}).get(mode, {}).get("score", {})
             .get("credited_relations") or 0)
            for task_id in args.tasks)
        totals[mode]["wall_seconds"] = round(sum(
            mode_summaries[task_id][mode]["wall_seconds"]
            for task_id in args.tasks), 3)

    summary = {
        "experiment": "mace_subgraph_search_exp1",
        "release_version": config["release_version"],
        "git_commit": config["git_commit"],
        "git_branch": config["git_branch"],
        "config_sha256": config_sha256(config),
        "modes": args.modes,
        "tasks": {
            task_id: {
                mode: {
                    "summary": mode_summaries[task_id][mode],
                    "score": scores.get(task_id, {}).get(mode, {}),
                }
                for mode in args.modes
            }
            for task_id in args.tasks
        },
        "totals": totals,
        "scoring_phase": "after_all_runs",
        "hidden_data_used_to_modify_logic": False,
        "dev_tuned_warning": (
            "All five tasks are DEV-TUNED.  Credited relations are not "
            "held-out generalization accuracy."),
    }
    (out_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(totals, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
