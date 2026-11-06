"""Offline wiring audit for the Full-MACE Qwen ordering adapter.

No model and no GPU are used.  The script answers three questions:

1. Which search decisions did Qwen actually change, and did every emitted id
   map onto the frozen universe?
2. Was Qwen's advice suppressed by the graph ordering rule?  The executed
   subset order is replayed with a recording oracle (same executor, same U,
   same budget) and the first 20 choices of the Graph-only and Full-MACE
   arms are compared.  The replay is validated against the first
   confirmation indices recorded in the earlier run.
3. Could this searcher deliver a gain at all?  Two upper bounds are measured
   from already verified evidence: an "oracle boost" that boosts exactly the
   verified minimal-set members through the same mechanism, and the
   definition-level earliest index (one evaluation for a single-operation
   MSMS, two for a single-operation MMBS because the empty set is a required
   proper subset).

Every number is derived from evidence produced by real interventions in the
earlier run; the replay performs the same deterministic interventions again
on CPU, which is why the audit can recover the exact execution order.
"""
from __future__ import annotations

import argparse
import itertools
import json
import statistics
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from benchmark_v3_baselines import graph_search
from benchmark_v3_baselines.baseline_c import PROBES
from benchmark_v3_baselines.execution import Executor
from benchmark_v3_baselines.graph_search import ExecutorOracle, subset_key
from benchmark_v3_baselines.public_io import load_task
from scripts.run_full_mace_comparison import (
    BOOST, boost_scores, graph_scores, load_universe)
from scripts.run_budget_experiment import _first_index

KIT = Path(__file__).resolve().parents[1]
RUN_ROOT = KIT / "runs" / "v3_full_mace_30min"
PILOT_ROOT = KIT / "runs" / "v3_baseline_pilot"
BUDGET = 16


class Recorder:
    """ExecutorOracle wrapper that records every evaluated subset."""

    def __init__(self, executor: Executor, payload: Dict[str, Any]):
        self.inner = ExecutorOracle(executor, payload)
        self.executor = executor
        self.steps: List[Dict[str, Any]] = []

    def evaluate(self, disabled: Sequence[str]):
        before = self.executor.probe_executions
        record = self.inner.evaluate(disabled)
        self.steps.append({
            "disabled": list(disabled),
            "status": record.status,
            "masked": record.masked,
            "exposed": record.exposed,
            "probes": self.executor.probe_executions - before,
        })
        return record


def replay(task_id: str, universe: Sequence[Dict[str, Any]],
           scores: Dict[str, float], inputs: Sequence[Dict[str, Any]],
           budget: int, tag: str) -> Dict[str, Any]:
    loaded = load_task(task_id)
    task = loaded["task"]
    ids = sorted(op["id"] for op in universe)
    executor = Executor(task_id, task["project_id"], PROBES[task_id],
                        task["target_operation"], f"audit_{tag}_{task_id}")
    executor.set_universe(universe)
    rows = []
    for payload in inputs:
        executes = executor.a_executes(payload)
        plus = executor.observation([], "plus", payload)
        minus = executor.observation([], "minus", payload)
        executable = (not plus.get("__probe_error__")
                      and not minus.get("__probe_error__"))
        masked_empty = bool(executable and plus.get("outcome") == "return"
                            and plus == minus)
        if not (executes and masked_empty):
            rows.append({"input": payload, "searched": False})
            continue
        recorder = Recorder(executor, payload)
        result = graph_search.search_relations(
            executor, payload, ids, graph_scores=scores, mode="graph",
            budget=budget, oracle=recorder)
        first = _first_index(recorder.steps, ids)
        rows.append({
            "input": payload,
            "searched": True,
            "order": recorder.steps,
            "first": first,
            "msms": result["msms_ids"],
            "mmbs": result["mmbs_ids"],
            "evaluations": result["evaluations"],
            "complete": result["complete"],
        })
    return {
        "task": task_id,
        "universe": ids,
        "scores": scores,
        "probe_executions": executor.probe_executions,
        "inputs": rows,
    }


# ---------------------------------------------------------------- question 1
def mapping_report(task: Dict[str, Any]) -> Dict[str, Any]:
    universe = task["universe"]
    qwen = task["qwen"]
    base = task["graph_scores"]
    boosted = task["boosted_scores"]
    accepted = qwen["accepted_ranks"]
    emitted = sum(len(qwen["parsed"].get(key) or [])
                  for key in ("msms_rank", "mmbs_rank"))
    mapped = sum(len(accepted[key]) for key in ("msms_rank", "mmbs_rank"))
    changed = [op for op in universe
               if abs(boosted.get(op, 0.0) - base.get(op, 0.0)) > 1e-12]
    return {
        "universe_size": len(universe),
        "ids_emitted": emitted,
        "ids_mapped": mapped,
        "ids_ignored": qwen["ignored_ids"],
        "mapping_rate": round(mapped / emitted, 3) if emitted else None,
        "ops_whose_score_changed": len(changed),
        "changed_ops": changed,
        "base_scores": base,
        "boosted_scores": boosted,
        "score_delta": {op: round(boosted.get(op, 0.0) - base.get(op, 0.0), 3)
                        for op in universe},
    }


def static_priority(scores: Dict[str, float],
                    universe: Sequence[str]) -> List[Tuple[str, ...]]:
    subsets = graph_search.all_subsets(universe)
    dynamic = {op: 0.0 for op in universe}
    return sorted(subsets, key=lambda item: (
        graph_search._subset_priority(item, universe, scores, dynamic), item))


def order_effects(task: Dict[str, Any]) -> Dict[str, Any]:
    universe = sorted(task["universe"])
    base_order = static_priority(task["graph_scores"], universe)
    boosted_order = static_priority(task["boosted_scores"], universe)
    first20_base = [list(item) for item in base_order[:20]]
    first20_boosted = [list(item) for item in boosted_order[:20]]
    overlap = len({tuple(item) for item in first20_base}
                  & {tuple(item) for item in first20_boosted})
    divergence = next((i for i, (a, b) in enumerate(
        zip(base_order, boosted_order)) if a != b), None)
    # Role conflation: one score map serves both the MSMS and MMBS side, so a
    # boost moves subsets where the op is kept and where it is disabled.
    conflated = {}
    for op in task["universe"]:
        if abs(task["boosted_scores"].get(op, 0.0)
               - task["graph_scores"].get(op, 0.0)) < 1e-12:
            continue
        kept_side = sum(1 for s in graph_search.all_subsets(universe)
                        if op not in s)
        disabled_side = sum(1 for s in graph_search.all_subsets(universe)
                            if op in s)
        conflated[op] = {"subsets_with_op_kept": kept_side,
                         "subsets_with_op_disabled": disabled_side}
    return {
        "top20_overlap": overlap,
        "first_divergence_index": divergence,
        "top20_graph": first20_base,
        "top20_full_mace": first20_boosted,
        "role_conflation": conflated,
    }


# ---------------------------------------------------------------- question 2
def _first20(row: Dict[str, Any]) -> List[List[str]]:
    return [step["disabled"] for step in row["order"][:20]]


def order_comparison(b: Dict[str, Any], d: Dict[str, Any],
                     recorded: Dict[str, Any]) -> Dict[str, Any]:
    per_input = []
    for rb, rd in zip(b["inputs"], d["inputs"]):
        if not rb.get("searched"):
            continue
        ob = [tuple(item) for item in _first20(rb)]
        od = [tuple(item) for item in _first20(rd)]
        first_diff = next((i for i, (x, y) in enumerate(zip(ob, od))
                           if x != y), None)
        recorded_row = next(
            (row for row in recorded["per_input"]
             if row["input"] == rb["input"]), None)
        rec = (recorded_row or {}).get("search_metrics") or {}
        # _first_index returns {'msms': {'index': ..., 'set': ...}, ...}
        rd_b = {key: (rb["first"][key] or {}).get("index")
                for key in ("msms", "mmbs")}
        rd_d = {key: (rd["first"][key] or {}).get("index")
                for key in ("msms", "mmbs")}
        rec_b = {key: (rec.get(f"first_{key}") or {}).get("evaluations")
                 for key in ("msms", "mmbs")}
        # The recorded Full-MACE row is the D arm; B was not stored in the
        # earlier run, so only the D replay can be validated directly.
        per_input.append({
            "input": rb["input"],
            "first20_overlap": len(set(ob[:16]) & set(od[:16])),
            "first_divergence": first_diff,
            "top20_graph": [list(item) for item in ob],
            "top20_full_mace": [list(item) for item in od],
            "replay_first_graph": rd_b,
            "replay_first_full_mace": rd_d,
            "recorded_first_full_mace": rec_b,
            "replay_matches_recorded": rd_d == rec_b,
        })
    matches = sum(1 for row in per_input if row["replay_matches_recorded"])
    return {
        "inputs": per_input,
        "replay_match_inputs": matches,
        "replay_match_total": len(per_input),
        "mean_first20_overlap": round(statistics.mean(
            row["first20_overlap"] for row in per_input), 2),
        "divergent_inputs": sum(1 for row in per_input
                                if row["first_divergence"] is not None),
    }


# ---------------------------------------------------------------- question 3
def verified_members(rows: Sequence[Dict[str, Any]]) -> Dict[str, List[str]]:
    """Union of verified MSMS/MMBS members, most frequent first."""
    counts: Dict[str, int] = {}
    for row in rows:
        if not row.get("searched"):
            continue
        for kind in ("msms", "mmbs"):
            for item in row[kind]:
                for op in item:
                    counts[op] = counts.get(op, 0) + 1
    ordered = sorted(counts, key=lambda op: (-counts[op], op))
    return {"order": ordered, "counts": counts}


def oracle_scores(base: Dict[str, float],
                  members: Sequence[str]) -> Dict[str, float]:
    return boost_scores(base, {"msms_rank": list(members),
                               "mmbs_rank": list(members)})


def definition_bound(row: Dict[str, Any], universe: Sequence[str]
                     ) -> Dict[str, Any]:
    """Earliest index at which a confirmed relation of this input can exist.

    A single-operation MSMS needs only its own evaluation, so 1.  A
    single-operation MMBS also needs the empty set (a proper subset), so 2.
    Set sizes are taken from the verified sets; larger sets are charged one
    evaluation per required strict subset.
    """
    def bound_for(items: List[List[str]], kind: str) -> Optional[int]:
        if not items:
            return None
        size = min(len(item) for item in items)
        if kind == "msms":
            return 1 if size == 1 else size + 1
        return 2 if size == 1 else size + 2

    return {
        "msms": bound_for(row["msms"], "msms"),
        "mmbs": bound_for(row["mmbs"], "mmbs"),
    }


def summarize_first(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    out = {}
    for kind in ("msms", "mmbs"):
        vals = [row["first"][kind]["index"] for row in rows
                if row.get("searched") and row["first"][kind]]
        out[kind] = {
            "inputs_confirmed": len(vals),
            "mean_first_index": round(statistics.mean(vals), 2) if vals else None,
            "values": vals,
        }
    return out


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", nargs="+", default=[
        "werkzeug_get_host_default_empty",
        "werkzeug_filestorage_stream_name"])
    parser.add_argument("--budget", type=int, default=BUDGET)
    parser.add_argument("--out", type=Path,
                        default=KIT / "runs" / "v3_full_mace_audit")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    audit: Dict[str, Any] = {"budget": args.budget, "tasks": {}}
    for task_id in args.tasks:
        started = time.time()
        record = json.loads((RUN_ROOT / "tasks" / task_id / "result.json")
                            .read_text(encoding="utf-8"))
        universe = load_universe(task_id, PILOT_ROOT)
        inputs = [row["input"] for row in record["full_mace"]["per_input"]]
        base = graph_scores(task_id, universe)
        boosted = record["boosted_scores"]
        print(f"[audit] {task_id} q1", flush=True)
        q1 = mapping_report({"universe": record["universe"], "qwen": record["qwen"],
                             "graph_scores": base,
                             "boosted_scores": boosted})
        q1["static_order"] = order_effects({"universe": record["universe"],
                                            "graph_scores": base,
                                            "boosted_scores": boosted})
        print(f"[audit] {task_id} replay graph-only", flush=True)
        replay_b = replay(task_id, universe, base, inputs, args.budget,
                          "graph")
        print(f"[audit] {task_id} replay full-mace", flush=True)
        replay_d = replay(task_id, universe, boosted, inputs, args.budget,
                          "fullmace")
        print(f"[audit] {task_id} replay oracle", flush=True)
        members = verified_members(replay_b["inputs"])
        oracle = oracle_scores(base, members["order"])
        replay_o = replay(task_id, universe, oracle, inputs, args.budget,
                          "oracle")
        bounds = [definition_bound(row, replay_b["universe"])
                  for row in replay_b["inputs"] if row.get("searched")]
        audit["tasks"][task_id] = {
            "q1_mapping": q1,
            "q2_order": order_comparison(replay_b, replay_d, record["full_mace"]),
            "q3_bounds": {
                "verified_members": members,
                "oracle_scores": oracle,
                "first_graph": summarize_first(replay_b["inputs"]),
                "first_full_mace": summarize_first(replay_d["inputs"]),
                "first_oracle": summarize_first(replay_o["inputs"]),
                "definition_lower_bound": {
                    "msms": min((b["msms"] for b in bounds
                                 if b["msms"] is not None), default=None),
                    "mmbs": min((b["mmbs"] for b in bounds
                                 if b["mmbs"] is not None), default=None),
                    "per_input": bounds,
                },
            },
            "replays": {"graph": replay_b, "full_mace": replay_d,
                        "oracle": replay_o},
            "wall_seconds": round(time.time() - started, 1),
        }
        (args.out / "audit.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"tasks": list(audit["tasks"])}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
