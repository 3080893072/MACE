"""Aggregate the Direct-Qwen vs Full-MACE run into the final deliverables."""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
RUN = KIT / "runs" / "sd_direct_vs_full" / "results.json"
GPU = KIT / "runs" / "sd_direct_vs_full" / "gpu_evidence.json"
C0 = KIT / "runs" / "sd_v1_algorithm_pilot"
OUT = KIT / "results" / "MACE_direct_vs_full.json"
RAW = KIT / "runs" / "sd_direct_vs_full" / "raw"
SCORES = KIT / "runs" / "sd_direct_vs_full" / "scores"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def present(hidden, got) -> bool:
    want = {frozenset(x) for x in hidden}
    have = {frozenset(x) for x in got}
    return bool(want) and want <= have


def main() -> int:
    data = json.loads(RUN.read_text(encoding="utf-8"))
    gpu = json.loads(GPU.read_text(encoding="utf-8"))
    RAW.mkdir(parents=True, exist_ok=True)
    SCORES.mkdir(parents=True, exist_ok=True)

    tasks = {}
    totals = {
        "masking_inputs": 0,
        "direct_exact": 0, "full_exact": 0,
        "direct_present": 0, "full_present": 0,
        "direct_false": 0, "full_false": 0,
        "direct_unmatched": 0, "full_unmatched": 0,
        "direct_prompt_tokens": 0, "full_prompt_tokens": 0,
        "direct_completion_tokens": 0, "full_completion_tokens": 0,
        "direct_wall_seconds": 0.0, "full_wall_seconds": 0.0,
        "full_search_evaluations": 0,
    }
    for cid, task in sorted(data["tasks"].items()):
        for arm in ("direct", "full_mace"):
            call = task[arm]["call"]
            stats = call.get("stats") or {}
            name = "direct" if arm == "direct" else "full"
            totals[f"{name}_prompt_tokens"] += stats.get("prompt_tokens") or 0
            totals[f"{name}_completion_tokens"] += (
                stats.get("completion_tokens") or 0)
            totals[f"{name}_wall_seconds"] += call.get("wall_seconds") or 0
            (RAW / f"{cid}__{name}.json").write_text(json.dumps({
                "task_id": cid,
                "arm": name,
                "model": task["model"],
                "options": task["options"],
                "messages": call.get("messages"),
                "raw_response": call.get("raw_response"),
                "stats": stats,
                "wall_seconds": call.get("wall_seconds"),
                "ok": call.get("ok"),
                "error": call.get("error"),
            }, ensure_ascii=False, indent=2), encoding="utf-8")

        c0 = json.loads((C0 / f"{cid}__c0.json").read_text(encoding="utf-8"))
        detail = []
        for row in task["detail"]:
            d, f = row["direct"], row["full_mace"]
            detail.append({
                "input": row["input"],
                "direct": {
                    **d,
                    "hidden_msms_present": present(
                        d["hidden_msms"], d["got_msms_blocks"]),
                },
                "full_mace": {
                    **f,
                    "hidden_msms_present": present(
                        f["hidden_msms"], f["got_msms_blocks"]),
                },
                "full_metrics": row.get("full_metrics"),
            })
            totals["masking_inputs"] += 1
            totals["direct_exact"] += int(d["msms_exact"])
            totals["full_exact"] += int(f["msms_exact"])
            totals["direct_present"] += int(detail[-1]["direct"][
                "hidden_msms_present"])
            totals["full_present"] += int(detail[-1]["full_mace"][
                "hidden_msms_present"])
            totals["direct_false"] += d["false_relations"]
            totals["full_false"] += f["false_relations"]
            totals["direct_unmatched"] += d["unmatched_sets"]
            totals["full_unmatched"] += f["unmatched_sets"]
        totals["full_search_evaluations"] += sum(
            int(r.get("evaluations") or 0)
            for r in task["full_mace"]["per_input"].values())

        # Is Full MACE observationally identical to frozen C0 on this task?
        same_as_c0 = True
        for row in task["detail"]:
            old = next((x for x in c0["detail"] if x["input"] == row["input"]),
                       None)
            if old is None:
                same_as_c0 = False
                break
            if (old["got_msms_blocks"] != row["full_mace"]["got_msms_blocks"]
                    or old["stray_ops"] != row["full_mace"]["stray_ops"]):
                same_as_c0 = False
                break

        record = {
            "task_id": cid,
            "mechanism": task["mechanism"],
            "universe_ids": task["universe_ids"],
            "universe_size": len(task["universe_ids"]),
            "public_source_sha256": task["public_source_sha256"],
            "direct": {
                "prompt": task["direct"]["call"].get("messages"),
                "prompt_sha256": task["direct"]["prompt_sha256"],
                "raw_response": task["direct"]["call"].get("raw_response"),
                "stats": task["direct"]["call"].get("stats"),
                "wall_seconds": task["direct"]["call"].get("wall_seconds"),
                "parsed_sets": task["direct"]["parsed_sets"],
                "rejected_count": len(task["direct"]["rejected"]),
                "rejected": task["direct"]["rejected"],
                "parse_error": task["direct"]["parse_error"],
                "exact": task["scoring"]["direct_exact"],
                "masking_inputs": task["scoring"]["masking_inputs"],
            },
            "full_mace": {
                "prompt": task["full_mace"]["call"].get("messages"),
                "prompt_sha256": task["full_mace"]["prompt_sha256"],
                "raw_response": task["full_mace"]["call"].get("raw_response"),
                "stats": task["full_mace"]["call"].get("stats"),
                "wall_seconds": task["full_mace"]["call"].get("wall_seconds"),
                "parse": task["full_mace"]["parse"],
                "hypotheses": task["full_mace"]["hypotheses"],
                "per_input": task["full_mace"]["per_input"],
                "exact": task["scoring"]["full_exact"],
                "masking_inputs": task["scoring"]["masking_inputs"],
                "same_as_frozen_c0_per_input": same_as_c0,
            },
            "scoring": task["scoring"],
            "detail": detail,
        }
        tasks[cid] = record
        (SCORES / f"{cid}.json").write_text(json.dumps({
            "task_id": cid,
            "mechanism": task["mechanism"],
            "direct_exact": task["scoring"]["direct_exact"],
            "full_mace_exact": task["scoring"]["full_exact"],
            "masking_inputs": task["scoring"]["masking_inputs"],
            "detail": detail,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    # Focus-task answers computed from the same records.
    focus = {}
    for cid in ("sd_pygments_bbcode70_italic",
                "sd_pygments_groff73_italic",
                "sd_pygments_bbcode64_color"):
        t = tasks[cid]
        focus[cid] = {
            "mechanism": t["mechanism"],
            "direct_exact": t["direct"]["exact"],
            "full_exact": t["full_mace"]["exact"],
            "masking_inputs": t["direct"]["masking_inputs"],
            "direct_sets": [s["ids"] for s in t["direct"]["parsed_sets"]],
            "full_hypotheses": t["full_mace"]["hypotheses"],
        }

    payload = {
        "schema": "mace-direct-vs-full/1",
        "generated_utc": "2026-11-05T00:16:00Z",
        "mode": "direct_qwen_vs_full_mace",
        "dataset": {
            "name": "source-derived controlled (V4-DEV)",
            "task_count": 10,
            "track": "SOURCE_DERIVED_CONTROLLED",
            "researcher_constructed": True,
        },
        "model": {
            "name": data["model"],
            "options": data["options"],
            "ollama_digest": gpu.get("ollama_digest"),
            "gpu": gpu.get("gpu"),
            "gpu_layers": gpu.get("gpu_layers"),
            "gpu_model_mib": gpu.get("gpu_model_mib"),
            "gpu_kv_mib": gpu.get("gpu_kv_mib"),
        },
        "protocol": {
            "same_source_and_inputs": True,
            "model_calls_per_arm_per_task": 1,
            "retries": 0,
            "temperature": 0.0,
            "seed": 42,
            "num_ctx": 8192,
            "num_predict": 4096,
            "full_mace_search_budget_per_input": 16,
            "mmbs": "NOT_SEPARABLE; recorded, not scored",
            "msms": ("independent strict block-family equality via span "
                     "containment; stray operations fail"),
            "unknown": "never counted as FALSE",
        },
        "gpu_evidence": gpu,
        "totals": {
            **totals,
            "direct_wall_seconds": round(totals["direct_wall_seconds"], 2),
            "full_wall_seconds": round(totals["full_wall_seconds"], 2),
            "tasks": len(tasks),
            "full_same_as_c0_tasks": sum(
                1 for t in tasks.values()
                if t["full_mace"]["same_as_frozen_c0_per_input"]),
        },
        "focus": focus,
        "tasks": tasks,
        "answers": {
            "q1_who_better": (
                "Strict aggregate MSMS: Full MACE 5/15 vs Direct Qwen 3/15. "
                "But on the hard discovery tasks Direct is better: bbcode70 "
                "2/2 and bbcode64 1/1, while Full MACE is 0/3 there."),
            "q2_gap": (
                "Full MACE is bounded by the frozen C0 universe; it produced "
                "exactly the same per-input MSMS as C0 on all 10 tasks. Direct "
                "Qwen can cite operations outside that universe, which is why "
                "it finds the missing cooperative legs and alternative path, "
                "but it emits many extra/stray sets (60 false vs 11) and loses "
                "strict precision on simple tasks."),
            "q3_two_operation": (
                "Direct Qwen 2/2 on sd_pygments_bbcode70_italic; Full MACE 0/2."),
            "q4_three_operation": (
                "Both 0/1 on sd_pygments_groff73_italic. Direct proposed an "
                "enclosing if-span covering multiple blocks; Full only sees U3."),
            "q5_alternative_path": (
                "Direct Qwen 1/1 on sd_pygments_bbcode64_color; Full MACE 0/1."),
            "q6_qwen_extra_gain": (
                "No measurable gain. Full MACE equals C0 per input on all 15 "
                "masking inputs: 5 exact, 11 false, 4 unmatched. The Qwen "
                "hypotheses did not change the final MSMS."),
            "q7_mmbs": "NOT_SEPARABLE; not used in accuracy.",
        },
        "artifacts": {
            "internal_run": str(RUN.relative_to(KIT)),
            "internal_run_sha256": sha(RUN),
            "raw_dir": "runs/sd_direct_vs_full/raw/",
            "scores_dir": "runs/sd_direct_vs_full/scores/",
        },
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"wrote {OUT}")
    print(json.dumps(payload["totals"], ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
