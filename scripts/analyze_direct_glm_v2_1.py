"""Aggregate the Direct GLM v2.1 run.  DEV only reads DEV reference files.

HELDOUT predictions are counted and hashed, never scored: no HELDOUT
reference, enumeration or acceptance file is opened here.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import statistics
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
RES = KIT / "results"
DEV_JSON = RES / "MACE_direct_GLM_v2_1_dev.json"
HELD_JSON = RES / "MACE_direct_GLM_v2_1_heldout_predictions.json"
PER_TASK = RES / "MACE_direct_GLM_v2_1_per_task.csv"
EFF = RES / "MACE_direct_GLM_v2_1_efficiency.csv"
TABLES = RES / "MACE_direct_GLM_v2_1_paper_tables.csv"
CONFIG = RES / "MACE_direct_GLM_v2_1_config.json"
QWEN = RES / "MACE_direct_vs_full.json"
V21 = KIT / "benchmark_v4_dataset" / "source_derived_v2_1"

DEV_TASKS = sorted(p.stem for p in (V21 / "cases").glob("*.json"))
HELD_TASKS = sorted(p.stem for p in (V21 / "heldout" / "cases").glob("*.json"))


def load(p):
    return json.load(io.open(p, encoding="utf-8"))


def sha_file(p):
    h = hashlib.sha256()
    with open(p, "rb") as fh:
        for c in iter(lambda: fh.read(1 << 20), b""):
            h.update(c)
    return h.hexdigest()


dev = load(DEV_JSON)
held = load(HELD_JSON)
dtasks = dev.get("tasks", {})
htasks = held.get("tasks", {})


def pctl(vals, q):
    vals = sorted(v for v in vals if v is not None)
    if not vals:
        return None
    if len(vals) == 1:
        return vals[0]
    k = (len(vals) - 1) * q
    lo, hi = int(k), min(int(k) + 1, len(vals) - 1)
    return round(vals[lo] + (vals[hi] - vals[lo]) * (k - lo), 3)


def context_limited(rec):
    pt = rec.get("prompt_tokens") or 0
    chars = rec.get("prompt_chars") or 0
    return bool(pt and chars / pt > 7.0)


def status_of(rec):
    if not rec.get("call", {}).get("ok"):
        return "TIMEOUT_OR_ERROR"
    if rec.get("parse_error") or not (rec.get("call") or {}).get("raw_response"):
        return "FORMAT_ERROR"
    return "OK"


def failure_type(rec, score):
    """Semantic failure label; prompt truncation is reported separately."""
    if status_of(rec) != "OK":
        return "FORMAT_ERROR"
    got = [tuple(x) for x in score.get("got_msms_blocks") or []]
    want = [tuple(x) for x in score.get("hidden_msms") or []]
    stray = score.get("stray_ops") or []
    mech = rec.get("mechanism", "")
    gs, ws = set(got), set(want)
    if not gs and not stray:
        return "CANDIDATE_OMISSION"
    if not (gs & ws):
        return "WRONG_RELATION"
    if ws <= gs:
        extra = gs - ws
        if not extra:
            return "STRAY_OPERATION"
        if all(not e for e in extra):
            return "EMPTY_SET_NOISE"
        if mech.startswith(("M2", "M3")):
            return "WRONG_COOPERATION"
        return "EXTRA_SET"
    if gs < ws:
        return "INCOMPLETE_SETS"
    if mech.startswith(("M2", "M3")):
        return "WRONG_COOPERATION"
    if mech.startswith("M4"):
        return "WRONG_ALTERNATIVE"
    return "WRONG_RELATION"


rows = []
failures = []
mech = {}
better_equal = {}
for cid in DEV_TASKS:
    rec = dtasks.get(cid)
    if rec is None:
        rows.append({"task_id": cid, "mechanism": "", "status": "INCOMPLETE",
                     "masking_inputs": 0, "exact": 0, "precision": "",
                     "recall": "", "false_relations": 0, "unmatched_sets": 0,
                     "mmbs_domain": 0, "mmbs_exact": "N/A",
                     "runtime_s": "", "prompt_tokens": "",
                     "completion_tokens": "", "parse_error": "",
                     "context_truncated": ""})
        continue
    sc = rec.get("scoring") or {}
    m = rec["mechanism"].split("_")[0]
    d = mech.setdefault(m, {"mechanism": rec["mechanism"], "tasks": 0,
                            "inputs": 0, "exact": 0, "false": 0,
                            "tasks_exact_all": 0})
    d["tasks"] += 1
    d["inputs"] += sc.get("masking_inputs", 0)
    d["exact"] += sc.get("exact", 0)
    d["false"] += sc.get("false_relations", 0)
    if sc.get("masking_inputs") and sc.get("exact") == sc.get("masking_inputs"):
        d["tasks_exact_all"] += 1
    rows.append({
        "task_id": cid, "mechanism": rec["mechanism"], "status": status_of(rec),
        "runner_status": rec["status"],
        "masking_inputs": sc.get("masking_inputs", 0),
        "exact": sc.get("exact", 0), "precision": sc.get("precision", ""),
        "recall": sc.get("recall", ""),
        "false_relations": sc.get("false_relations", 0),
        "unmatched_sets": sc.get("unmatched_sets", 0),
        "mmbs_domain": sc.get("mmbs_domain", 0),
        "mmbs_exact": "N/A",
        "runtime_s": rec.get("runtime_s", ""),
        "prompt_tokens": rec.get("prompt_tokens", ""),
        "completion_tokens": rec.get("completion_tokens", ""),
        "parse_error": rec.get("parse_error") or "",
        "context_truncated": context_limited(rec),
    })
    for item in rec.get("detail") or []:
        s = item["score"]
        if s["msms_exact"]:
            continue
        failures.append({
            "task_id": cid, "mechanism": rec["mechanism"],
            "input": item["public_id"], "input_key": item["input"],
            "expected_msms_blocks": json.dumps(s["hidden_msms"]),
            "predicted_msms_blocks": json.dumps(s["got_msms_blocks"]),
            "stray_ops": json.dumps(s["stray_ops"]),
            "failure_type": failure_type(rec, s),
            "context_truncated": context_limited(rec),
            "evidence_summary": (
                f"sets={len(rec.get('parsed_sets') or [])}; "
                f"rejected={len(rec.get('rejected') or [])}; "
                f"parse_error={rec.get('parse_error')}; "
                f"prompt_tokens={rec.get('prompt_tokens')}; "
                f"prompt_chars={rec.get('prompt_chars')}; "
                f"ctx_trunc={context_limited(rec)}"),
        })

with open(PER_TASK, "w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=list(rows[0]))
    w.writeheader()
    w.writerows(rows)

# ---- matched Direct-Qwen subset (10 formal tasks, same input keys) --------
qwen = load(QWEN)["tasks"]
matched = {"tasks": 0, "inputs": 0, "qwen_exact": 0, "glm_exact": 0,
           "qwen_false": 0, "glm_false": 0,
           "qwen_unmatched": 0, "glm_unmatched": 0,
           "qwen_prompt_tokens": 0, "qwen_completion_tokens": 0,
           "glm_prompt_tokens": 0, "glm_completion_tokens": 0,
           "qwen_wall_s": 0.0, "glm_wall_s": 0.0,
           "per_task": []}
for cid, qrec in qwen.items():
    grec = dtasks.get(cid)
    if grec is None:
        continue
    gdetail = {d["input"]: d for d in grec.get("detail") or []}
    qdetail = {d["input"]: d for d in qrec.get("detail") or []}
    keys = [k for k in qdetail if k in gdetail]
    if not keys:
        continue
    qe = sum(1 for k in keys if qdetail[k]["direct"]["msms_exact"])
    ge = sum(1 for k in keys if gdetail[k]["score"]["msms_exact"])
    matched["tasks"] += 1
    matched["inputs"] += len(keys)
    matched["qwen_exact"] += qe
    matched["glm_exact"] += ge
    matched["qwen_false"] += sum(qdetail[k]["direct"]["false_relations"] for k in keys)
    matched["glm_false"] += sum(gdetail[k]["score"]["false_relations"] for k in keys)
    matched["qwen_unmatched"] += sum(qdetail[k]["direct"]["unmatched_sets"] for k in keys)
    matched["glm_unmatched"] += sum(gdetail[k]["score"]["unmatched_sets"] for k in keys)
    matched["glm_prompt_tokens"] += grec.get("prompt_tokens") or 0
    matched["glm_completion_tokens"] += grec.get("completion_tokens") or 0
    matched["glm_wall_s"] += grec.get("runtime_s") or 0
    matched["per_task"].append({"task_id": cid, "inputs": len(keys),
                                "qwen_exact": qe, "glm_exact": ge})


# The prior Direct-Qwen run covered exactly these 10 tasks / 15 inputs, so its
# aggregate token and wall totals are the matched-subset totals.
_qsum = load(QWEN).get("totals") or {}
if matched["tasks"] == len(qwen):
    matched["qwen_prompt_tokens"] = _qsum.get("direct_prompt_tokens")
    matched["qwen_completion_tokens"] = _qsum.get("direct_completion_tokens")
    matched["qwen_wall_s"] = _qsum.get("direct_wall_seconds")

# efficiency (per split)
def eff_block(tasks, expected):
    done = [t for t in tasks.values()]
    run = [t.get("runtime_s") for t in done if t.get("runtime_s") is not None]
    pt = [t.get("prompt_tokens") for t in done if t.get("prompt_tokens")]
    ct = [t.get("completion_tokens") for t in done if t.get("completion_tokens")]
    tps = []
    for t in done:
        st = (t.get("call") or {}).get("stats") or {}
        ev = st.get("eval_duration_ns")
        if ev and t.get("completion_tokens"):
            tps.append(t["completion_tokens"] / (ev / 1e9))
    return {
        "tasks_expected": expected, "tasks_completed": len(done),
        "tasks_incomplete": max(0, expected - len(done)),
        "total_runtime_s": round(sum(run), 3),
        "mean_runtime_s": round(sum(run) / len(run), 3) if run else None,
        "p50_runtime_s": pctl(run, 0.5), "p95_runtime_s": pctl(run, 0.95),
        "prompt_tokens": sum(pt), "completion_tokens": sum(ct),
        "tokens_per_second_mean": round(sum(tps) / len(tps), 2) if tps else None,
        "peak_gpu_memory_mib": None,
        "peak_gpu_memory_note": "Ollama API does not expose it; recorded out-of-band",
    }


# nvidia-smi --query-gpu=memory.used on the AutoDL RTX 4090 D (24564 MiB),
# sampled during and after the run; model resident 100% GPU (ollama ps).
PEAK_GPU_MIB = 18909


eff = {"dev": eff_block(dtasks, len(DEV_TASKS)),
       "heldout": eff_block(htasks, len(HELD_TASKS))}
for _e in eff.values():
    _e["peak_gpu_memory_mib"] = PEAK_GPU_MIB
    _e["peak_gpu_memory_note"] = (
        "nvidia-smi memory.used peak on AutoDL RTX 4090 D 24564 MiB; "
        "model resident, 100% GPU")
with open(EFF, "w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["split", "tasks_expected", "tasks_completed", "tasks_incomplete",
                "total_runtime_s", "mean_runtime_s", "p50_runtime_s",
                "p95_runtime_s", "prompt_tokens", "completion_tokens",
                "tokens_per_second_mean", "peak_gpu_memory_mib",
                "gpu_total_mib", "gpu_mem_note"])
    for k in ("dev", "heldout"):
        e = eff[k]
        w.writerow([k, e["tasks_expected"], e["tasks_completed"],
                    e["tasks_incomplete"], e["total_runtime_s"],
                    e["mean_runtime_s"], e["p50_runtime_s"],
                    e["p95_runtime_s"], e["prompt_tokens"],
                    e["completion_tokens"], e["tokens_per_second_mean"],
                    e["peak_gpu_memory_mib"], 24564, e["peak_gpu_memory_note"]])

# fixed HELDOUT subset lists from the v2.1 seal (flags only, no reference)
seal = load(V21 / "heldout" / "seal" / "heldout_v2_1_seal.json")
entries = seal.get("entries", [])
heldout_subsets = {
    "full_heldout": len(entries),
    "project_disjoint": sum(1 for e in entries if e.get("project_disjoint_from_dev")),
    "template_disjoint": sum(1 for e in entries if not e.get("template_seen_in_dev")),
    "both_disjoint": sum(1 for e in entries if e.get("project_disjoint_from_dev")
                         and not e.get("template_seen_in_dev")),
}

# paper tables
n_inputs = sum(r["masking_inputs"] for r in rows)
n_exact = sum(r["exact"] for r in rows)
n_false = sum(r["false_relations"] for r in rows)
n_unmatched = sum(r["unmatched_sets"] for r in rows)
coop_in = sum(r["masking_inputs"] for r in rows if r["mechanism"].startswith(("M2", "M3")))
coop_ex = sum(r["exact"] for r in rows if r["mechanism"].startswith(("M2", "M3")))
alt_in = sum(r["masking_inputs"] for r in rows if r["mechanism"].startswith("M4"))
alt_ex = sum(r["exact"] for r in rows if r["mechanism"].startswith("M4"))
with open(TABLES, "w", encoding="utf-8", newline="") as fh:
    w = csv.writer(fh)
    w.writerow(["table", "key", "value", "note"])
    w.writerow(["A", "Direct_GLM_MSMS_exact", f"{n_exact}/{n_inputs}", "DEV, strict block-family"])
    w.writerow(["A", "Direct_GLM_MMBS_exact", "N/A", "Direct protocol does not request MMBS"])
    w.writerow(["A", "Direct_GLM_false_relations", n_false, "DEV"])
    w.writerow(["A", "Direct_GLM_unmatched_sets", n_unmatched, "DEV"])
    w.writerow(["A", "Direct_GLM_runtime_s", eff["dev"]["total_runtime_s"], "DEV"])
    w.writerow(["A", "Direct_Qwen_MSMS_exact_matched_subset",
                f"{matched['qwen_exact']}/{matched['inputs']}",
                f"same {matched['tasks']} tasks / input keys as Direct GLM"])
    w.writerow(["A", "Direct_GLM_MSMS_exact_matched_subset",
                f"{matched['glm_exact']}/{matched['inputs']}",
                "paired subset, identical prompt template"])
    w.writerow(["A", "Direct_Qwen_false_relations_matched_subset",
                matched["qwen_false"], "paired subset"])
    w.writerow(["A", "Direct_GLM_false_relations_matched_subset",
                matched["glm_false"], "paired subset"])
    w.writerow(["A", "Direct_Qwen_unmatched_sets_matched_subset",
                matched["qwen_unmatched"], "paired subset"])
    w.writerow(["A", "Direct_GLM_unmatched_sets_matched_subset",
                matched["glm_unmatched"], "paired subset"])
    w.writerow(["A", "C0_MSMS_exact", "pending unified", "frozen v2.1 run"])
    w.writerow(["A", "Full_MACE_MSMS_exact", "pending unified", "frozen v2.1 run"])
    for m in sorted(mech):
        d = mech[m]
        w.writerow(["B", f"{m}_tasks", d["tasks"], d["mechanism"]])
        w.writerow(["B", f"{m}_inputs", d["inputs"], ""])
        w.writerow(["B", f"{m}_Direct_GLM_exact", f"{d['exact']}/{d['inputs']}", ""])
        w.writerow(["B", f"{m}_Direct_Qwen_exact", "pending unified", ""])
        w.writerow(["B", f"{m}_C0_exact", "pending unified", ""])
        w.writerow(["B", f"{m}_Full_MACE_exact", "pending unified", ""])
    w.writerow(["C", "total_runtime_s", eff["dev"]["total_runtime_s"], "DEV 25 tasks"])
    w.writerow(["C", "mean_runtime_s", eff["dev"]["mean_runtime_s"], ""])
    w.writerow(["C", "p50_runtime_s", eff["dev"]["p50_runtime_s"], ""])
    w.writerow(["C", "p95_runtime_s", eff["dev"]["p95_runtime_s"], ""])
    w.writerow(["C", "prompt_tokens", eff["dev"]["prompt_tokens"], ""])
    w.writerow(["C", "completion_tokens", eff["dev"]["completion_tokens"], ""])
    w.writerow(["C", "tokens_per_second", eff["dev"]["tokens_per_second_mean"], ""])
    w.writerow(["C", "peak_gpu_memory_mib", PEAK_GPU_MIB,
                "nvidia-smi memory.used on RTX 4090 D (24564 MiB)"])
    w.writerow(["C", "matched_10_task_wall_s_glm", round(matched["glm_wall_s"], 2),
                "same 10 tasks as Direct Qwen"])
    w.writerow(["C", "matched_10_task_wall_s_qwen", matched["qwen_wall_s"], ""])
    w.writerow(["C", "matched_10_task_prompt_tokens_glm", matched["glm_prompt_tokens"], ""])
    w.writerow(["C", "matched_10_task_prompt_tokens_qwen", matched["qwen_prompt_tokens"], ""])
    w.writerow(["C", "matched_10_task_completion_tokens_glm", matched["glm_completion_tokens"], ""])
    w.writerow(["C", "matched_10_task_completion_tokens_qwen", matched["qwen_completion_tokens"], ""])
    for f in failures:
        note = f["expected_msms_blocks"] + " -> " + f["predicted_msms_blocks"]
        if f["context_truncated"]:
            note += " [prompt truncated at ctx cap]"
        w.writerow(["D", f"{f['task_id']}:{f['input']}", f["failure_type"],
                    note])
    w.writerow(["E", "heldout_tasks", len(HELD_TASKS), "predictions only, unscored"])
    w.writerow(["E", "heldout_completed", len(htasks), ""])
    w.writerow(["E", "heldout_frozen_sha256", sha_file(HELD_JSON), ""])
    for name, n in heldout_subsets.items():
        w.writerow(["E", name, n, "fixed v2.1 seal flags; unscored"])

config = {
    "schema": "mace-direct-glm-v2.1-config/1",
    "model": dev.get("model"),
    "model_identity": {
        "tag": "glm-4.7-flash:q4_K_M",
        "ollama_model_id": "4475827791a2",
        "manifest_sha256": "e1e233835e36cd0ebaa63cd554eb14c4b2abd50480e11972f348fbe500195d7f",
        "weights_blob_sha256": "9eba2761cf0b88b8bc11a065a7b5b47f1b13ce820e8e492cb1010b450f9ec950",
        "weights_bytes": 19019269280,
        "architecture": "glm4moelite",
        "parameters": "29.9B",
        "quantization": "Q4_K_M",
        "native_context": 202752,
        "thinking_default": True,
        "thinking_used": False,
        "served_total_context": 8192,
        "output_reserved_tokens": 4096,
        "effective_prompt_cap_tokens": 4096,
        "qwen32b_present_on_host": False,
        "qwen32b_deleted": False,
        "qwen32b_note": ("the instance restarted before deployment and its "
                         "model store was empty (12 KB); Qwen 32B was never "
                         "deleted by this run and was not re-downloaded"),
    },
    "hardware": {"gpu": "NVIDIA GeForce RTX 4090 D", "gpu_total_mib": 24564,
                 "host": "AutoDL", "model_placement": "100% GPU (ollama ps)"},
    "timing": {
        "deployment": {
            "ollama_server_start": "2026-11-05T15:14:59+08:00",
            "model_ready": "2026-11-05T15:47:52+08:00",
            "seconds": 1973.0,
            "note": ("includes repeated pull restarts after stall; 19 GB weights "
                     "at roughly 10 MB/s; no model-version switching")
        },
        "dev_eval_seconds": eff["dev"]["total_runtime_s"],
        "heldout_eval_seconds": eff["heldout"]["total_runtime_s"],
        "eval_total_seconds": round(eff["dev"]["total_runtime_s"] + eff["heldout"]["total_runtime_s"], 3),
        "eval_deadline_seconds": 2700,
        "deadline_met": True,
        "note": "smoke tasks are 3 of the 25 DEV tasks and are counted in DEV time",
    },
    "options": dev.get("options"),
    "protocol": dev.get("protocol"),
    "dataset": {"dev_tasks": len(DEV_TASKS), "heldout_tasks": len(HELD_TASKS),
                "dev_completed": len(dtasks), "heldout_completed": len(htasks)},
    "dev_metrics": {
        "masking_inputs": n_inputs, "strict_exact": n_exact,
        "precision": round(sum(r["precision"] for r in rows if r["precision"] != "") / max(1, sum(1 for r in rows if r["precision"] != "")), 4),
        "recall": round(sum(r["recall"] for r in rows if r["recall"] != "") / max(1, sum(1 for r in rows if r["recall"] != "")), 4),
        "false_relations": n_false, "unmatched_sets": n_unmatched,
        "cooperative": {"exact": coop_ex, "inputs": coop_in},
        "alternative": {"exact": alt_ex, "inputs": alt_in},
        "mmbs_exact": None,
        "mmbs_note": "Direct protocol does not request MMBS",
    },
    "by_mechanism": mech,
    "efficiency": eff,
    "matched_direct_qwen": matched,
    "context_truncation": {
        "cap_tokens_observed": 4098,
        "declared_num_ctx": 8192,
        "heuristic": "prompt_chars / prompt_tokens > 7 implies prompt was cut",
        "dev_tasks_affected": [r["task_id"] for r in rows if r["context_truncated"]],
        "dev_tasks_affected_count": sum(1 for r in rows if r["context_truncated"]),
        "dev_failures_on_truncated": sum(1 for f in failures if f["context_truncated"]),
        "dev_failures_total": len(failures),
    },
    "failure_counts": {},
    "hashes": {
        "dev_json": sha_file(DEV_JSON),
        "heldout_predictions": sha_file(HELD_JSON),
        "per_task_csv": sha_file(PER_TASK),
        "efficiency_csv": sha_file(EFF),
        "paper_tables_csv": sha_file(TABLES),
    },
    "heldout_unscored": True,
}
for f in failures:
    config["failure_counts"][f["failure_type"]] = config["failure_counts"].get(f["failure_type"], 0) + 1
CONFIG.write_text(json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
print(json.dumps({"dev": {"exact": n_exact, "inputs": n_inputs,
                          "false": n_false, "unmatched": n_unmatched,
                          "coop": [coop_ex, coop_in], "alt": [alt_ex, alt_in]},
                  "matched_qwen": {k: matched[k] for k in
                                   ("tasks", "inputs", "qwen_exact", "glm_exact")},
                  "context_truncated_dev_tasks": config["context_truncation"]["dev_tasks_affected_count"],
                  "heldout_completed": len(htasks), "failures": len(failures),
                  "failure_counts": config["failure_counts"]}, ensure_ascii=False, indent=1))
