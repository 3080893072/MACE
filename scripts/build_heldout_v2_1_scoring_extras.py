# -*- coding: utf-8 -*-
"""Derive the paired-input matrix and the DEV-vs-HELDOUT table.

Reads only existing score artefacts and DEV result files.  No model calls,
no re-scoring of HELDOUT, no modification of any prediction.
"""
from __future__ import annotations

import csv
import io
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
KIT = Path(__file__).resolve().parents[1]
RES = KIT / "results"
DEV = KIT / "benchmark_v4_dataset" / "source_derived_v2_1"
sys.path.insert(0, str(KIT / "benchmark_v4_dataset" / "tools"))
sys.path.insert(0, str(KIT / "scripts"))
from sd_algorithm_pilot import block_spans  # noqa: E402
from run_candidate_discovery_v2_1 import score_sets  # noqa: E402

ORDER = ["C0", "Full MACE", "Direct Qwen", "Direct GLM"]


def main() -> int:
    sc = json.loads((RES / "MACE_HELDOUT_v2_1_official_scores.json")
                    .read_text("utf-8"))
    per = [r for r in sc["per_input"] if r["eligible"]]

    # ---- paired matrix --------------------------------------------------
    keys = sorted({(r["task_id"], r["input"]) for r in per})
    mat = []
    for cid, inp in keys:
        row = {"task_id": cid, "input": inp}
        for m in ORDER:
            hit = [r for r in per
                   if r["method"] == m and r["task_id"] == cid
                   and r["input"] == inp]
            r = hit[0]
            row[m] = r["msms_exact"]
            row[m + " state"] = r["state"]
            row["hidden_msms"] = "|".join("+".join(s) for s in r["hidden_msms"])
        mat.append(row)
    cols = (["task_id", "input", "hidden_msms"]
            + [c for m in ORDER for c in (m, m + " state")])
    with io.open(RES / "MACE_HELDOUT_v2_1_paired_matrix.csv", "w",
                 encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=cols)
        w.writeheader()
        w.writerows(mat)

    # ---- DEV strict-rule recomputation ----------------------------------
    dev_final = json.loads((RES / "MACE_v2_1_dev_final.json")
                           .read_text("utf-8"))
    # Authoritative closure table (later than the candidate-discovery dump).
    per_task = list(csv.DictReader(io.open(
        RES / "MACE_v2_1_dev_per_task.csv", encoding="utf-8-sig")))
    prim = sorted(r["task_id"] for r in per_task)
    roles = {}
    for cid in prim:
        ref = json.loads((DEV / "tasks" / cid / "reference.json")
                         .read_text("utf-8"))
        roles[cid] = {k: v["role"] for k, v in ref["inputs"].items()}

    dev_doc = json.loads((RES / "MACE_candidate_discovery_v2_1_dev.json")
                         .read_text("utf-8"))
    # Which non-masking inputs were inside the DEV mask denominator: exactly
    # the control-role rows that the closure run scored (2 tasks, both
    # `control`), read from the per-input detail of the DEV dump.
    ctrl_count = {}
    extra_roles = []
    for cid in prim:
        n = 0
        for d in (dev_doc["tasks"].get(cid, {}).get("detail") or []):
            role = roles[cid].get(d["input"])
            if role != "masking":
                n += 1
                extra_roles.append((cid, d["input"], role))
        if n:
            ctrl_count[cid] = n

    full_pub = c0_pub = dev_pub_n = 0
    full_strict = c0_strict = dev_strict_n = 0
    ambiguous = []
    for r in per_task:
        cid = r["task_id"]
        ref_n = int(r["reference_masking_inputs"] or 0)
        n_ctrl = ctrl_count.get(cid, 0)
        ex = int(r["msms_exact"] or 0)
        c0 = int(r["c0_exact"] or 0)
        full_pub += ex
        c0_pub += c0
        dev_pub_n += ref_n
        dev_strict_n += ref_n - n_ctrl
        for bucket, val in (("full", ex), ("c0", c0)):
            out = val
            if n_ctrl:
                if val == ref_n:
                    out = val - n_ctrl
                elif val == 0:
                    out = 0
                else:
                    ambiguous.append((cid, bucket, val, ref_n, n_ctrl))
            if bucket == "full":
                full_strict += out
            else:
                c0_strict += out

    dev_direct = {}
    for name, path in (("Direct Qwen", "MACE_direct_Qwen_v2_1_DEV_completed.json"),
                       ("Direct GLM", "MACE_direct_GLM_v2_1_dev.json")):
        d = json.loads((RES / path).read_text("utf-8"))
        ex = n = 0
        for cid in prim:
            rec = d["tasks"].get(cid) or {}
            ps = rec.get("parsed_sets") or []
            ref = json.loads((DEV / "tasks" / cid / "reference.json")
                             .read_text("utf-8"))
            enum = json.loads((DEV / "evidence" / cid / "enumeration.json")
                              .read_text("utf-8"))
            sp = block_spans(enum)
            ops = {o["id"]: o for s in ps for o in (s.get("ops") or [])}
            for key, v in ref["inputs"].items():
                if v["role"] != "masking":
                    continue
                scv = score_sets([list(s["ids"]) for s in ps], ops, sp,
                                 v.get("msms") or [])
                n += 1
                ex += int(scv["msms_exact"])
        dev_direct[name] = (ex, n)

    dev_pub = dev_final["two_result_sets"][
        "set_1_all_dev_completion_and_strict_scoring"]
    rows = [
        ("C0", c0_pub, dev_pub_n,
         "published DEV denominator (27, includes 2 control-role inputs)"),
        ("C0", c0_strict, dev_strict_n,
         "strict role==masking, control-role rows removed"),
        ("Full MACE", full_pub, dev_pub_n,
         "published DEV denominator (27, includes 2 control-role inputs)"),
        ("Full MACE", full_strict, dev_strict_n,
         "strict role==masking, control-role rows removed"),
        ("Direct Qwen", *dev_direct["Direct Qwen"],
         "strict role==masking, recomputed; DEV run had 5 INVALID_OUTPUT"),
        ("Direct GLM", *dev_direct["Direct GLM"],
         "strict role==masking, recomputed; DEV run had 10 INVALID_OUTPUT"),
    ]
    hm = {m: sc["methods"][m] for m in ORDER}
    out = []
    for m, ex, n, note in rows:
        out.append({
            "method": m, "dev_exact": ex, "dev_inputs": n,
            "dev_pct": round(100 * ex / n, 2),
            "heldout_exact": hm[m]["strict_exact"],
            "heldout_inputs": hm[m]["masking_inputs"],
            "heldout_pct": hm[m]["strict_exact_pct"],
            "delta_pp": round(100 * ex / n - hm[m]["strict_exact_pct"], 2),
            "note": note,
        })
    with io.open(RES / "MACE_v2_1_DEV_vs_HELDOUT.csv", "w",
                 encoding="utf-8-sig", newline="") as fh:
        w = csv.DictWriter(fh, fieldnames=list(out[0]))
        w.writeheader()
        w.writerows(out)

    print(json.dumps({"paired_rows": len(mat), "dev": out,
                      "c0_strict": c0_strict, "full_strict": full_strict,
                      "ambiguous": ambiguous,
                      "non_masking_dev_rows": extra_roles},
                     ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
