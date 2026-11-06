"""Read-only metrics for MACE semantic feedback v1.

The script makes no model call and no executor call.  It compares the saved
feedback run with the historical A/B/C artifacts.  Pilot sets are scored
against the frozen attribution sets; real-task sets are scored against the
C0/Grap-only confirmed sets, not against a hidden reference.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

KIT = Path(__file__).resolve().parents[1]
FEEDBACK = KIT / "runs" / "v3_semantic_feedback_v1" / "results.json"
LIVE = KIT / "runs" / "v3_semantic_relations" / "results_live.json"
DIRECT = (KIT / "runs" / "v3_semantic_relations" / "direct_end_to_end"
          / "rescored" / "results.json")
OUT = KIT / "runs" / "v3_semantic_feedback_v1" / "summary.json"


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _sets(values: Any) -> Set[Tuple[str, ...]]:
    out: Set[Tuple[str, ...]] = set()
    if not isinstance(values, list):
        return out
    for item in values:
        if isinstance(item, (list, tuple)):
            out.add(tuple(sorted(map(str, item))))
    return out


def _pilot_truth(live: Dict[str, Any], task_id: str) -> Dict[str, Set[Tuple[str, ...]]]:
    truth = live["tasks"][task_id]["truth"]
    absorber: Set[Tuple[str, ...]] = set()
    coexisting: Set[Tuple[str, ...]] = set()
    for case in truth.values():
        for item in case.get("absorber_sets", []) or []:
            absorber.add(tuple(sorted(item)))
        for item in case.get("coexisting_unmasking_sets", []) or []:
            coexisting.add(tuple(sorted(item)))
    return {"msms": absorber, "mmbs": coexisting}


def _real_reference(live: Dict[str, Any], task_id: str) -> Dict[str, Set[Tuple[str, ...]]]:
    arm = live["tasks"][task_id]["summaries"]["A_graph"]
    return {"msms": _sets(arm.get("msms_relations")),
            "mmbs": _sets(arm.get("mmbs_relations"))}


def _candidate_set(candidate: Dict[str, Any]) -> Tuple[str, ...]:
    names = candidate.get("verification", {}).get("names")
    if names:
        return tuple(sorted(names))
    return tuple(sorted(op["id"] for op in candidate.get("ops") or []))


def _candidate_metrics(candidates: Sequence[Dict[str, Any]],
                       reference: Dict[str, Set[Tuple[str, ...]]],
                       kind: str) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    for role in ("msms", "mmbs"):
        rows = [c for c in candidates if c.get("role") == role
                and c.get("status") == "mapped"]
        predicted = {_candidate_set(c) for c in rows}
        matched = predicted & reference[role]
        confirmed = {_candidate_set(c) for c in rows
                     if c.get("verification", {}).get("status") in
                     ("VERIFIED", "SET_CONFIRMED")}
        exact = sum(
            1 for c in rows
            if (c.get("verification", {}).get("condition") or {}).get("exact"))
        false_accept = sum(
            1 for c in rows
            if (c.get("verification", {}).get("condition") or {})
            .get("false_accept"))
        false_reject = sum(
            1 for c in rows
            if (c.get("verification", {}).get("condition") or {})
            .get("false_reject"))
        out[role] = {
            "candidates": len(rows),
            "unique_sets": len(predicted),
            "set_correct": len(matched),
            "confirmed": len(confirmed),
            "set_precision": round(len(matched) / len(predicted), 3)
                            if predicted else None,
            "set_recall": round(len(matched) / len(reference[role]), 3)
                          if reference[role] else None,
            "condition_exact": exact,
            "false_accept_candidates": false_accept,
            "false_reject_candidates": false_reject,
            "correct_relations": sum(
                1 for c in rows
                if _candidate_set(c) in reference[role]
                and c.get("verification", {}).get("status") in
                ("VERIFIED", "SET_CONFIRMED")),
        }
    return out


def _arm_metrics(summary: Any) -> Dict[str, Any]:
    if not summary:
        return {}
    return {k: summary.get(k) for k in (
        "universe_size", "inputs_searched", "evaluations", "complete_inputs",
        "first_msms_mean", "first_mmbs_mean", "probe_executions",
        "msms_relations", "mmbs_relations", "hypothesis_witness",
        "hypothesis_probed")}


def _cost(record: Dict[str, Any]) -> Dict[str, Any]:
    total = {"prompt_tokens": 0, "completion_tokens": 0, "wall_seconds": 0.0}
    calls = []
    for label in ("initial", "correction"):
        call = record.get(label)
        if not call:
            continue
        model = call["model"]
        stats = model.get("stats") or {}
        prompt = int(stats.get("prompt_tokens") or 0)
        completion = int(stats.get("completion_tokens") or 0)
        wall = float(model.get("wall_seconds") or 0)
        total["prompt_tokens"] += prompt
        total["completion_tokens"] += completion
        total["wall_seconds"] += wall
        calls.append({"label": label, "prompt_tokens": prompt,
                      "completion_tokens": completion,
                      "wall_seconds": wall,
                      "error": model.get("error")})
    total["total_tokens"] = total["prompt_tokens"] + total["completion_tokens"]
    total["calls"] = calls
    return total


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--feedback", type=Path, default=FEEDBACK)
    parser.add_argument("--out", type=Path, default=OUT)
    args = parser.parse_args(argv)
    feedback = _load(args.feedback)
    live = _load(LIVE)
    direct = _load(DIRECT) if DIRECT.exists() else {"tasks": {}}

    tasks: Dict[str, Any] = {}
    total_cost = {"prompt_tokens": 0, "completion_tokens": 0,
                  "wall_seconds": 0.0, "calls": 0}
    total_probes = {"D_graph": 0, "D_union": 0}
    for task_id, record in feedback["tasks"].items():
        kind = record["kind"]
        reference = (_pilot_truth(live, task_id) if kind == "pilot"
                     else _real_reference(live, task_id))
        candidates = record.get("candidates_final") or []
        metrics = _candidate_metrics(candidates, reference, kind)
        cost = _cost(record)
        total_cost["prompt_tokens"] += cost["prompt_tokens"]
        total_cost["completion_tokens"] += cost["completion_tokens"]
        total_cost["wall_seconds"] += cost["wall_seconds"]
        total_cost["calls"] += len(cost["calls"])
        arms = record.get("arms") or {}
        probes = {key: (arm or {}).get("probe_executions") or 0
                  for key, arm in arms.items()}
        for key in probes:
            total_probes[key] = total_probes.get(key, 0) + probes[key]
        live_task = live["tasks"].get(task_id, {})
        direct_task = (direct.get("tasks", {}).get(task_id) or {}).get("summary")
        tasks[task_id] = {
            "kind": kind,
            "reference_kind": ("frozen attribution sets" if kind == "pilot"
                               else "A_graph confirmed sets"),
            "reference_sizes": {k: len(v) for k, v in reference.items()},
            "cost": cost,
            "candidates": metrics,
            "correction": record.get("metrics"),
            "universes": {
                "U_graph": len(record["universes"]["U_graph"]),
                "U_qwen": len(record["universes"]["U_qwen"]),
                "U_union": len(record["universes"]["U_union"]),
                "control_context": len(record["universes"]["control_context"]),
                "rejected": len(record["universes"]["rejected"]),
            },
            "arms": {key: _arm_metrics(value) for key, value in arms.items()},
            "probes": probes,
            "baselines": {
                "A_graph": _arm_metrics((live_task.get("summaries") or {}).get("A_graph")),
                "B_old_qwen": _arm_metrics((live_task.get("summaries") or {}).get("B_old_qwen")),
                "C_semantic": _arm_metrics((live_task.get("summaries") or {}).get("C_semantic")),
                "direct_qwen": direct_task,
                "C_relation_verification": (
                    [{"status": r.get("status"), "kind": r.get("kind"),
                      "names": r.get("names"),
                      "exact": (r.get("condition") or {}).get("exact")
                      if isinstance(r.get("condition"), dict) else None}
                     for r in live_task.get("relation_verification", [])]
                    if kind == "pilot" else None),
            },
        }

    payload = {
        "schema": "mace-semantic-feedback-summary-v1",
        "feedback_source": str(args.feedback),
        "model": feedback.get("model"),
        "elapsed_seconds": feedback.get("elapsed_seconds"),
        "totals": {
            "cost": total_cost,
            "probes": total_probes,
            "tasks": len(tasks),
        },
        "tasks": tasks,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
