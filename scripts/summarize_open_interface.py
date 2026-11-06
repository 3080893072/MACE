"""Summarise the open-discovery interface check (no new model calls)."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
INTERFACE = ROOT / "benchmark_open_v1" / "interface"
OUT = INTERFACE / "interface_summary.json"


def main() -> int:
    data = json.loads((INTERFACE / "ctrl_interface.json").read_text(encoding="utf-8"))
    attr = json.loads((ROOT / "benchmark_pilot" / "attribution.json")
                      .read_text(encoding="utf-8"))["controlled"]
    tasks = {t["task_id"]: t for t in data["tasks"]}
    rows = []
    agg = {
        "direct_tokens": 0, "direct_prompt": 0, "direct_completion": 0,
        "direct_wall": 0, "direct_unique": 0, "direct_verified": 0,
        "direct_false": 0, "direct_unverified": 0, "direct_incomplete": 0,
        "direct_duplicates": 0, "direct_witness_pass": 0,
        "direct_executions": 0,
        "mace_raw_tokens": 0, "mace_raw_wall": 0, "mace_raw_calls": 0,
        "mace_norm_tokens": 0, "mace_norm_wall": 0, "mace_norm_calls": 0,
    }
    seed_total = 0
    seed_complete = 0
    seed_witness = 0

    for tid in ("ctrl_01", "ctrl_02", "ctrl_03"):
        task = tasks[tid]
        direct = task["direct_qwen"]
        counts = direct["verification"]["counts"]
        unique = [r for r in direct["verification"]["relation_results"]
                  if r["status"] != "DUPLICATE"]
        witness_pass = 0
        for result in unique:
            checks = result.get("checks") or {}
            core = (checks.get("a_has_local_effect")
                    and checks.get("original_masks")
                    and checks.get("only_set_masks")
                    and checks.get("disabling_set_exposes"))
            if not core:
                continue
            if result.get("kind") in ("independent", "cooperative"):
                if all((checks.get("proper_subsets_do_not_mask") or {}).values()):
                    witness_pass += 1
            elif result.get("kind") == "coexisting":
                if all((checks.get("proper_subsets_do_not_expose") or {}).values()):
                    witness_pass += 1

        seeds = []
        for item in attr[tid].get("absorber_sets", []):
            seeds.append((frozenset(item["ops"]), item["kind"]))
        for item in attr[tid].get("coexisting_sets", []):
            seeds.append((frozenset(item["ops"]), "coexisting"))
        direct_keys = {(frozenset(r.get("operations") or []), r.get("kind"))
                       for r in unique if r.get("operations")}
        matches = [key for key in direct_keys if key in seeds]
        seed_total += len(seeds)
        seed_witness += len(matches)

        stats = direct["stats"]
        tokens = stats["prompt_tokens"] + stats["completion_tokens"]
        raw = task["full_mace"]["raw"]
        norm = task["full_mace"]["normalized"]

        def usage_tokens(usage):
            usage = usage or {}
            return usage.get("prompt_tokens", 0) + usage.get("completion_tokens", 0)

        rows.append({
            "task_id": tid,
            "source": "old controlled Pilot task (interface check only, not a new real task)",
            "direct_qwen": {
                "status": direct["verification"]["status"],
                "counts": counts,
                "witness_execution_pass": witness_pass,
                "seed_sets": [[sorted(k[0]), k[1]] for k in seeds],
                "seed_matches_at_operation_kind": [[sorted(k[0]), k[1]] for k in matches],
                "guard": direct["guard"],
                "test_gap_exact": direct["test_gap"].get("exact"),
                "test_gap_covered": direct["test_gap"].get("covered"),
                "test_gap_total": direct["test_gap"].get("total"),
                "counterexample": direct["counterexample"],
                "tokens": tokens,
                "wall_seconds": direct["wall_seconds"],
                "verification_executions": direct["verification_executions"],
                "prompt_sha256": direct["prompt_sha256"],
            },
            "full_mace_raw": {
                "run_status": raw["run_status"],
                "interface_status": raw["interface_status"],
                "tokens": usage_tokens(raw["usage"]),
                "wall_seconds": raw["wall_seconds"],
                "calls": (raw["usage"] or {}).get("calls"),
            },
            "full_mace_normalized": {
                "run_status": norm["run_status"],
                "interface_status": norm["interface_status"],
                "tokens": usage_tokens(norm["usage"]),
                "wall_seconds": norm["wall_seconds"],
                "calls": (norm["usage"] or {}).get("calls"),
                "guard": norm.get("final_guard"),
                "bundle_keys": norm.get("final_bundle_keys"),
                "adapter_missing": norm["adapter"]["missing"],
            },
            "schema_probe": {
                "run_status": task["schema_probe"]["status"],
                "interface_status": task["schema_probe"]["interface_status"],
                "bundle_keys": task["schema_probe"]["final_bundle_keys"],
                "report_keys": task["schema_probe"]["report_keys"],
                "adapter_missing": task["schema_probe"]["adapter"]["missing"],
            },
        })
        agg["direct_tokens"] += tokens
        agg["direct_prompt"] += stats["prompt_tokens"]
        agg["direct_completion"] += stats["completion_tokens"]
        agg["direct_wall"] += direct["wall_seconds"]
        agg["direct_unique"] += counts["submitted"]
        agg["direct_verified"] += counts["verified"]
        agg["direct_false"] += counts["false"]
        agg["direct_unverified"] += counts["unverified"]
        agg["direct_incomplete"] += counts["incomplete"]
        agg["direct_duplicates"] += counts["duplicates_ignored"]
        agg["direct_witness_pass"] += witness_pass
        agg["direct_executions"] += direct["verification_executions"]
        agg["mace_raw_tokens"] += usage_tokens(raw["usage"])
        agg["mace_raw_wall"] += raw["wall_seconds"]
        agg["mace_raw_calls"] += (raw["usage"] or {}).get("calls", 0)
        agg["mace_norm_tokens"] += usage_tokens(norm["usage"])
        agg["mace_norm_wall"] += norm["wall_seconds"]
        agg["mace_norm_calls"] += (norm["usage"] or {}).get("calls", 0)

    summary = {
        "schema_version": "mace-open-interface-summary-v1",
        "generated_from": "benchmark_open_v1/interface/ctrl_interface.json",
        "model": data["model"],
        "scope": ("interface feasibility on ctrl_01/02/03; no new real task was "
                  "selected because Full MACE failed the interface gate"),
        "tasks": rows,
        "aggregates": {
            **agg,
            "direct_false_attribution_rate_all_unique": round(
                agg["direct_false"] / max(agg["direct_unique"], 1), 4),
            "direct_false_attribution_rate_evaluable": round(
                agg["direct_false"] / max(agg["direct_false"] + agg["direct_verified"], 1), 4),
            "direct_unverified_rate_all_unique": round(
                agg["direct_unverified"] / max(agg["direct_unique"], 1), 4),
            "direct_complete_valid_rate": round(
                agg["direct_verified"] / max(agg["direct_unique"], 1), 4),
            "direct_execution_count": agg["direct_executions"],
            "mace_execution_count": "not_reported",
            "seed_total_controlled": seed_total,
            "seed_complete_valid_recovered": seed_complete,
            "seed_witness_operation_kind_matched": seed_witness,
            "seed_recovery_applies_to": "direct_qwen_only",
            "full_mace_seed_recovery": "N/A_UNSUPPORTED",
            "new_real_tasks_created": 0,
            "new_real_task_seeds_created": 0,
        },
        "gate": {
            "full_mace_operation_attribution": "UNSUPPORTED",
            "decision": "STOP",
            "new_tasks_created": False,
        },
        "notes": [
            "ctrl_01/02/03 are old controlled Pilot instruments; these are not benchmark scores.",
            "Direct Qwen can emit the required JSON shape and operation lines, but 0 unique records had a sound+exact condition; its ctrl_01 relation is witness-true while condition=True is unsound.",
            "Full MACE raw output used <expr> notation and produced NO_RESULT; a uniform notation-normalizing transport adapter then produced a valid bundle, but the bundle has no operation-set/input relations.",
            "Full MACE guard/witness output was not substituted for the missing operation attribution.",
            "Program execution counts for Full MACE are not reported by run_mode and are recorded as not_reported, not estimated.",
        ],
    }
    OUT.write_text(json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    print(json.dumps(summary["aggregates"], indent=2))
    for row in rows:
        print(row["task_id"], row["direct_qwen"]["status"],
              row["direct_qwen"]["counts"],
              "witness", row["direct_qwen"]["witness_execution_pass"],
              "seeds", row["direct_qwen"]["seed_sets"],
              "match", row["direct_qwen"]["seed_matches_at_operation_kind"])
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
