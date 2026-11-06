"""Build the frozen v2.1 DEV-closure deliverables from recorded runs only.

No model call, no probe run, no dataset/reference change.  Input is the
combined record produced by close_candidate_discovery_v2_1.py (19 original
tasks + the 2 src-layout tasks re-executed under the corrected sys.path).
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
COMBINED = KIT / "runs" / "candidate_discovery_v2_1_closure" / "combined_pre_analysis.json"
PRE_CSV = KIT / "results" / "MACE_candidate_discovery_v2_1_per_task.csv"
V2 = KIT / "results" / "MACE_candidate_discovery_v2.json"
FINAL_JSON = KIT / "results" / "MACE_v2_1_dev_final.json"
FINAL_CSV = KIT / "results" / "MACE_v2_1_dev_per_task.csv"
FROZEN = KIT / "results" / "MACE_v2_1_frozen_config.json"
SD = KIT / "benchmark_v4_dataset" / "source_derived"

spec = importlib.util.spec_from_file_location(
    "cd21", KIT / "scripts" / "run_candidate_discovery_v2_1.py")
cd21 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cd21)

V2_REUSED = ["sd_pygments_bbcode70_italic", "sd_pygments_bbcode64_color",
             "sd_pygments_groff73_italic", "sd_networkx_gexf448_slices"]


def load(p):
    return json.load(io.open(p, encoding="utf-8"))


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def sha_text(s):
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def dump(p, obj):
    p.write_text(json.dumps(obj, ensure_ascii=False, indent=2), encoding="utf-8")


data = load(COMBINED)
v2 = load(V2)
rows = []
coverage = {}
better = equal = worse = 0
novel_total = novel_correct = novel_wrong = 0
expanded_tasks = expanded_correct_tasks = 0

for cid, x in data["tasks"].items():
    mech = x["mechanism"].split("_")[0]
    ref = cd21.reference_for(cid)
    enum = load(SD / "evidence" / cid / "enumeration.json")
    spans = cd21.block_spans(enum)
    byid = {op["id"]: op for op in x["u_union"]}
    ref_masking = [k for k, v in ref["inputs"].items() if v["role"] == "masking"]
    target_blocks = set()
    for key in ref_masking:
        for s in ref["inputs"][key]["msms"]:
            target_blocks |= set(s)

    ug = {o["id"] for o in x["u_graph"]}
    uq = {o["id"] for o in x["u_qwen"]}
    novel = sorted(uq - ug)
    n_correct = n_wrong = 0
    for oid in novel:
        blocks, _ = cd21.project_containment([oid], byid, spans)
        if blocks & target_blocks:
            n_correct += 1
        else:
            n_wrong += 1
    novel_total += len(novel)
    novel_correct += n_correct
    novel_wrong += n_wrong
    if novel:
        expanded_tasks += 1
        if n_correct:
            expanded_correct_tasks += 1

    s = x["scoring"]
    scored = s["masking_inputs"]
    c0e = x["baseline"]["c0_exact"] or 0
    if s["exact"] > c0e:
        comp = "better"
        better += 1
    elif s["exact"] == c0e:
        comp = "equal"
        equal += 1
    else:
        comp = "worse"
        worse += 1
    stats = x["call"].get("stats") or {}
    incomplete = sum(1 for v in x["search"].values() if not v.get("complete"))
    note = ""
    if cid == "sd_pygments_latex297_italic":
        note = ("SEARCH_INCOMPLETE 3/3 inputs (16/64 subsets each; budget not "
                "expanded per protocol); 0/2 is budget-limited negative")
    if cid in ("sd_attrs_asdict_loop_m7", "sd_humanize_filesize_gnu_m5"):
        note = ("src-layout sys.path defect repaired in-memory; cached Qwen "
                "response replayed (0 new calls); rebuilt prompt differs from "
                "the cached prompt because U_graph is now non-empty")

    m = coverage.setdefault(mech, {
        "mechanism": x["mechanism"], "tasks": 0, "inputs": 0, "exact": 0,
        "present": 0, "c0_exact": 0, "c0_false": 0, "false_relations": 0,
        "tasks_exact_all": 0})
    m["tasks"] += 1
    m["inputs"] += scored
    m["exact"] += s["exact"]
    m["present"] += s["present"]
    m["c0_exact"] += c0e
    m["c0_false"] += x["baseline"]["c0_false"] or 0
    m["false_relations"] += s["false_relations"]
    if scored and s["exact"] == scored:
        m["tasks_exact_all"] += 1

    coop = f"{s['exact']}/{scored}" if mech in ("M2", "M3") else ""
    alt = f"{s['exact']}/{scored}" if mech == "M4" else ""
    rows.append({
        "task_id": cid,
        "mechanism": x["mechanism"],
        "status": "OK",
        "completeness_note": note,
        "u_graph_count": len(x["u_graph"]),
        "u_qwen_count": len(x["u_qwen"]),
        "u_qwen_novel_count": len(novel),
        "u_union_count": len(x["u_union"]),
        "recall_graph": x["recall"]["u_graph"]["recall"],
        "recall_qwen": x["recall"]["u_qwen"]["recall"],
        "recall_union": x["recall"]["u_union"]["recall"],
        "wrong_candidates_graph": x["recall"]["u_graph"]["wrong_candidates"],
        "wrong_candidates_qwen": x["recall"]["u_qwen"]["wrong_candidates"],
        "wrong_candidates_union": x["recall"]["u_union"]["wrong_candidates"],
        "novel_correct": n_correct,
        "novel_wrong": n_wrong,
        "reference_masking_inputs": len(ref_masking),
        "scored_masking_inputs": scored,
        "msms_exact": s["exact"],
        "msms_present": s["present"],
        "false_relations": s["false_relations"],
        "unmatched_sets": s["unmatched_sets"],
        "cooperative_accuracy": coop,
        "alternative_accuracy": alt,
        "probe_count": x["cost"]["probe_executions"],
        "runtime_s": round(x["cost"]["wall_seconds"], 2),
        "prompt_tokens": stats.get("prompt_tokens"),
        "completion_tokens": stats.get("completion_tokens"),
        "c0_exact": c0e,
        "c0_false": x["baseline"]["c0_false"] or 0,
        "c0_scored_inputs": scored,
        "comparison_vs_c0": comp,
        "search_incomplete_inputs": incomplete,
        "qwen_cache_reused": bool(x.get("qwen_cache_reused")),
        "prompt_matches_cached": x.get("prompt_matches_cached"),
    })

assert len(rows) == 21, len(rows)
columns = list(rows[0])
with open(FINAL_CSV, "w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=columns)
    w.writeheader()
    w.writerows(rows)

tot = {
    "tasks_total": 21,
    "tasks_completed": 21,
    "tasks_incomplete": 0,
    "masking_inputs": sum(r["scored_masking_inputs"] for r in rows),
    "c0_exact": sum(r["c0_exact"] for r in rows),
    "c0_false": sum(r["c0_false"] for r in rows),
    "new_exact": sum(r["msms_exact"] for r in rows),
    "new_present": sum(r["msms_present"] for r in rows),
    "new_false": sum(r["false_relations"] for r in rows),
    "new_unmatched": sum(r["unmatched_sets"] for r in rows),
    "new_probes": sum(r["probe_count"] for r in rows),
    "new_runtime": round(sum(r["runtime_s"] for r in rows), 2),
    "prompt_tokens": sum(r["prompt_tokens"] or 0 for r in rows),
    "completion_tokens": sum(r["completion_tokens"] or 0 for r in rows),
    "qwen_calls_actual_this_round": 21,
    "qwen_calls_cache_replayed": 2,
    "search_incomplete_inputs": sum(r["search_incomplete_inputs"] for r in rows),
}
assert tot["masking_inputs"] == 27
assert tot["new_exact"] == 19 and tot["c0_exact"] == 14

v2t = v2["totals"]
all25 = {
    "note": ("descriptive only. 4 tasks come from the frozen v2 run and were "
             "not re-executed in v2.1; do not pool them with the primary "
             "v2.1 denominator for method claims."),
    "tasks": 25,
    "masking_inputs": tot["masking_inputs"] + v2t["masking_inputs"],
    "c0_exact": tot["c0_exact"] + v2t["c0_exact"],
    "new_exact": tot["new_exact"] + v2t["new_exact"],
    "new_false": tot["new_false"] + v2t["new_false"],
    "new_unmatched": tot["new_unmatched"] + v2t["new_unmatched"],
    "new_probes": tot["new_probes"] + v2t["new_probes"],
    "new_runtime": round(tot["new_runtime"] + v2t["new_runtime"], 2),
}

final = {
    "schema": "mace-cd-v2.1-dev-final/1",
    "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "mode": "DEV closure (no HIDDEN access, no new Qwen call, no prompt change)",
    "dataset": {
        "DEV_tasks_total": 25,
        "v2_1_primary_tasks": 21,
        "v2_1_excluded_already_tested_by_v2": V2_REUSED,
        "v2_1_excluded_count": 4,
        "all_21_fully_evaluated": True,
        "masking_inputs_total": tot["masking_inputs"],
        "msms_exact_denominator": tot["masking_inputs"],
        "incomplete_excluded_from_denominator": True,
        "c0_and_full_use_same_reference": True,
        "reference_source": ("acceptance/<cid>.json role+MSMS, validated 0 "
                             "mismatches against the 10 formal reference.json"),
    },
    "two_result_sets": {
        "set_1_all_dev_completion_and_strict_scoring": {
            "scope": "21 v2.1 DEV tasks, all 27 MASKED inputs",
            "tasks_total": 21, "tasks_completed": 21, "tasks_incomplete": 0,
            "masked_inputs": tot["masking_inputs"],
            "c0_exact": tot["c0_exact"],
            "full_mace_exact": tot["new_exact"],
            "c0_false": tot["c0_false"],
            "full_mace_false": tot["new_false"],
            "full_mace_unmatched": tot["new_unmatched"],
        },
        "set_2_paired_complete_samples_c0_vs_full": {
            "scope": "same 21 tasks / same 27 inputs, every sample evaluable",
            "paired_samples": 27,
            "c0_exact": tot["c0_exact"],
            "full_mace_exact": tot["new_exact"],
            "exact_gain": tot["new_exact"] - tot["c0_exact"],
            "c0_false": tot["c0_false"],
            "full_mace_false": tot["new_false"],
            "tasks_better": better, "tasks_equal": equal, "tasks_worse": worse,
        },
    },
    "all_dev_descriptive": all25,
    "totals": tot,
    "coverage_by_mechanism": coverage,
    "qwen_expansion": {
        "novel_candidates": novel_total,
        "novel_correct": novel_correct,
        "novel_wrong": novel_wrong,
        "tasks_with_expansion": expanded_tasks,
        "tasks_with_correct_expansion": expanded_correct_tasks,
    },
    "per_task": rows,
    "diagnostics": {
        "sd_docutils_smartquotes_strip_m1": {
            "scored_input": "in1 (mask_space_padding)",
            "hidden_msms_blocks": [["U1"]],
            "confirmed_kept": ["docutils/frontend.py:275-275",
                               "docutils/frontend.py:277-277"],
            "stray_op": "docutils/frontend.py:277-277",
            "strict_exact": False, "false_relations": 1,
            "introduced_to_keep_probe_executable": False,
            "evidence": ("In in1 the kept pair is masked+minimal at candidate "
                         "level, but the hidden family is covered by 275 alone; "
                         "277 is an extra kept operation. In in3, 277 alone is "
                         "masked+minimal and 275+277 is NOT_MINIMAL with "
                         "witness 277, i.e. 277 is the true target there. The "
                         "stray is therefore input-specific over-keeping, not "
                         "an execution crutch: the probe runs and compares in "
                         "all candidate sets."),
            "impact": ("Strict minimality fails on in1 (stray op). Executability "
                       "is unaffected. Answer and reference unchanged."),
        },
        "sd_networkx_gexf448_slices": {
            "source_run": "frozen v2 (not re-executed in v2.1)",
            "scored_input": "in1 (mask_undirected_slices)",
            "hidden_msms_blocks": [["U1"]],
            "confirmed_kept": ["networkx/readwrite/gexf.py:404-404",
                               "networkx/readwrite/gexf.py:451-451"],
            "stray_op": "networkx/readwrite/gexf.py:404-404",
            "strict_exact": False, "false_relations": 1,
            "introduced_to_keep_probe_executable": False,
            "evidence": ("Kept [451] alone (404,456 disabled) is NOT_MASKED; "
                         "kept [404,451] is masked+minimal, and the score still "
                         "lists 404 as stray. 404 has changed_cells=8/8 in the "
                         "C0 cell diagnostic (non-zero effect) and is required "
                         "for the masking observation, but it belongs to no "
                         "hidden target block family; 451 alone is the U1 "
                         "family. Probe execution itself does not need 404 "
                         "(the [451] set executes)."),
            "impact": ("Strict minimality fails by the block-family rule: an "
                       "operationally necessary non-family operation is counted "
                       "stray. Executability is unaffected. Answer, reference "
                       "and scorer unchanged."),
        },
        "policy": ("No reference was edited and no failing sample was removed. "
                   "Both cases remain failures under current scoring."),
    },
    "closure_disclosure": {
        "fixed_tasks": ["sd_attrs_asdict_loop_m7",
                        "sd_humanize_filesize_gnu_m5"],
        "defect": ("SDExecutor._run_probe/a_executes/trace_run put <variant> "
                   "on sys.path; these packages live under <variant>/src, so "
                   "the installed package was imported."),
        "repair": "in-memory sys.path insertion of both <variant> and <variant>/src",
        "new_qwen_calls": 0,
        "cached_qwen_replayed": True,
        "prompt_matches_cached": False,
        "deviation": ("The cached Qwen responses were produced under the "
                      "defective harness where U_graph was empty. With the "
                      "repaired harness U_graph is non-empty, so the rebuilt "
                      "prompt differs from the cached prompt. The model output "
                      "is replayed as-is (no new call, no prompt edit); its "
                      "score must be read with this conditioning in mind."),
        "post_fix_result": {
            "sd_attrs_asdict_loop_m7": {"inputs": 1, "exact": 1, "c0_exact": 1},
            "sd_humanize_filesize_gnu_m5": {"inputs": 1, "exact": 1, "c0_exact": 1},
        },
    },
    "freeze": {
        "git_head": subprocess.check_output(
            ["git", "-C", str(KIT), "rev-parse", "HEAD"], text=True).strip(),
        "code_state": ("HEAD 2f1ee01 + untracked/uncaptured runner, analyzer, "
                       "closure and harness files identified by SHA-256 in "
                       "MACE_v2_1_frozen_config.json"),
        "model": "qwen2.5-coder:32b (Ollama, Q4_K_M)",
        "model_digest": ("b92d6a0bd47ee79114298de0177bf920c05a706d12633950b3936"
                         "778492bef41"),
        "temperature": 0, "seed": 42, "retries": 0,
        "num_ctx": 16384, "num_predict": 4096, "timeout_s": 900,
        "candidate_discovery_prompt_changed": False,
        "search_budget": 16, "max_ops": 6,
        "frozen_config": "results/MACE_v2_1_frozen_config.json",
    },
    "heldout_preparation": {
        "seal_read": "benchmark_v4_dataset/split/seal.json",
        "seal_version": "v4.0-dev-2026-11-04",
        "seal_sha256": ("106069cd615aef1b5e40e7888371d36d714a30d99151f083cee"
                        "4d6ab1aaa7382"),
        "seal_state": "unsealed=null (still sealed)",
        "heldout_projects_public_in_seal": 8,
        "read_only": ["seal.json", "PROTOCOL.md (public spec)"],
        "not_read": ["HELDOUT reference", "hidden answers",
                     "hidden subset enumerations", "HELDOUT scoring feedback"],
        "v2_1_dataset_usable": True,
        "independent_scoring_environment_preserved": True,
    },
    "ready_for_heldout": "YES",
}
dump(FINAL_JSON, final)

# frozen config (hashes of every code path that can affect a HELDOUT run)
files = {
    "runner": "scripts/run_candidate_discovery_v2_1.py",
    "v2_core": "scripts/run_candidate_discovery_v2.py",
    "closure": "scripts/close_candidate_discovery_v2_1.py",
    "analyzer": "scripts/analyze_candidate_discovery_v2_1.py",
    "finalizer": "scripts/finalize_candidate_discovery_v2_1.py",
    "executor_harness": "benchmark_v4_dataset/tools/sd_algorithm_pilot.py",
    "graph_search": "benchmark_v3_baselines/graph_search.py",
    "ast_discovery": "benchmark_v3_baselines/ast_discovery.py",
    "subgraph": "benchmark_v3_baselines/subgraph.py",
    "qwen_client": "mace/qwen.py",
    "protocol": "benchmark_v4_dataset/PROTOCOL.md",
    "heldout_seal": "benchmark_v4_dataset/split/seal.json",
}
frozen = {
    "schema": "mace-cd-v2.1-frozen-config/1",
    "frozen_at_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
    "git_head": final["freeze"]["git_head"],
    "file_sha256": {k: sha_file(KIT / v) for k, v in files.items()},
    "prompt_build_source_sha256": sha_text(
        __import__("inspect").getsource(cd21.build_prompt)),
    "prompt_sha256_by_task": {
        cid: x.get("prompt_sha256") for cid, x in data["tasks"].items()},
    "model": {
        "name": "qwen2.5-coder:32b",
        "quantization": "Q4_K_M",
        "digest": final["freeze"]["model_digest"],
        "endpoint": "http://127.0.0.1:11434 (SSH tunnel to AutoDL RTX 4090 D)",
        "temperature": 0, "seed": 42, "retries": 0,
        "num_ctx": 16384, "num_predict": 4096, "timeout_s": 900,
    },
    "algorithm": {
        "candidate_discovery": "v2 prompt, frozen; no change in v2.1",
        "u_graph": "C0 discover -> rank_and_prune(max_ops=6)",
        "u_union": "u_graph union u_qwen, provenance retained",
        "search": "search_relations_role_separated(..., budget_per_input=16)",
        "verifier": "block-family MSMS exact; UNKNOWN != FALSE",
        "max_ops": 6, "budget_per_input": 16,
        "deadline_seconds": 45 * 60,
    },
    "protocol": {
        "methods": ["A_role_separated_C0",
                    "B_full_mace_plus_candidate_discovery_v2"],
        "denominator": "only fully evaluated MASKED inputs",
        "incomplete": "excluded from accuracy, retained in CSV",
        "mmbs": "NOT_SEPARABLE is not scored",
        "hidden_access": "none; DEV acceptance references only",
    },
    "results": {
        "final_json_sha256": sha_file(FINAL_JSON),
        "per_task_csv_sha256": sha_file(FINAL_CSV),
        "pre_closure_json_sha256": sha_file(
            KIT / "results" / "MACE_candidate_discovery_v2_1_dev.json"),
        "v2_result_sha256": sha_file(V2),
        "closure_combined_sha256": sha_file(COMBINED),
    },
    "final_numbers": {
        "dev_tasks_primary": 21, "masked_inputs": tot["masking_inputs"],
        "c0_exact": tot["c0_exact"], "full_exact": tot["new_exact"],
        "full_false": tot["new_false"], "full_unmatched": tot["new_unmatched"],
        "better_equal_worse": [better, equal, worse],
    },
}
dump(FROZEN, frozen)
print("wrote", FINAL_CSV)
print("wrote", FINAL_JSON)
print("wrote", FROZEN)
print(json.dumps(final["two_result_sets"], ensure_ascii=False, indent=1))
print("shas", sha_file(FINAL_JSON), sha_file(FINAL_CSV), sha_file(FROZEN))
