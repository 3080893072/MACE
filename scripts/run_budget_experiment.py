"""Same-universe budget experiment: exhaustive vs graph-ordered search.

Both arms enumerate the *same* fixed candidate universe U, use the same public
input grid, the same intervention legality rules and the same minimality
definer.  They differ only in the order in which subsets are evaluated.

For each (task, U, mode) one cold full-budget run is executed and timed per
subset evaluation.  Every smaller budget is the prefix of that same run:
the search is deterministic and a budget only truncates it, so a set is
reported as confirmed at budget ``b`` only when the first ``b`` evaluations
contain the witness and every strict-subset comparison that minimality
requires.  Missing comparisons make a set *undecided*, never confirmed.

Two fixed universes are pre-declared per task and reported as separate
panels; neither is chosen after seeing results:

``U_graph``
    the subgraph top-k candidate set frozen in the previous round
    (``runs/v3_subgraph_ablation/tasks/<task>/candidates.json``).
``U_c``
    Baseline C's effect-pruned universe (``runs/v3_baseline_pilot/...``).

No hidden reference is read and no score is consulted while running.
Usage::

    python -m scripts.run_budget_experiment
    python -m scripts.run_budget_experiment --tasks werkzeug_get_host_default_empty
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import platform
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from benchmark_v3_baselines import graph_search
from benchmark_v3_baselines.baseline_c import PROBES, _active_ops
from benchmark_v3_baselines.config import TASK_IDS
from benchmark_v3_baselines.execution import Executor
from benchmark_v3_baselines.graph_search import (
    EvalRecord, EvidenceStore, ExecutorOracle, subset_key)
from benchmark_v3_baselines.inputs import grid_for
from benchmark_v3_baselines.public_io import load_task

KIT = Path(__file__).resolve().parents[1]
OUT_ROOT = KIT / "runs" / "v3_graph_budget"
GRAPH_RUN = KIT / "runs" / "v3_subgraph_ablation"
PILOT_RUN = KIT / "runs" / "v3_baseline_pilot"
FRACTIONS = [0.10, 0.25, 0.50, 0.75, 1.00]
CODE_FILES = [
    "benchmark_v3_baselines/graph_search.py",
    "benchmark_v3_baselines/execution.py",
    "benchmark_v3_baselines/baseline_c.py",
    "scripts/run_budget_experiment.py",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def budget_limit(fraction: float, total: int) -> int:
    """Ceil-based limit, clipped to [1, total].

    The rounding rule is fixed in advance: never spend less than the stated
    fraction of the full enumeration.
    """
    return max(1, min(total, int(math.ceil(fraction * total - 1e-12))))


class TimedOracle:
    """Executor oracle that records the cost of every evaluation."""

    def __init__(self, executor: Executor, payload: Dict[str, Any]):
        self.inner = ExecutorOracle(executor, payload)
        self.executor = executor
        self.steps: List[Dict[str, Any]] = []
        self.cache_hits = 0

    def evaluate(self, disabled: Sequence[str]):
        before = self.executor.probe_executions
        started = time.perf_counter()
        record = self.inner.evaluate(disabled)
        elapsed = time.perf_counter() - started
        self.steps.append({
            "disabled": list(disabled),
            "status": record.status,
            "masked": record.masked,
            "exposed": record.exposed,
            "probes": self.executor.probe_executions - before,
            "wall_seconds": round(elapsed, 6),
        })
        self.cache_hits = self.inner.cache_hits
        return record


def _prefix_store(trace: Sequence[Dict[str, Any]], limit: int,
                  universe: Sequence[str]) -> EvidenceStore:
    store = EvidenceStore(oracle=None)
    for step in trace[:limit]:
        disabled = tuple(step["disabled"])
        store.records[subset_key(disabled)] = EvalRecord(
            disabled, step["status"], masked=step["masked"],
            exposed=step["exposed"])
        store.order.append(subset_key(disabled))
        store.evaluations += 1
        if step["status"] == "UNKNOWN":
            store.unknown += 1
        elif step["status"] == "INVALID":
            store.invalid += 1
    return store


def _classify(blocked: Sequence[Dict[str, Any]]) -> Tuple[int, int]:
    """Split minimality-blocked sets into (undecided, unknown-evidence)."""
    undecided = unknown = 0
    for item in blocked:
        reasons = [entry.get("reason", "") for entry in item["blocked_by"]]
        if any(reason == "missing" for reason in reasons):
            undecided += 1
        else:
            unknown += 1
    return undecided, unknown


def _first_index(trace: Sequence[Dict[str, Any]],
                 universe: Sequence[str]) -> Dict[str, Any]:
    """First evaluation index at which an MSMS/MMBS is confirmed.

    Confirmation is gated on the full set of strict-subset comparisons, so a
    set whose witness appears early is still undecided until its subsets are
    covered.
    """
    first = {"msms": None, "mmbs": None}
    for size in range(1, len(trace) + 1):
        store = _prefix_store(trace, size, universe)
        if first["msms"] is None:
            found = graph_search.minimal_masked_sets(universe, store)["confirmed"]
            if found:
                first["msms"] = {"index": size, "set": found[0]}
        if first["mmbs"] is None:
            found = graph_search.minimal_exposed_sets(universe, store)["confirmed"]
            if found:
                first["mmbs"] = {"index": size, "set": found[0]}
        if first["msms"] is not None and first["mmbs"] is not None:
            break
    return first


def run_input(executor: Executor, payload: Dict[str, Any],
              universe: Sequence[str], scores: Dict[str, float],
              mode: str) -> Dict[str, Any]:
    started = time.perf_counter()
    probes_before = executor.probe_executions
    executes = executor.a_executes(payload)
    plus = executor.observation([], "plus", payload)
    minus = executor.observation([], "minus", payload)
    executable = (not plus.get("__probe_error__")
                  and not minus.get("__probe_error__"))
    masked_empty = bool(executable and plus.get("outcome") == "return"
                        and plus == minus)
    if not (executes and masked_empty):
        return {"input": payload, "a_executes": executes,
                "masked_empty": masked_empty, "searched": False,
                "setup_probes": executor.probe_executions - probes_before,
                "setup_wall_seconds": round(time.perf_counter() - started, 4)}
    active = _active_ops(executor, payload)
    setup_probes = executor.probe_executions - probes_before
    setup_wall = time.perf_counter() - started
    oracle = TimedOracle(executor, payload)
    result = graph_search.search_relations(
        executor, payload, universe, graph_scores=scores, mode=mode,
        oracle=oracle, budget=None)
    search_wall = time.perf_counter() - started - setup_wall
    first = _first_index(oracle.steps, universe)
    return {
        "input": payload,
        "a_executes": True,
        "masked_empty": True,
        "searched": True,
        "active_ops": active,
        "universe": list(universe),
        "subsets_total": len(oracle.steps),
        "setup_probes": setup_probes,
        "setup_wall_seconds": round(setup_wall, 4),
        "search_wall_seconds": round(search_wall, 4),
        "cache_hits": result["executor_cache_hits"],
        "steps": oracle.steps,
        "first": first,
        "msms_full": result["msms_ids"],
        "mmbs_full": result["mmbs_ids"],
        "evidence_complete": result["evidence_complete"],
    }


def summarize_input(row: Dict[str, Any], limit: int) -> Dict[str, Any]:
    if not row["searched"]:
        return {"searched": False}
    trace = row["steps"]
    store = _prefix_store(trace, limit, row["universe"])
    msms = graph_search.minimal_masked_sets(row["universe"], store)
    mmbs = graph_search.minimal_exposed_sets(row["universe"], store)
    msms_undecided, msms_unknown = _classify(msms["unknown"])
    mmbs_undecided, mmbs_unknown = _classify(mmbs["unknown"])
    probes = row["setup_probes"] + sum(step["probes"] for step in trace[:limit])
    wall = row["setup_wall_seconds"] + sum(
        step["wall_seconds"] for step in trace[:limit])
    first_probes = {}
    for key in ("msms", "mmbs"):
        item = row["first"][key]
        if item is None or item["index"] > limit:
            first_probes[key] = None
        else:
            index = item["index"]
            first_probes[key] = row["setup_probes"] + sum(
                step["probes"] for step in trace[:index])
    return {
        "searched": True,
        "evaluations": limit,
        "subsets_total": row["subsets_total"],
        "complete": limit == row["subsets_total"],
        "confirmed_msms": len(msms["confirmed"]),
        "confirmed_mmbs": len(mmbs["confirmed"]),
        "undecided_msms": msms_undecided,
        "undecided_mmbs": mmbs_undecided,
        "unknown_msms": msms_unknown,
        "unknown_mmbs": mmbs_unknown,
        "probes": probes,
        "wall_seconds": round(wall, 4),
        "first_msms_probes": first_probes["msms"],
        "first_mmbs_probes": first_probes["mmbs"],
        "msms": msms["confirmed"],
        "mmbs": mmbs["confirmed"],
    }


def derive(row: Dict[str, Any], fractions: Sequence[float]) -> List[Dict[str, Any]]:
    if not row["searched"]:
        return []
    total = row["subsets_total"]
    out = []
    for fraction in fractions:
        limit = budget_limit(fraction, total)
        metrics = summarize_input(row, limit)
        metrics["fraction"] = fraction
        metrics["limit"] = limit
        out.append(metrics)
    return out


def _aggregate(rows: List[Dict[str, Any]], fraction: float) -> Dict[str, Any]:
    entries = [entry for row in rows for entry in row.get("budget", [])
               if abs(entry["fraction"] - fraction) < 1e-9]
    if not entries:
        return {}
    first_ms = [e["first_msms_probes"] for e in entries
                if e["first_msms_probes"] is not None]
    first_mm = [e["first_mmbs_probes"] for e in entries
                if e["first_mmbs_probes"] is not None]
    return {
        "fraction": fraction,
        "limit_min": min(e["limit"] for e in entries),
        "limit_max": max(e["limit"] for e in entries),
        "confirmed_msms": sum(e["confirmed_msms"] for e in entries),
        "confirmed_mmbs": sum(e["confirmed_mmbs"] for e in entries),
        "undecided_msms": sum(e["undecided_msms"] for e in entries),
        "undecided_mmbs": sum(e["undecided_mmbs"] for e in entries),
        "unknown_msms": sum(e["unknown_msms"] for e in entries),
        "unknown_mmbs": sum(e["unknown_mmbs"] for e in entries),
        "probes": sum(e["probes"] for e in entries),
        "wall_seconds": round(sum(e["wall_seconds"] for e in entries), 3),
        "complete_inputs": sum(1 for e in entries if e["complete"]),
        "inputs": len(entries),
        "first_msms_probes_mean": (round(sum(first_ms) / len(first_ms), 2)
                                   if first_ms else None),
        "first_mmbs_probes_mean": (round(sum(first_mm) / len(first_mm), 2)
                                   if first_mm else None),
    }


def universes(task_id: str) -> Dict[str, List[Dict[str, Any]]]:
    graph = json.loads((GRAPH_RUN / "tasks" / task_id / "candidates.json")
                       .read_text(encoding="utf-8"))
    pilot = json.loads((PILOT_RUN / "tasks" / task_id / "baseline_c" /
                        "baseline_c.json").read_text(encoding="utf-8"))
    return {
        "U_graph": graph["selection"]["ops"],
        "U_c": pilot["universe"],
    }


def main(argv=None) -> int:
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    except Exception:  # noqa: BLE001 - non-reconfigurable stream
        pass
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", nargs="*", choices=TASK_IDS,
                        default=TASK_IDS)
    parser.add_argument("--out", type=Path, default=OUT_ROOT)
    args = parser.parse_args(argv)
    out_root = args.out
    out_root.mkdir(parents=True, exist_ok=True)

    config = {
        "experiment": "mace_graph_budget_same_universe",
        "task_ids": list(args.tasks),
        "fractions": FRACTIONS,
        "rounding": "ceil(fraction * 2**|U|), clipped to [1, 2**|U|]",
        "universes": (
            "U_graph = frozen subgraph top-k candidates from "
            "runs/v3_subgraph_ablation; U_c = frozen Baseline C universe. "
            "Both are fixed before any budget run; neither is chosen by "
            "score."),
        "modes": {
            "exhaustive": "subsets by (|D|, D) order",
            "graph": "symmetric frontier ordered by graph score, "
                     "deterministic tie-break by the subset tuple",
        },
        "hidden_data_in_scope": False,
        "model_calls": 0,
        "budget_derivation": (
            "Every budget is the deterministic prefix of one cold "
            "full-budget run; per-subset probes and wall seconds are timed "
            "during that run and summed over the prefix."),
        "code_sha256": {rel: sha256_file(KIT / rel) for rel in CODE_FILES},
        "inputs_sha256": {
            task: sha256_file(PILOT_RUN / "tasks" / task / "baseline_c" /
                              "baseline_c.json") for task in args.tasks},
        "environment": {"python": sys.version.split()[0],
                        "platform": platform.platform(),
                        "cpu_count": None},
    }
    import os
    config["environment"]["cpu_count"] = os.cpu_count()
    (out_root / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")

    summary: Dict[str, Any] = {"tasks": {}, "totals": {}}
    for task_id in args.tasks:
        loaded = load_task(task_id)
        task = loaded["task"]
        inputs = grid_for(task_id)
        per_task: Dict[str, Any] = {}
        for panel, ops in universes(task_id).items():
            ids = sorted(op["id"] for op in ops)
            scores = {op["id"]: float(op.get("graph_score", 0.0))
                      for op in ops}
            per_task[panel] = {"universe": ids, "modes": {}}
            for mode in ("exhaustive", "graph"):
                executor = Executor(task_id, task["project_id"],
                                    PROBES[task_id],
                                    task["target_operation"],
                                    f"budget_{panel}_{mode}_{task_id}")
                executor.set_universe(ops)
                rows = []
                for payload in inputs:
                    print(f"[budget] {task_id} {panel} {mode} {payload}",
                          flush=True)
                    row = run_input(executor, payload, ids, scores, mode)
                    if row["searched"]:
                        row["budget"] = derive(row, FRACTIONS)
                        row["full_msms"] = row["msms_full"]
                        row["full_mmbs"] = row["mmbs_full"]
                    rows.append(row)
                per_task[panel]["modes"][mode] = {
                    "probe_executions": executor.probe_executions,
                    "variant_builds": len(executor._variants),
                    "inputs": rows,
                    "budget_summary": [
                        _aggregate(rows, fraction) for fraction in FRACTIONS],
                }
        summary["tasks"][task_id] = per_task
        (out_root / "tasks" / task_id).mkdir(parents=True, exist_ok=True)
        (out_root / "tasks" / task_id / "result.json").write_text(
            json.dumps(per_task, ensure_ascii=False, indent=2),
            encoding="utf-8")

    for panel in ("U_graph", "U_c"):
        summary["totals"][panel] = {}
        for mode in ("exhaustive", "graph"):
            summary["totals"][panel][mode] = []
            for fraction in FRACTIONS:
                entries = []
                for task_id in args.tasks:
                    block = summary["tasks"][task_id].get(panel)
                    if not block:
                        continue
                    for row in block["modes"][mode]["inputs"]:
                        for entry in row.get("budget", []):
                            if abs(entry["fraction"] - fraction) < 1e-9:
                                entries.append(entry)
                if not entries:
                    continue
                summary["totals"][panel][mode].append({
                    "fraction": fraction,
                    "confirmed_msms": sum(e["confirmed_msms"] for e in entries),
                    "confirmed_mmbs": sum(e["confirmed_mmbs"] for e in entries),
                    "undecided_msms": sum(e["undecided_msms"] for e in entries),
                    "undecided_mmbs": sum(e["undecided_mmbs"] for e in entries),
                    "unknown_msms": sum(e["unknown_msms"] for e in entries),
                    "unknown_mmbs": sum(e["unknown_mmbs"] for e in entries),
                    "probes": sum(e["probes"] for e in entries),
                    "wall_seconds": round(sum(e["wall_seconds"] for e in entries), 3),
                    "complete_inputs": sum(1 for e in entries if e["complete"]),
                    "inputs": len(entries),
                })
    (out_root / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(summary["totals"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
