"""Summarise the Direct Qwen end-to-end baseline and its strict/normalised scores.

Reads only saved artifacts; makes no model call.  The strict score maps every
proposed operation literally.  The inner-normalised score drops an enclosing
statement when the relation also cites its body; it is a sensitivity check,
not a substitute for the strict result.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Set

KIT = Path(__file__).resolve().parents[1]
BASE = KIT / "runs" / "v3_semantic_relations" / "direct_end_to_end"
LIVE = KIT / "runs" / "v3_semantic_relations" / "results_live.json"
GPU = KIT / "runs" / "v3_semantic_relations" / "gpu_evidence.json"


def _load(path: Path) -> Dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _pilot_truth(path: Path) -> Dict[str, Any]:
    return _load(path)


def _sets(value: Any) -> List[List[str]]:
    if not isinstance(value, list):
        return []
    return [list(map(str, item)) for item in value if isinstance(item, list)]


def _unique_ops(record: Dict[str, Any], key: str = "ops") -> Set[str]:
    out: Set[str] = set()
    for relation in record.get("relations", []):
        if relation.get("status") != "mapped":
            continue
        for op in relation.get(key) or relation.get("ops") or []:
            out.add(str(op["id"]))
    return out


def _sum_strict(record: Dict[str, Any]) -> Dict[str, Any]:
    summary = record["summary"]
    return {k: summary.get(k) for k in (
        "mapped_relations", "rejected_relations", "verified_relations",
        "covered_true_relations", "true_relations", "exact_task",
        "set_confirmed_relations", "not_confirmed_relations",
        "new_op_relations", "normalization", "statuses")}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", type=Path, default=BASE / "summary.json")
    args = parser.parse_args(argv)

    first = _load(BASE / "results.json")
    strict = _load(BASE / "rescored" / "results.json")
    normal = _load(BASE / "normalized_inner" / "results.json")
    live = _load(LIVE)
    gpu = _load(GPU)

    tasks: Dict[str, Any] = {}
    for task_id, record in strict["tasks"].items():
        normal_record = normal["tasks"][task_id]
        stats = record["model_output"].get("stats") or {}
        true_sets: Dict[str, List[List[str]]] = {}
        if record["kind"] == "pilot":
            truth = _load(KIT / "benchmark_pilot" / "attribution.json")
            truth = truth["controlled"][task_id]
            absorber = {tuple(sorted(x)) for case in truth["per_case"]
                        for x in case.get("absorber_sets", [])}
            coexisting = {tuple(sorted(x)) for case in truth["per_case"]
                          for x in case.get("coexisting_unmasking_sets", [])}
            true_sets = {"masking": [list(x) for x in sorted(absorber)],
                         "exposing": [list(x) for x in sorted(coexisting)]}
        proposed = _unique_ops(record, "ops")
        normalized_proposed = _unique_ops(normal_record, "normalized_ops")
        tasks[task_id] = {
            "kind": record["kind"],
            "tokens": {
                "prompt": stats.get("prompt_tokens"),
                "completion": stats.get("completion_tokens"),
                "total": (stats.get("prompt_tokens") or 0)
                         + (stats.get("completion_tokens") or 0),
            },
            "wall_seconds": record["model_output"].get("wall_seconds"),
            "attempt": stats.get("attempt"),
            "strict": _sum_strict(record),
            "inner_normalized": _sum_strict(normal_record),
            "strict_unique_ops": sorted(proposed),
            "normalized_unique_ops": sorted(normalized_proposed),
            "pilot_true_sets": true_sets,
            "raw_relations": len(record["relations"]),
        }

    semantic: Dict[str, Any] = {}
    for task_id, record in live["tasks"].items():
        if record["kind"] == "pilot":
            statuses = [r.get("status") for r in record["relation_verification"]]
            semantic[task_id] = {
                "kind": "pilot",
                "relations": len(statuses),
                "verified": sum(1 for s in statuses if s == "VERIFIED"),
                "statuses": statuses,
            }
        else:
            arm = record["summaries"]["A_graph"]
            semantic[task_id] = {
                "kind": "real_v3",
                "msms_relations": _sets(arm.get("msms_relations")),
                "mmbs_relations": _sets(arm.get("mmbs_relations")),
                "unique_msms_ops": sorted({x for s in _sets(
                    arm.get("msms_relations")) for x in s}),
                "unique_mmbs_ops": sorted({x for s in _sets(
                    arm.get("mmbs_relations")) for x in s}),
            }
    semantic_calls = gpu.get("task_calls", {})
    semantic["cost"] = {
        "prompt_tokens": sum(v.get("prompt_tokens", 0)
                             for v in semantic_calls.values()),
        "completion_tokens": sum(v.get("completion_tokens", 0)
                                 for v in semantic_calls.values()),
        "wall_seconds": sum(v.get("wall_seconds", 0)
                            for v in semantic_calls.values()),
    }

    direct_totals = {
        "calls": len(tasks),
        "prompt_tokens": sum(t["tokens"]["prompt"] or 0
                             for t in tasks.values()),
        "completion_tokens": sum(t["tokens"]["completion"] or 0
                                 for t in tasks.values()),
        "wall_seconds": sum(t["wall_seconds"] or 0 for t in tasks.values()),
    }
    payload = {
        "schema": "mace-direct-qwen-summary-v1",
        "model": strict.get("model"),
        "options": strict.get("options"),
        "note": ("strict = literal AST mapping; inner_normalized = secondary "
                 "sensitivity that keeps the innermost statement when an "
                 "enclosing statement is also cited"),
        "direct": {"tasks": tasks, "totals": direct_totals},
        "semantic_arm": semantic,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
