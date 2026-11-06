"""Offline A/B/C/C0/D comparison for the role-separated search (v2).

No GPU, no model call.  Two sources are reused:

* ``runs/v3_full_mace_audit/audit.json`` for the recorded Graph-only (A) and
  old shared-score Full-MACE (B) executions, and for the verified members
  used to build the per-input oracle (D);
* ``runs/v3_full_mace_30min/tasks/<task>/result.json`` for the raw Qwen
  responses already recorded.  They are re-parsed through the new
  hypothesis protocol and gated, but no request is sent.

C and C0 are executed on the real (CPU) probe executor with the same
universe, inputs, budget and intervention semantics as A/B.

Arms
----
A_graph        recorded Graph-only, shared ``edge`` ordering
B_shared_qwen  recorded old Full MACE, Qwen ranks folded into one score map
C_role_qwen    v2 role-separated queues + gating, historical Qwen hypotheses
C0_role_no_hyp v2 role-separated queues, no hypotheses (deterministic control)
D_oracle       v2 queues + per-input verified hypotheses (upper bound; uses
               ground truth and is not a deployable method)
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from benchmark_v3_baselines.baseline_c import PROBES
from benchmark_v3_baselines.config import BUDGET
from benchmark_v3_baselines.execution import Executor
from benchmark_v3_baselines.graph_search import search_relations_role_separated
from benchmark_v3_baselines.inputs import grid_for
from benchmark_v3_baselines.public_io import load_task

from scripts.run_full_mace_comparison import load_universe, parse_hypotheses

KIT = Path(__file__).resolve().parents[1]
AUDIT = KIT / "runs" / "v3_full_mace_audit" / "audit.json"
QWEN_RUN = KIT / "runs" / "v3_full_mace_30min"
DEFAULT_OUT = KIT / "runs" / "v3_role_separated" / "offline_comparison.json"
BUDGET_PER_INPUT = 16


def _payload_key(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True)


def load_audit() -> Dict[str, Any]:
    return json.loads(AUDIT.read_text(encoding="utf-8"))


def qwen_hypotheses(task_id: str,
                    universe: Sequence[str]) -> Optional[Dict[str, Any]]:
    path = QWEN_RUN / "tasks" / task_id / "result.json"
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    raw = record.get("qwen", {}).get("raw_response")
    if not raw:
        return None
    parsed = parse_hypotheses(raw, universe)
    return {
        "format": parsed["format"],
        "msms": parsed["msms"],
        "mmbs": parsed["mmbs"],
        "rejected": parsed["rejected"],
        "raw_response": raw,
        "model": record.get("qwen", {}).get("model"),
        "stats": record.get("qwen", {}).get("stats"),
    }


def recorded_rows(task_audit: Dict[str, Any], arm: str) -> List[Dict[str, Any]]:
    rows = []
    for row in task_audit["replays"][arm]["inputs"]:
        if not row.get("searched"):
            rows.append({"input": row["input"], "searched": False})
            continue
        first = row.get("first") or {}
        rows.append({
            "input": row["input"],
            "searched": True,
            "evaluations": row.get("evaluations"),
            "complete": row.get("complete"),
            "first_msms": first.get("msms"),
            "first_mmbs": first.get("mmbs"),
            "msms_ids": row.get("msms", []),
            "mmbs_ids": row.get("mmbs", []),
            "order": row.get("order", []),
        })
    return rows


def _first_of(result: Dict[str, Any]) -> Dict[str, Any]:
    def entry(value):
        if not value:
            return None
        return {"index": value["evaluations"], "set": value["set"]}
    return {"msms": entry(result["first_msms"]),
            "mmbs": entry(result["first_mmbs"])}


def live_arm(task_id: str, universe_ops: Sequence[Dict[str, Any]], *,
             hypotheses_by_payload: Optional[Dict[str, Dict[str, Any]]] = None,
             budget: int = BUDGET_PER_INPUT) -> Dict[str, Any]:
    loaded = load_task(task_id)
    task = loaded["task"]
    universe = [op["id"] for op in universe_ops]
    inputs = grid_for(task_id, BUDGET["max_inputs"])
    executor = Executor(task_id, task["project_id"], PROBES[task_id],
                        task["target_operation"], f"rs_{task_id}")
    executor.set_universe(list(universe_ops))
    rows: List[Dict[str, Any]] = []
    for payload in inputs:
        executes = executor.a_executes(payload)
        plus = executor.observation([], "plus", payload)
        minus = executor.observation([], "minus", payload)
        executable = (not plus.get("__probe_error__")
                      and not minus.get("__probe_error__"))
        searched = bool(executes and executable
                        and plus.get("outcome") == "return" and plus == minus)
        if not searched:
            rows.append({"input": payload, "searched": False})
            continue
        before = executor.probe_executions
        hypotheses = None
        if hypotheses_by_payload is not None:
            hypotheses = hypotheses_by_payload[_payload_key(payload)]
        result = search_relations_role_separated(
            executor, payload, list(universe), budget=budget,
            hypotheses=hypotheses)
        rows.append({
            "input": payload,
            "searched": True,
            "evaluations": result["evaluations"],
            "complete": result["complete"],
            "first_msms": _first_of(result)["msms"],
            "first_mmbs": _first_of(result)["mmbs"],
            "msms_ids": result["msms_ids"],
            "mmbs_ids": result["mmbs_ids"],
            "order": result["schedule"],
            "queues": result["queues"],
            "unknown_subsets": result["unknown_subsets"],
            "invalid_subsets": result["invalid_subsets"],
            "reused_evidence": result["reused_evidence"],
            "duplicate_probes": result["duplicate_probes"],
            "hypotheses": result["hypotheses"],
            "probes": executor.probe_executions - before,
        })
    return {
        "task": task_id,
        "universe": list(universe),
        "probe_executions": executor.probe_executions,
        "variants": len(executor._variants),
        "inputs": rows,
    }


def oracle_hypotheses(task_audit: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Per-input verified sets from the recorded Graph-only replay."""
    out: Dict[str, Dict[str, Any]] = {}
    for row in task_audit["replays"]["graph"]["inputs"]:
        if not row.get("searched"):
            continue
        first = row.get("first") or {}
        hypotheses = {"msms": [], "mmbs": []}
        if first.get("msms"):
            hypotheses["msms"].append(tuple(first["msms"]["set"]))
        if first.get("mmbs"):
            hypotheses["mmbs"].append(tuple(first["mmbs"]["set"]))
        out[_payload_key(row["input"])] = hypotheses
    return out


def qwen_map_for(task_audit: Dict[str, Any],
                 task_hypotheses: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    hypotheses = {"msms": task_hypotheses["msms"],
                  "mmbs": task_hypotheses["mmbs"]}
    return {_payload_key(row["input"]): hypotheses
            for row in task_audit["replays"]["graph"]["inputs"]}


def _index_of(result_row: Dict[str, Any],
              target: Sequence[str]) -> Optional[int]:
    """1-based evaluation index at which ``target`` was observed."""
    order = result_row.get("order") or []
    target_key = tuple(sorted(target))
    for position, entry in enumerate(order, start=1):
        if entry.get("disabled") is None:
            continue
        if tuple(sorted(entry["disabled"])) == target_key:
            return position
    return None


def _relation_index(result_row: Dict[str, Any], kind: str,
                    target: Sequence[str]) -> Optional[int]:
    first = result_row.get(f"first_{kind}") or {}
    if not first or sorted(first.get("set", [])) != sorted(target):
        return None
    return first.get("index")


def summarize(task_id: str, arms: Dict[str, Dict[str, Any]],
              universe: Sequence[str], truth: Dict[str, Any]) -> Dict[str, Any]:
    summary: Dict[str, Any] = {"task": task_id, "arms": {}}
    for name, arm in arms.items():
        searched = [row for row in arm["inputs"] if row.get("searched")]
        msms_idx = [row["first_msms"]["index"] for row in searched
                    if row.get("first_msms")]
        mmbs_idx = [row["first_mmbs"]["index"] for row in searched
                    if row.get("first_mmbs")]
        unknown = sum(int(row.get("unknown_subsets") or 0)
                      for row in searched)
        invalid = sum(int(row.get("invalid_subsets") or 0)
                      for row in searched)
        duplicate = sum(int(row.get("duplicate_probes") or 0)
                        for row in searched)
        reused = sum(int(row.get("reused_evidence") or 0)
                     for row in searched)
        gates = [row.get("hypotheses") for row in searched
                 if row.get("hypotheses")]
        hits = {role: sum(entry["witness"]
                          for gate in gates
                          for entry in gate["gate"][role])
                for role in ("msms", "mmbs")}
        probed = {role: sum(1 for gate in gates
                            for entry in gate["gate"][role]
                            if entry["status"] != "BUDGET_SKIPPED")
                  for role in ("msms", "mmbs")}
        arm_summary = {
            "inputs_searched": len(searched),
            "evaluations": sum(int(row.get("evaluations") or 0)
                               for row in searched),
            "complete_inputs": sum(1 for row in searched
                                   if row.get("complete")),
            "first_msms_mean": (round(sum(msms_idx) / len(msms_idx), 3)
                                if msms_idx else None),
            "first_msms_values": msms_idx,
            "first_mmbs_mean": (round(sum(mmbs_idx) / len(mmbs_idx), 3)
                                if mmbs_idx else None),
            "first_mmbs_values": mmbs_idx,
            "msms_relations": sorted({tuple(item)
                                      for row in searched
                                      for item in row.get("msms_ids", [])}),
            "mmbs_relations": sorted({tuple(item)
                                      for row in searched
                                      for item in row.get("mmbs_ids", [])}),
            "unknown_subsets": unknown,
            "invalid_subsets": invalid,
            "duplicate_probes": duplicate,
            "reused_evidence": reused,
            "hypothesis_witness": hits,
            "hypothesis_probed": probed,
        }
        arm_summary["msms_relations"] = [list(item) for item
                                         in arm_summary["msms_relations"]]
        arm_summary["mmbs_relations"] = [list(item) for item
                                         in arm_summary["mmbs_relations"]]
        arm_summary["probe_executions"] = arm.get("probe_executions")
        summary["arms"][name] = arm_summary

    # Truth checks: at which evaluation does each arm first observe the
    # verified disabled set that confirms the true relation?
    checks = {}
    for payload_key, entry in truth.items():
        msms_set = entry.get("msms")
        mmbs_set = entry.get("mmbs")
        check = {"input": entry["input"], "true_msms": msms_set,
                 "true_mmbs": mmbs_set, "arms": {}}
        for name, arm in arms.items():
            row = next((item for item in arm["inputs"]
                        if _payload_key(item["input"]) == payload_key
                        and item.get("searched")), None)
            if row is None:
                continue
            arm_check = {}
            if msms_set:
                disabled = [op for op in universe if op not in msms_set]
                arm_check["msms_confirmation_index"] = _relation_index(
                    row, "msms", msms_set)
                arm_check["msms_evidence_index"] = _index_of(row, disabled)
            if mmbs_set:
                arm_check["mmbs_confirmation_index"] = _relation_index(
                    row, "mmbs", mmbs_set)
                arm_check["mmbs_evidence_index"] = _index_of(row, mmbs_set)
            check["arms"][name] = arm_check
        checks[payload_key] = check
    summary["truth_checks"] = checks
    return summary


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--budget", type=int, default=BUDGET_PER_INPUT)
    args = parser.parse_args(argv)
    audit = load_audit()
    output: Dict[str, Any] = {"budget_per_input": args.budget,
                              "source": "audit.json + saved Qwen responses",
                              "tasks": {}}
    for task_id, task_audit in audit["tasks"].items():
        universe = sorted(task_audit["replays"]["graph"]["universe"])
        universe_ops = load_universe(task_id, KIT / "runs" / "v3_baseline_pilot")
        assert sorted(op["id"] for op in universe_ops) == universe, task_id
        print(f"[offline] {task_id}", flush=True)
        arms = {
            "A_graph": {"inputs": recorded_rows(task_audit, "graph"),
                        "probe_executions":
                            task_audit["replays"]["graph"]["probe_executions"]},
            "B_shared_qwen": {
                "inputs": recorded_rows(task_audit, "full_mace"),
                "probe_executions":
                    task_audit["replays"]["full_mace"]["probe_executions"]},
        }
        qwen = qwen_hypotheses(task_id, universe)
        if qwen is not None:
            arms["C_role_qwen"] = live_arm(
                task_id, universe_ops,
                hypotheses_by_payload=qwen_map_for(task_audit, qwen),
                budget=args.budget)
        arms["C0_role_no_hyp"] = live_arm(task_id, universe_ops,
                                          budget=args.budget)
        arms["D_oracle"] = live_arm(
            task_id, universe_ops,
            hypotheses_by_payload=oracle_hypotheses(task_audit),
            budget=args.budget)

        truth = {}
        for row in task_audit["replays"]["graph"]["inputs"]:
            if not row.get("searched"):
                continue
            first = row.get("first") or {}
            truth[_payload_key(row["input"])] = {
                "input": row["input"],
                "msms": (first.get("msms") or {}).get("set"),
                "mmbs": (first.get("mmbs") or {}).get("set"),
            }
        summary = summarize(task_id, arms, universe, truth)
        summary["qwen"] = ({key: qwen[key] for key in
                            ("format", "msms", "mmbs", "rejected",
                             "model", "stats")} if qwen else None)
        output["tasks"][task_id] = {
            "universe": universe,
            "arms": {name: {"input_rows": arm["inputs"],
                            "probe_executions": arm.get("probe_executions"),
                            "variants": arm.get("variants")}
                     for name, arm in arms.items()},
            "summary": summary,
        }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2,
                                   default=str), encoding="utf-8")
    print(f"[offline] wrote {args.out}")
    for task_id, data in output["tasks"].items():
        print(f"\n=== {task_id}")
        for name, arm in data["summary"]["arms"].items():
            print(f"{name:16s} evals={arm['evaluations']:3d} "
                  f"first_msms={arm['first_msms_values']} "
                  f"first_mmbs={arm['first_mmbs_values']} "
                  f"dup={arm['duplicate_probes']} "
                  f"msms={arm['msms_relations']} "
                  f"mmbs={arm['mmbs_relations']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
