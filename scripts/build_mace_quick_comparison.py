"""Build the 30-minute MACE quick-comparison artifact.

This script is read-only over previously frozen results.  It does not run a
model and does not execute a benchmark task.  The deterministic A/B/C numbers
come from the already frozen source-derived algorithm pilot; the only new
content is the per-task comparison view and the explicit Full-MACE NOT_RUN
record for this round.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
SRC = KIT / "benchmark_v4_dataset" / "results" / "source_derived_v1_algorithm_scores.json"
OUT = KIT / "results" / "MACE_quick_comparison.json"

METHODS = {
    "c_fixed": "C-fixed-1.1",
    "graph": "Graph-only",
    "c0": "Role-separated C0",
}
FOCUS = [
    "sd_pygments_bbcode70_italic",
    "sd_pygments_groff73_italic",
    "sd_pygments_bbcode64_color",
]


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def method_view(src: dict) -> dict:
    return {
        "u_exact": bool(src.get("u_exact")),
        "u_recall": src.get("u_recall"),
        "universe_size": src.get("universe_size"),
        "discovered_candidates": src.get("discovered_candidates"),
        "msms_exact": int(src.get("msms_exact") or 0),
        "masking_inputs": int(src.get("masking_inputs") or 0),
        "msms_intervention_exact": int(
            src.get("msms_exact_intervention") or 0),
        "false_relations": int(src.get("false_relations") or 0),
        "unmatched_sets": int(src.get("unmatched_sets") or 0),
        "probes": int(src.get("probe_executions") or 0),
        "wall_seconds": round(float(src.get("wall_seconds") or 0.0), 2),
    }


def main() -> int:
    data = load(SRC)
    per_task = []
    for case in data["per_case"]:
        row = {
            "task_id": case["case_id"],
            "mechanism": case["mechanism"],
            "u_blocks": case["u_blocks"],
            "masking_inputs": case["masking_inputs"],
            "methods": {},
        }
        for key, label in METHODS.items():
            row["methods"][label] = method_view(case["methods"][key])
        per_task.append(row)

    totals = {}
    for key, label in METHODS.items():
        t = data["totals"][key]
        totals[label] = {
            "tasks": t["tasks"],
            "masking_inputs": t["masking_inputs"],
            "msms_exact": t["msms_exact"],
            "msms_intervention_exact": t["msms_exact_intervention"],
            "false_relations": t["false_relations"],
            "unmatched_sets": t["unmatched_sets"],
            "probes": t["probe_executions"],
            "wall_seconds": t["wall_seconds"],
            "u_exact_tasks": t["u_exact_tasks"],
            "cooperative_tasks": t["cooperative_tasks"],
            "cooperative_msms_exact_tasks": t["cooperative_msms_exact_tasks"],
            "u_recall_mean": t["u_recall_mean"],
        }

    payload = {
        "schema": "mace_quick_comparison/1",
        "generated_utc": "2026-11-04T15:41:35Z",
        "mode": "quick_30min",
        "dataset": {
            "name": "source-derived controlled (V4-DEV)",
            "task_count": 10,
            "split": "DEV",
            "track": "SOURCE_DERIVED_CONTROLLED",
            "researcher_constructed": True,
            "note": ("A is a real upstream statement; deletion and U are "
                     "researcher-constructed.  Not a natural upstream defect."),
        },
        "freeze": {
            "code_commit": "2f1ee01",
            "source_artifact": str(SRC.relative_to(KIT)),
            "source_sha256": digest(SRC),
            "reused_artifacts": [
                "benchmark_v4_dataset/results/source_derived_v1_algorithm_scores.json",
                "benchmark_v4_dataset/registry/source_derived_accepted.json",
            ],
            "no_new_deterministic_runs": True,
        },
        "methods": {
            "C-fixed-1.1": {
                "source": "A. C-fixed-1.1 (frozen artifact)",
                "discovery": "AST discovery + rank_and_prune(max_ops=6)",
                "search": "search_relations(mode=exhaustive)",
                "model_calls": 0,
            },
            "Graph-only": {
                "source": "B. Graph-only (frozen artifact)",
                "discovery": "subgraph.build + candidate_selection(max_ops=6)",
                "search": "search_relations(mode=graph)",
                "model_calls": 0,
            },
            "Role-separated C0": {
                "source": "C. Role-separated C0 (frozen artifact)",
                "discovery": "AST discovery + rank_and_prune(max_ops=6)",
                "search": "search_relations_role_separated(budget=16, no hypotheses)",
                "model_calls": 0,
            },
        },
        "per_task": per_task,
        "totals": totals,
        "focus_tasks": FOCUS,
        "full_mace": {
            "status": "NOT_RUN",
            "reason": ("AutoDL SSH endpoint was unreachable in this round. "
                       "Port 37377 refused the connection; 37376 accepted TCP "
                       "but rejected the stored credential; port 22 rejected "
                       "password authentication. No nvidia-smi / Ollama / "
                       "qwen2.5-coder:32b evidence could be collected, so the "
                       "model stage was stopped rather than fabricating GPU "
                       "results."),
            "gpu_used": False,
            "model_calls": 0,
            "adapter_status": ("NOT_IMPLEMENTED_BEYOND_INTERFACE_AUDIT: the "
                               "existing v3 driver is bound to v3 public task "
                               "ids, v3 payloads and v3 probe fixtures; the SD "
                               "packages use a different public schema. A "
                               "separate adapter would be needed, but the "
                               "model endpoint was unavailable before the "
                               "5-minute cutoff."),
            "attempts": [
                {"endpoint": "connect.cqa1.seetacloud.com:37377",
                 "result": "ConnectionRefused (WinError 10061)"},
                {"endpoint": "connect.cqa1.seetacloud.com:37376",
                 "result": "TCP open; AuthenticationException"},
                {"endpoint": "connect.cqa1.seetacloud.com:22",
                 "result": "BadAuthenticationType; password auth not accepted"},
            ],
        },
        "mmbs": {
            "status": "NOT_SEPARABLE",
            "reason": ("reference.json sets mmbs = minimal_masking_sets on "
                       "every input of every SD case; hidden MMBS is not an "
                       "independent quantity. Emitted mmbs_ids are recorded "
                       "but not scored."),
        },
        "scoring_rules": {
            "msms": "independent strict block-family match; minimality checked",
            "mmbs": "NOT_SEPARABLE",
            "unknown": "never counted as FALSE",
            "incomplete": "reported as INCOMPLETE, not as zero",
            "graph_only": "never relabeled as Full MACE",
        },
        "answers": {
            "q1_most_correct_u": ("Graph-only has the highest mean block recall "
                                  "(0.633 vs 0.583) but the same number of "
                                  "exact-U tasks (5/10); it adds stray "
                                  "operations and loses MSMS precision."),
            "q2_best_msms": ("C-fixed-1.1 and Role-separated C0 tie on exact "
                             "MSMS (5/15 masking inputs); Graph-only is 3/15."),
            "q3_cooperative_discovery": ("No deterministic method finds either "
                                         "the two-operation or three-operation "
                                         "cooperative MSMS (0/2 tasks; 0/3 "
                                         "masking inputs)."),
            "q4_qwen_extra_gain": ("NOT_RUN: no Qwen call and no Full MACE "
                                   "result in this round. No extra-gain claim "
                                   "is made."),
            "q5_full_mace_actually_ran": ("No. Status = NOT_RUN; GPU endpoint "
                                          "unreachable and adapter not installed."),
        },
    }

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
