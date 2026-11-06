# -*- coding: utf-8 -*-
"""MACE-Bench v2.1 HELDOUT — official independent scoring.

Reads the four frozen prediction files and the formal v2.1 HELDOUT reference,
applies the frozen scoring definition (score_sets + block projection), and
writes scores, per-input rows, pairwise McNemar results and subset tables.

No model is called.  No prediction file is modified.  Fails closed if any
prediction hash mismatches.
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import os
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

sys.stdout.reconfigure(encoding="utf-8")
KIT = Path(__file__).resolve().parents[1]
HELDOUT = KIT / "benchmark_v4_dataset" / "source_derived_v2_1" / "heldout"
PUB = KIT / "runs" / "heldout_public_only"
RES = KIT / "results"
# Read predictions from RES; write scores here.  Override only when you want
# to reproduce the scoring without touching the frozen artifacts.
OUT = Path(os.environ.get("MACE_SCORE_OUT", RES))

if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))
if str(KIT / "benchmark_v4_dataset" / "tools") not in sys.path:
    sys.path.insert(0, str(KIT / "benchmark_v4_dataset" / "tools"))
if str(KIT / "scripts") not in sys.path:
    sys.path.insert(0, str(KIT / "scripts"))

from sd_algorithm_pilot import block_spans, family, project_containment  # noqa: E402
from run_candidate_discovery_v2_1 import score_sets  # noqa: E402

PRED = {
    "C0": (RES / "MACE_HELDOUT_v2_1_C0_predictions.json",
           "ecc55c7ac10bc5e302d69ae31b7b5439f0847c983eb1dbe39d1fe72bae40d28d"),
    "Full MACE": (RES / "MACE_HELDOUT_v2_1_Full_predictions.json",
                  "056e6565f0eed7f3e8057ddd0a5550299e42ccb14e0ba7065a25dbd5756ee478"),
    "Direct Qwen": (RES / "MACE_HELDOUT_v2_1_Direct_Qwen_predictions.json",
                    "0d216443dc35ca404c5f508e312d1a501dc4b124eedec82f578eeac40dd2476e"),
    "Direct GLM": (RES / "MACE_direct_GLM_v2_1_heldout_predictions.json",
                   "b18154766089fd849515f485bbdb279dd47b336c48fd3d1d4f70f2f1a052597f"),
}
ORDER = ["C0", "Full MACE", "Direct Qwen", "Direct GLM"]
PER_INPUT_METHODS = ("C0", "Full MACE")
COOP = ("M2", "M3")
ALT = ("M4",)


def sha_bytes(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def sha_file(p: Path) -> str:
    return sha_bytes(p.read_bytes())


def load(p: Path) -> Any:
    return json.loads(p.read_text("utf-8"))


def mcnemar_exact(b: int, c: int) -> float:
    """Two-sided exact binomial McNemar p (b, c discordant)."""
    n = b + c
    if n == 0:
        return 1.0
    k = min(b, c)
    tail = sum(math.comb(n, i) for i in range(0, k + 1)) / (2 ** n)
    return min(1.0, 2 * tail)


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    # ---- 1. frozen-file gate -------------------------------------------
    audit = {"started_utc": datetime.now(timezone.utc).isoformat(),
             "script": str(Path(__file__).resolve()),
             "script_sha256": sha_file(Path(__file__).resolve()),
             "dataset_root": str(HELDOUT),
             "prediction_hashes": {}, "hash_ok": True,
             "scorer_version": "1.1",
             "version_note": ("1.1 fixes a method-alias bug in 1.0: the "
                              "per-input branch tested name=='Full' while the "
                              "frozen key is 'Full MACE', which mis-scored Full "
                              "as empty. The defective 1.0 output was detected "
                              "before reporting and overwritten; 1.1 adds the "
                              "fail-closed self-check that would have caught it.")}
    preds = {}
    for name, (path, expect) in PRED.items():
        actual = sha_file(path)
        audit["prediction_hashes"][name] = {
            "path": str(path), "expected": expect, "actual": actual,
            "matches": actual == expect}
        if actual != expect:
            audit["hash_ok"] = False
        preds[name] = load(path)
    if not audit["hash_ok"]:
        audit["aborted"] = "prediction hash mismatch; scoring not performed"
        (OUT / "MACE_HELDOUT_v2_1_official_scores.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        print("ABORT: hash mismatch", json.dumps(audit["prediction_hashes"]))
        return 2

    cases = {p.stem: load(p) for p in (PUB / "cases").glob("*.json")}
    flags = load(PUB / "public_subset_flags.json")["tasks"]
    refs, spans, ref_hashes = {}, {}, {}
    for cid in cases:
        rp = HELDOUT / "tasks" / cid / "reference.json"
        ep = HELDOUT / "evidence" / cid / "enumeration.json"
        refs[cid] = load(rp)
        spans[cid] = block_spans(load(ep))
        ref_hashes[cid] = {"reference": sha_file(rp),
                           "enumeration": sha_file(ep)}
    audit["reference_hashes"] = ref_hashes
    audit["reference_source"] = "formal v2.1 tasks/<cid>/reference.json"

    # ---- 2. per-input scoring ------------------------------------------
    rows: List[Dict[str, Any]] = []
    for name in ORDER:
        tasks = preds[name].get("tasks") or {}
        for cid in sorted(cases):
            spec = cases[cid]
            rec = tasks.get(cid) or {}
            keys = list(spec["inputs"])
            role_map = {k: refs[cid]["inputs"][k] for k in keys}
            mask_keys = [k for k in keys if role_map[k]["role"] == "masking"]
            if name in PER_INPUT_METHODS:
                field = ("predicted_kept_sets" if name == "C0"
                         else "predicted_sets")
                ops_by_id = rec.get("ops") or {}
                # ids carry file:first-last; enrich from universe if needed
                universe = {op["id"]: op for op in (
                    rec.get("universe") or rec.get("u_union") or [])}
                ops_by_id = {**ops_by_id, **universe}
                per_input = rec.get("predictions") or {}
                gates = rec.get("per_input") or {}
                task_status = rec.get("status", "MISSING")
            else:
                parsed = rec.get("parsed_sets") or []
                ops_by_id = {}
                for s in parsed:
                    for op in s.get("ops") or []:
                        ops_by_id[op["id"]] = op
                field = "ids"
                per_input = None
                task_status = rec.get("status", "MISSING")
            for key in keys:
                hidden = role_map[key]
                row = {
                    "method": name, "task_id": cid,
                    "mechanism": spec.get("mechanism"), "input": key,
                    "role": hidden["role"],
                    "eligible": hidden["role"] == "masking",
                    "task_status": task_status,
                }
                if hidden["role"] != "masking":
                    rows.append(row)
                    continue
                gate = None
                if name in PER_INPUT_METHODS:
                    entry = per_input.get(key) or {}
                    gate = (gates.get(key) or {}).get("gate")
                    sets = [list(s) for s in (entry.get(field) or [])]
                    if sets:
                        state = "SCORED"
                    elif gate == "probe_error":
                        state = "EXECUTION_ERROR"
                    elif gate in ("A_NOT_EXECUTED", "PLUS_NOT_RETURN"):
                        state = "ABSTAIN_EMPTY"
                    elif gate == "A_DELETION_CHANGES_OUTPUT":
                        state = "NO_CANDIDATE"
                    else:
                        state = "ABSTAIN_EMPTY"
                else:
                    sets = [list(s[field]) for s in (rec.get("parsed_sets") or [])]
                    state = ("SCORED" if sets else "INVALID_OUTPUT"
                             if task_status != "OK" else "ABSTAIN_EMPTY")
                want = hidden.get("msms") or []
                sc = score_sets(sets, ops_by_id, spans[cid], want)
                row.update({
                    "gate": gate,
                    "state": state,
                    "n_pred_sets": len(sets),
                    "n_hidden_sets": len(want),
                    "n_hidden_blocks": sum(len(s) for s in want),
                    "msms_exact": int(sc["msms_exact"]),
                    "msms_present": int(sc["hidden_msms_present"]),
                    "false_relations": sc["false_relations"],
                    "unmatched_sets": sc["unmatched_sets"],
                    "stray_ops": len(sc["stray_ops"]),
                    "got_blocks": sorted(sorted(s) for s in sc["got_msms_blocks"]),
                    "hidden_msms": sorted(sorted(s) for s in want),
                    "precision": None, "recall": None,
                })
                want_f = family(want)
                got_f = family([b for b in sc["got_msms_blocks"]])
                tp = len(got_f & want_f)
                row["precision"] = round(tp / len(got_f), 4) if got_f else 0.0
                row["recall"] = round(tp / len(want_f), 4) if want_f else 0.0
                row["tp"] = tp
                rows.append(row)

    # ---- 2.1 self-checks (fail closed on scorer/namespace defects) -----
    elig = {m: {(r["task_id"], r["input"]) for r in rows
                if r["method"] == m and r["eligible"]} for m in ORDER}
    self_checks = {
        "eligible_key_sets_identical": all(elig[m] == elig[ORDER[0]]
                                           for m in ORDER),
        "masking_inputs": len(elig[ORDER[0]]),
        "masking_tasks": len({t for t, _ in elig[ORDER[0]]}),
        "nonempty_by_method": {},
        "nonempty_matches_file": {},
    }
    for m in PER_INPUT_METHODS:
        direct = 0
        for cid in cases:
            rec = (preds[m].get("tasks") or {}).get(cid) or {}
            role_map = refs[cid]["inputs"]
            for key, v in (rec.get("predictions") or {}).items():
                if (role_map.get(key, {}).get("role") == "masking"
                        and (v.get("n_sets") or 0) > 0):
                    direct += 1
        scored = sum(1 for r in rows if r["method"] == m and r["eligible"]
                     and r["n_pred_sets"] > 0)
        self_checks["nonempty_by_method"][m] = scored
        self_checks["nonempty_matches_file"][m] = scored == direct
    for m in ORDER:
        self_checks["nonempty_by_method"].setdefault(
            m, sum(1 for r in rows if r["method"] == m and r["eligible"]
                   and r["n_pred_sets"] > 0))
    bad = [k for k, v in self_checks.items()
           if isinstance(v, bool) and not v]
    if bad:
        audit["self_checks"] = self_checks
        audit["aborted"] = f"scorer self-check failed: {bad}"
        (OUT / "MACE_HELDOUT_v2_1_official_scores.json").write_text(
            json.dumps(audit, ensure_ascii=False, indent=2), encoding="utf-8")
        print("ABORT self-check", json.dumps(self_checks, ensure_ascii=False))
        return 3
    audit["self_checks"] = self_checks

    # ---- 3. method aggregates -----------------------------------------
    methods = {}
    for name in ORDER:
        rs = [r for r in rows if r["method"] == name and r["eligible"]]
        n = len(rs)
        exact = sum(r["msms_exact"] for r in rs)
        present = sum(r["msms_present"] for r in rs)
        tp = sum(r.get("tp") or 0 for r in rs)
        got = sum(len(r.get("got_blocks") or []) for r in rs)
        want = sum(r.get("n_hidden_blocks") or 0 for r in rs)
        coops = [r for r in rs if str(r["mechanism"]).startswith(COOP)]
        alts = [r for r in rs if str(r["mechanism"]).startswith(ALT)]
        methods[name] = {
            "masking_inputs": n,
            "strict_exact": exact,
            "strict_exact_pct": round(100 * exact / n, 2) if n else None,
            "nonempty_prediction_inputs": sum(
                1 for r in rs if r["n_pred_sets"] > 0),
            "coverage_pct": round(100 * sum(
                1 for r in rs if r["n_pred_sets"] > 0) / n, 2) if n else None,
            "present_superset": present,
            "false_relations": sum(r["false_relations"] for r in rs),
            "unmatched_sets": sum(r["unmatched_sets"] for r in rs),
            "stray_operations": sum(r["stray_ops"] for r in rs),
            "micro_precision": round(tp / got, 4) if got else None,
            "micro_recall": round(tp / want, 4) if want else None,
            "macro_precision": round(
                sum(r["precision"] for r in rs) / n, 4) if n else None,
            "macro_recall": round(
                sum(r["recall"] for r in rs) / n, 4) if n else None,
            "cooperative_accuracy": {
                "exact": sum(r["msms_exact"] for r in coops),
                "inputs": len(coops),
                "pct": round(100 * sum(r["msms_exact"] for r in coops)
                             / len(coops), 2) if coops else None,
                "mechanisms": ["M2", "M3"],
            },
            "alternative_path_accuracy": {
                "exact": sum(r["msms_exact"] for r in alts),
                "inputs": len(alts),
                "pct": round(100 * sum(r["msms_exact"] for r in alts)
                             / len(alts), 2) if alts else None,
                "mechanisms": ["M4"],
            },
            "mmbs_accuracy": {
                "value": None,
                "reason": ("no frozen method emits MMBS predictions; MMBS is "
                           "not scored (not counted as wrong or empty)"),
            },
            "input_states": {
                s: sum(1 for r in rs if r["state"] == s)
                for s in sorted({r["state"] for r in rs})},
            "tasks_with_predictions": len(
                {r["task_id"] for r in rs if r["n_pred_sets"] > 0}),
        }

    # ---- 4. paired comparisons ----------------------------------------
    idx = {(r["method"], r["task_id"], r["input"]): r for r in rows
           if r["eligible"]}
    keys = sorted({(r["task_id"], r["input"]) for r in rows if r["eligible"]})
    pair_rows = []
    for i, a in enumerate(ORDER):
        for b in ORDER[i + 1:]:
            bb = cc = both = neither = 0
            for k in keys:
                ra, rb = idx.get((a, *k)), idx.get((b, *k))
                if ra is None or rb is None:
                    continue
                ea, eb = ra["msms_exact"], rb["msms_exact"]
                if ea and not eb:
                    bb += 1
                elif eb and not ea:
                    cc += 1
                elif ea and eb:
                    both += 1
                else:
                    neither += 1
            p = mcnemar_exact(bb, cc)
            pair_rows.append({
                "method_a": a, "method_b": b, "n_paired_inputs":
                    bb + cc + both + neither,
                "a_only": bb, "b_only": cc, "both": both,
                "neither": neither,
                "discordant": bb + cc,
                "risk_difference_pp": round(
                    100 * (bb - cc) / (bb + cc + both + neither), 2)
                if (bb + cc + both + neither) else None,
                "mcnemar_exact_p": round(p, 6),
                "significant_0.05": p < 0.05,
            })

    # ---- 5. generalization subsets ------------------------------------
    subsets = {
        "Full": lambda f: True,
        "Project-disjoint": lambda f: bool(f.get("project_disjoint_from_dev")),
        "Template-disjoint": lambda f: not bool(f.get("template_seen_in_dev")),
        "Both-disjoint": lambda f: (bool(f.get("project_disjoint_from_dev"))
                                    and not bool(f.get("template_seen_in_dev"))),
    }
    gen = {}
    for sname, fn in subsets.items():
        ids = {c for c in cases if fn(flags.get(c, {}))}
        gen[sname] = {"tasks": len(ids), "methods": {}}
        for name in ORDER:
            rs = [r for r in rows if r["method"] == name and r["eligible"]
                  and r["task_id"] in ids]
            gen[sname]["methods"][name] = {
                "masking_inputs": len(rs),
                "exact": sum(r["msms_exact"] for r in rs),
                "pct": round(100 * sum(r["msms_exact"] for r in rs)
                             / len(rs), 2) if rs else None,
            }

    # ---- 6. write artefacts -------------------------------------------
    out = {
        "schema": "mace-heldout-v2.1-official-scores/1",
        "scorer_version": "1.1",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "split": "HELDOUT",
        "scored": True,
        "unsealed": True,
        "dataset_root": str(HELDOUT),
        "denominator_rule": ("every input whose reference role == 'masking'; "
                             "identical denominator for all four methods; "
                             "UNKNOWN != FALSE"),
        "methods": methods,
        "pairwise": pair_rows,
        "generalization": gen,
        "per_input": rows,
        "audit": audit,
        "known_anomaly": {
            "task": "sd_multidict_version_m6",
            "inputs": {"mask_one_impl": "masking",
                       "expose_two_impls": "exposing",
                       "control_non_multidict": "control"},
            "rule": ("only the masking input enters the denominator; the other "
                     "two are outside every method's denominator by the frozen "
                     "role rule. No method-specific denominator adjustment."),
        },
    }
    audit["finished_utc"] = datetime.now(timezone.utc).isoformat()
    scores_path = OUT / "MACE_HELDOUT_v2_1_official_scores.json"
    scores_path.write_text(json.dumps(out, ensure_ascii=False, indent=2),
                           encoding="utf-8")

    cols = ["method", "task_id", "mechanism", "input", "role", "eligible",
            "task_status", "gate", "state", "n_pred_sets", "n_hidden_sets",
            "n_hidden_blocks", "msms_exact", "msms_present",
            "false_relations", "unmatched_sets", "stray_ops", "tp",
            "precision", "recall"]
    with io.open(OUT / "MACE_HELDOUT_v2_1_per_input_scores.csv", "w",
                 encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        for r in rows:
            w.writerow(r)

    with io.open(OUT / "MACE_HELDOUT_v2_1_method_comparison.csv", "w",
                 encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(pair_rows[0]))
        w.writeheader()
        w.writerows(pair_rows)

    with io.open(OUT / "MACE_HELDOUT_v2_1_generalization.csv", "w",
                 encoding="utf-8-sig", newline="") as fh:
        w = csv.writer(fh)
        w.writerow(["subset", "tasks", "method", "masking_inputs", "exact",
                    "pct"])
        for sname, s in gen.items():
            for name in ORDER:
                m = s["methods"][name]
                w.writerow([sname, s["tasks"], name, m["masking_inputs"],
                            m["exact"], m["pct"]])

    print(json.dumps({"methods": {k: {
        "inputs": v["masking_inputs"], "exact": v["strict_exact"],
        "pct": v["strict_exact_pct"], "coverage": v["coverage_pct"],
        "false": v["false_relations"], "unmatched": v["unmatched_sets"]}
        for k, v in methods.items()}, "pairwise": pair_rows},
        ensure_ascii=False, indent=1))
    print("wrote", scores_path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
