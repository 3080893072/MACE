# -*- coding: utf-8 -*-
"""Assemble the HELDOUT v2.1 prediction-freeze manifest.

Consumes only prediction files (no truth, no scoring) and public case metadata.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
KIT = Path(__file__).resolve().parents[1]
RES = KIT / "results"
PUB = KIT / "runs" / "heldout_public_only"
GLM = RES / "MACE_direct_GLM_v2_1_heldout_predictions.json"
GLM_SHA = "b18154766089fd849515f485bbdb279dd47b336c48fd3d1d4f70f2f1a052597f"

FILES = {
    "c0": RES / "MACE_HELDOUT_v2_1_C0_predictions.json",
    "full": RES / "MACE_HELDOUT_v2_1_Full_predictions.json",
    "qwen": RES / "MACE_HELDOUT_v2_1_Direct_Qwen_predictions.json",
    "glm": GLM,
}


def sha(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def load(p: Path):
    return json.loads(p.read_text("utf-8"))


def main() -> int:
    cases = {p.stem: load(p) for p in (PUB / "cases").glob("*.json")}
    flags = load(PUB / "public_subset_flags.json")["tasks"]

    docs = {k: load(p) for k, p in FILES.items() if p.exists()}
    hashes = {k: sha(p) for k, p in FILES.items() if p.exists()}

    methods = {"c0": "C0", "full": "Full MACE + Qwen",
               "qwen": "Direct Qwen 32B", "glm": "Direct GLM (frozen)"}

    # ---- completeness ----------------------------------------------------
    completeness = {}
    for key, doc in docs.items():
        tasks = doc.get("tasks") or {}
        done, bad = [], []
        for cid in cases:
            rec = tasks.get(cid)
            if rec is None:
                bad.append((cid, "MISSING"))
                continue
            st = rec.get("status")
            if key in ("c0", "full"):
                if st == "OK":
                    done.append(cid)
                else:
                    bad.append((cid, st))
            else:
                if st in ("OK", "INVALID_OUTPUT", "TRUNCATED"):
                    done.append(cid)
                else:
                    bad.append((cid, st))
        completeness[key] = {
            "tasks_completed": len(done),
            "tasks_total": len(cases),
            "complete": len(done) == len(cases),
            "not_completed": [{"task_id": c, "status": s} for c, s in bad],
        }

    # ---- per-method summary ---------------------------------------------
    method_summary = {}
    for key, doc in docs.items():
        tasks = doc.get("tasks") or {}
        if key in ("c0", "full"):
            nonempty = sum(
                1 for r in tasks.values()
                if any(v.get("n_sets", 0) > 0
                       for v in (r.get("predictions") or {}).values()))
            tot = doc.get("totals") or {}
            probes = tot.get("probes")
            wall = tot.get("wall_seconds")
            pt = tot.get("prompt_tokens")
            ct = tot.get("completion_tokens")
        else:
            nonempty = sum(1 for r in tasks.values() if r.get("parsed_sets"))
            probes = None
            wall = round(sum(r.get("runtime_s") or 0
                             for r in tasks.values()), 3)
            pt = sum(r.get("prompt_tokens") or 0 for r in tasks.values())
            ct = sum(r.get("completion_tokens") or 0 for r in tasks.values())
        method_summary[key] = {
            "tasks_present": len(tasks),
            "tasks_with_nonempty_prediction": nonempty,
            "probe_executions": probes,
            "wall_seconds_sum": wall,
            "prompt_tokens": pt,
            "completion_tokens": ct,
            "prediction_unit": ("per_input" if key in ("c0", "full")
                                else "task_level"),
        }

    # ---- per-task execution status --------------------------------------
    rows = []
    for cid in sorted(cases):
        spec = cases[cid]
        fl = flags.get(cid, {})
        pd_ = bool(fl.get("project_disjoint_from_dev"))
        ts_ = bool(fl.get("template_seen_in_dev"))
        for key in ("c0", "full", "qwen", "glm"):
            rec = (docs.get(key, {}).get("tasks") or {}).get(cid) or {}
            preds = rec.get("predictions") or {}
            if key in ("c0", "full"):
                n_pred_inputs = sum(1 for v in preds.values()
                                    if v.get("n_sets", 0) > 0)
                n_sets = sum(v.get("n_sets", 0) for v in preds.values())
                probes = (rec.get("cost") or {}).get("probe_executions")
                wall = (rec.get("cost") or {}).get("wall_seconds")
                pt = ct = None
                parse_err = rec.get("parsed_answer_error") if key == "full" else None
                si = sum(1 for v in (rec.get("per_input") or {}).values()
                         if v.get("SEARCH_INCOMPLETE"))
            else:
                n_pred_inputs = len(rec.get("parsed_sets") or [])
                n_sets = n_pred_inputs
                probes = wall = None
                pt = rec.get("prompt_tokens")
                ct = rec.get("completion_tokens")
                parse_err = rec.get("parse_error")
                si = None
            rows.append({
                "method": methods[key], "method_key": key, "task_id": cid,
                "mechanism": spec.get("mechanism"),
                "project_disjoint": pd_, "template_seen_in_dev": ts_,
                "both_disjoint": pd_ and not ts_,
                "status": rec.get("status", "MISSING"),
                "declared_inputs": len(spec.get("inputs") or []),
                "inputs_with_prediction": n_pred_inputs,
                "predicted_sets": n_sets,
                "probe_executions": probes,
                "wall_seconds": wall,
                "prompt_tokens": pt, "completion_tokens": ct,
                "parse_error": parse_err,
                "search_incomplete_inputs": si,
            })

    # ---- stratification (counts only; no truth) -------------------------
    subsets = {
        "Full": lambda c, f: True,
        "Project-disjoint": lambda c, f: bool(f.get("project_disjoint_from_dev")),
        "Template-disjoint": lambda c, f: not bool(f.get("template_seen_in_dev")),
        "Both-disjoint": lambda c, f: (bool(f.get("project_disjoint_from_dev"))
                                       and not bool(f.get("template_seen_in_dev"))),
    }
    strat = {}
    for name, fn in subsets.items():
        ids = [c for c in cases if fn(c, flags.get(c, {}))]
        strat[name] = {
            "tasks": len(ids),
            "declared_inputs": sum(len(cases[c].get("inputs") or [])
                                   for c in ids),
            "masking_inputs": None,
            "masking_inputs_note": ("UNKNOWN until unsealed scoring; no hidden "
                                    "roles were read during prediction."),
            "task_ids": sorted(ids),
            "per_method_tasks_with_prediction": {
                k: sum(1 for c in ids
                       if ((docs.get(k, {}).get("tasks") or {})
                           .get(c, {}).get("status") in
                           ("OK", "INVALID_OUTPUT", "TRUNCATED")))
                for k in docs},
        }

    manifest = {
        "schema": "mace-heldout-v2.1-freeze-manifest/1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "split": "HELDOUT",
        "scored": False,
        "scoring_performed": False,
        "dataset_root": str(KIT / "benchmark_v4_dataset" / "source_derived_v2_1" / "heldout"),
        "public_source_root": str(PUB),
        "files": {k: {"path": str(p), "sha256": hashes[k],
                      "exists": p.exists()}
                  for k, p in FILES.items()},
        "glm_frozen_sha256_expected": GLM_SHA,
        "glm_frozen_sha256_matches": hashes.get("glm") == GLM_SHA,
        "completeness": completeness,
        "method_summary": method_summary,
        "stratification": strat,
        "no_truth_access": {
            "static_check": load(RES / "MACE_HELDOUT_v2_1_blind_static_check.json")
            if (RES / "MACE_HELDOUT_v2_1_blind_static_check.json").exists() else None,
            "integrity_precheck": load(RES / "MACE_HELDOUT_v2_1_integrity_precheck.json")
            if (RES / "MACE_HELDOUT_v2_1_integrity_precheck.json").exists() else None,
        },
    }
    mout = RES / "MACE_HELDOUT_v2_1_freeze_manifest.json"
    mout.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8")

    csv_out = RES / "MACE_HELDOUT_v2_1_execution_status.csv"
    cols = ["method", "method_key", "task_id", "mechanism", "project_disjoint",
            "template_seen_in_dev", "both_disjoint", "status",
            "declared_inputs", "inputs_with_prediction", "predicted_sets",
            "probe_executions", "wall_seconds", "prompt_tokens",
            "completion_tokens", "parse_error", "search_incomplete_inputs"]
    with io.open(csv_out, "w", encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        for r in rows:
            w.writerow(r)

    print(json.dumps({"hashes": hashes, "completeness": completeness,
                      "stratification": {k: v["tasks"] for k, v in strat.items()},
                      "glm_match": manifest["glm_frozen_sha256_matches"]},
                     ensure_ascii=False, indent=1))
    print("wrote", mout, csv_out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
