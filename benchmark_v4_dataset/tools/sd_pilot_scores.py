"""Aggregate the SD algorithm pilot into the published scores JSON.

Reads ``runs/sd_v1_algorithm_pilot/raw_results.json`` (written by
``sd_algorithm_pilot.py``) plus the frozen task packages, and writes
``results/source_derived_v1_algorithm_scores.json``.  No probe is re-run and
no answer is re-enumerated.
"""
from __future__ import annotations

import collections
import json
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
DS = KIT / "benchmark_v4_dataset"
SD = DS / "source_derived"
RUN = KIT / "runs" / "sd_v1_algorithm_pilot"
OUT = DS / "results" / "source_derived_v1_algorithm_scores.json"
AS_OF = "2026-11-04"

METHODS = {
    "c_fixed": {
        "name": "A. C-fixed-1.1",
        "discovery": "ast_discovery.discover + rank_and_prune(max_ops=6)",
        "search": "search_relations(mode='exhaustive')",
        "emission": "minimality_only",
        "isolation": "baseline_c._active_ops (frozen C step)",
    },
    "graph": {
        "name": "B. Graph-only (Graph-full)",
        "discovery": "subgraph.build + candidate_selection(max_ops=6)",
        "search": "search_relations(mode='graph', graph_scores)",
        "emission": "minimality_only",
        "isolation": "baseline_c._active_ops (frozen C step)",
    },
    "c0": {
        "name": "C. Role-separated C0",
        "discovery": "ast_discovery.discover + rank_and_prune(max_ops=6)",
        "search": "search_relations_role_separated(budget=16, no hypotheses)",
        "emission": "minimality_only",
        "isolation": "none (offline C0 arm does not run it)",
    },
}


def load(path: Path):
    return json.loads(path.read_text("utf-8"))


def main() -> int:
    recs = load(RUN / "raw_results.json")
    by_case = collections.defaultdict(dict)
    for rec in recs:
        by_case[rec["case_id"]][rec["method"]] = rec

    per_case = []
    for cid in sorted(by_case):
        ref = load(SD / "tasks" / cid / "reference.json")
        task = load(SD / "tasks" / cid / "task.json")
        mask_keys = [k for k, v in ref["inputs"].items() if v["role"] == "masking"]
        row = {
            "case_id": cid,
            "mechanism": task["mechanism"],
            "u_blocks": sorted(u["id"] for u in ref["candidate_universe"]),
            "masking_inputs": mask_keys,
            "methods": {},
        }
        for method in METHODS:
            rec = by_case[cid].get(method)
            if rec is None:
                continue
            row["methods"][method] = {
                "universe_size": len(rec["universe"]),
                "discovered_candidates": rec["discovery"].get("candidate_ops",
                                                              rec["discovery"].get("eligible")),
                "u_covered": rec["discovery"]["u_covered"],
                "u_total": rec["discovery"]["u_total"],
                "u_recall": rec["discovery"]["u_recall"],
                "u_exact": rec["discovery"]["u_exact"],
                "msms_exact": rec["scoring"]["msms_exact"],
                "msms_exact_intervention": rec["scoring"]["msms_exact_intervention"],
                "masking_inputs": rec["scoring"]["masking_inputs"],
                "false_relations": rec["scoring"]["false_relations"],
                "unmatched_sets": rec["scoring"]["unmatched_sets"],
                "mmbs_emitted_sets": rec["scoring"]["mmbs_emitted_sets"],
                "probe_executions": rec["cost"]["probe_executions_algorithm"],
                "wall_seconds": rec["cost"]["wall_seconds_algorithm"],
                "per_input": [
                    {k: d[k] for k in (
                        "input", "hidden_msms", "got_msms_ops",
                        "got_msms_blocks", "got_msms_blocks_identity",
                        "stray_ops", "msms_exact", "intervention_equivalent",
                        "got_mmbs_disabled_sets")}
                    for d in rec["detail"]],
            }
        per_case.append(row)

    totals = {}
    for method in METHODS:
        agg = {"tasks": 0, "masking_inputs": 0, "msms_exact": 0,
               "msms_exact_intervention": 0, "false_relations": 0,
               "unmatched_sets": 0, "probe_executions": 0,
               "wall_seconds": 0.0, "u_exact_tasks": 0, "u_recall_sum": 0.0,
               "cooperative_tasks": 0, "cooperative_msms_exact_tasks": 0}
        for row in per_case:
            m = row["methods"].get(method)
            if m is None:
                continue
            agg["tasks"] += 1
            for k in ("masking_inputs", "msms_exact",
                      "msms_exact_intervention", "false_relations",
                      "unmatched_sets", "probe_executions"):
                agg[k] += m[k]
            agg["wall_seconds"] += m["wall_seconds"]
            agg["u_exact_tasks"] += int(m["u_exact"])
            agg["u_recall_sum"] += m["u_recall"]
            if row["mechanism"] in ("M2_TWO_OPERATION_COOPERATIVE",
                                    "M3_THREE_OPERATION_COOPERATIVE"):
                agg["cooperative_tasks"] += 1
                if m["msms_exact"] == m["masking_inputs"]:
                    agg["cooperative_msms_exact_tasks"] += 1
        agg["u_recall_mean"] = round(agg["u_recall_sum"] / agg["tasks"], 3)
        agg["wall_seconds"] = round(agg["wall_seconds"], 2)
        agg.pop("u_recall_sum")
        totals[method] = agg

    payload = {
        "schema": "mace_source_derived_algorithm_pilot/1",
        "as_of": AS_OF,
        "dataset": ("benchmark_v4_dataset/source_derived, 10 accepted "
                    "SOURCE_DERIVED_CONTROLLED tasks (V4-DEV)"),
        "protocol": {
            "algorithm_visible": [
                "frozen P+ source of the target file",
                "public target operation A (file, line, code)",
                "opaque input grid in1..inN (roles not revealed)"],
            "hidden_from_algorithm": [
                "reference.json (U, MSMS, MMBS, roles)",
                "enumeration.json", "subset execution matrix",
                "block boundaries and line maps"],
            "scoring_view": ("scorer-only; hidden data is read after every "
                             "method has finished"),
            "a_correct": ("A is part of the public task, so every method "
                          "receives the correct A: 10/10 by construction"),
            "u_found": ("hidden block is counted as reached when a kept "
                        "operation's span lies inside it; u_exact requires "
                        "all hidden blocks reached"),
            "msms_exact": ("the family of hidden blocks reached by the "
                           "emitted minimal kept sets equals the hidden "
                           "MSMS family on that masking input and no emitted "
                           "operation falls outside every block"),
            "msms_exact_intervention": ("stricter diagnostic: the emitted "
                                        "kept set's minus-side observation "
                                        "vector over all declared inputs "
                                        "equals the hidden set's"),
            "conditions": ("no method emits an explicit condition; the "
                           "per-input gate (P+ = P- and A executes) is part "
                           "of the frozen intervention protocol, so condition "
                           "handling is IMPLICIT_PER_INPUT, not derived"),
            "probe_count": ("number of probe process launches charged to the "
                            "algorithm; scoring probes are counted separately "
                            "(all zero here because one probe run returns "
                            "every declared input)"),
        },
        "methods": METHODS,
        "full_mace": {
            "status": "NOT_RUN",
            "reason": (
                "scripts/run_full_mace_comparison.call_qwen calls "
                "benchmark_v3_baselines.public_io.load_task(task_id), i.e. "
                "the driver is bound to the v3 public task ids, probes and "
                "fixtures; the SD packages use a different public schema. "
                "Running it would require either rewriting the driver "
                "interface or rebuilding SD tasks in v3 form, both forbidden "
                "this round. No Qwen server is reachable either (local "
                "endpoint down; autodl has ollama + qwen2.5-coder weights but "
                "no running server), and the GPU is not needed for A/B/C."),
            "gpu_used": False,
        },
        "mmbs": {
            "status": "NOT_SEPARABLE",
            "reason": ("reference.json sets mmbs = minimal_masking_sets on "
                       "every input of every case (sd_harness.py:289), so the "
                       "hidden MMBS is not an independent quantity. The "
                       "algorithms' mmbs_ids are minimal *exposed disabled* "
                       "sets and are recorded verbatim, not scored."),
        },
        "per_case": per_case,
        "totals": totals,
        "caveats": [
            "All 10 tasks are RESEARCHER_CONSTRUCTED (track C); a failure "
            "here is a statement about the algorithm on constructed "
            "masking tasks, not about natural upstream defects.",
            "MSMS equality is scored on the finite declared input grid and "
            "the declared block universe only.",
            "A statement inside a researcher block counts as reaching that "
            "block; exact-span agreement is reported separately as "
            "got_msms_blocks_identity.",
            "Wall time is parallelised (12 probe workers) and is not "
            "comparable across machines; probe counts are.",
        ],
        "artifacts": {
            "raw": "runs/sd_v1_algorithm_pilot/raw_results.json",
            "per_case_method": "runs/sd_v1_algorithm_pilot/<case>__<method>.json",
            "adapter": "benchmark_v4_dataset/tools/sd_algorithm_pilot.py",
            "run_log": "runs/sd_v1_algorithm_pilot_run.log",
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   "utf-8")
    print(json.dumps(totals, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
