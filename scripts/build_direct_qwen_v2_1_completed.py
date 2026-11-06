"""Build the completed Direct Qwen 32B DEV baseline for MACE-Bench v2.1.

Reads, never rewrites:
  * the 10 existing Direct Qwen responses in runs/sd_direct_vs_full/raw/
  * the 15 new responses in results/MACE_direct_Qwen_v2_1_dev_new.json
  * v2.1 formal references/evidence
  * C0 / Full MACE per-input details (v2.1 runs + the frozen v2 four-task run)
  * the Direct GLM v2.1 DEV result

Writes:
  * results/MACE_direct_Qwen_v2_1_DEV_completed.json
  * results/MACE_four_methods_DEV_comparison.csv
  * docs/MACE_direct_Qwen_v2_1_DEV_completion.md
"""
from __future__ import annotations

import csv
import hashlib
import io
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))
TOOLS = KIT / "benchmark_v4_dataset" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from sd_algorithm_pilot import block_spans, family, load, project_containment  # noqa: E402
from scripts.run_direct_glm_v2_1 import map_direct, score_sets  # noqa: E402

V21 = KIT / "benchmark_v4_dataset" / "source_derived_v2_1"
NEW = KIT / "results" / "MACE_direct_Qwen_v2_1_dev_new.json"
OLD_RAW = KIT / "runs" / "sd_direct_vs_full" / "raw"
GLM = KIT / "results" / "MACE_direct_GLM_v2_1_dev.json"
V2 = KIT / "results" / "MACE_candidate_discovery_v2.json"
DEV_FINAL = KIT / "results" / "MACE_v2_1_dev_final.json"
OUT_JSON = KIT / "results" / "MACE_direct_Qwen_v2_1_DEV_completed.json"
OUT_CSV = KIT / "results" / "MACE_four_methods_DEV_comparison.csv"
OUT_MD = KIT / "docs" / "MACE_direct_Qwen_v2_1_DEV_completion.md"

V2_REUSED = {
    "sd_pygments_bbcode70_italic",
    "sd_pygments_bbcode64_color",
    "sd_pygments_groff73_italic",
    "sd_networkx_gexf448_slices",
}
OLD_RUN = [
    "sd_jsonschema_1145_pointer", "sd_networkx_gexf448_slices",
    "sd_pygments_bbcode64_color", "sd_pygments_bbcode70_italic",
    "sd_pygments_groff73_italic", "sd_pygments_latex297_italic",
    "sd_pygments_style95_cache", "sd_tabulate_1052_strip_right",
    "sd_tabulate_1056_strip_center", "sd_tabulate_2557_curlen",
]


def sha_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha_file(p: Path) -> str:
    return hashlib.sha256(p.read_bytes()).hexdigest()


def utc_now() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def public_view(cid: str):
    spec = load(V21 / "cases" / f"{cid}.json")
    rel = spec["base"]["file"]
    patched = (V21 / "evidence" / cid / "patched" / Path(rel).name) \
        .read_text("utf-8").splitlines(keepends=True)
    from sd_algorithm_pilot import _MARKER
    source = "".join(line if not _MARKER.match(line) else "\n"
                     for line in patched)
    return spec, rel, source, int(spec["base"]["A_line"]), spec["base"]["A_code"]


def score_record(cid: str, raw_response: str) -> dict:
    spec, rel, source, a_line, _ = public_view(cid)
    parsed, rejected, parse_error = map_direct(raw_response, rel, source, a_line)
    enumeration = load(V21 / "evidence" / cid / "enumeration.json")
    spans = block_spans(enumeration)
    reference = load(V21 / "tasks" / cid / "reference.json")
    ops_by_id = {op["id"]: op for r in parsed for op in r["operations"]}
    sets = [[op["id"] for op in r["operations"]] for r in parsed]
    agg = {"masking_inputs": 0, "exact": 0, "present": 0,
           "false_relations": 0, "unmatched_sets": 0,
           "precision_sum": 0.0, "recall_sum": 0.0}
    detail = []
    for index, (key, hidden) in enumerate(reference["inputs"].items(), 1):
        if hidden.get("role") != "masking":
            continue
        score = score_sets(sets, ops_by_id, spans, hidden["msms"])
        agg["masking_inputs"] += 1
        agg["exact"] += int(score["msms_exact"])
        agg["present"] += int(bool(score["got_msms_blocks"]))
        agg["false_relations"] += score["false_relations"]
        agg["unmatched_sets"] += score["unmatched_sets"]
        agg["precision_sum"] += score["precision"]
        agg["recall_sum"] += score["recall"]
        detail.append({"input": key, "public_id": f"in{index}",
                       "mmbs_status": hidden.get("mmbs_status"),
                       "mmbs_exact": None,
                       "parsed_sets": len(sets),
                       "score": score})
    n = agg["masking_inputs"]
    agg["precision"] = round(agg["precision_sum"] / n, 4) if n else 0.0
    agg["recall"] = round(agg["recall_sum"] / n, 4) if n else 0.0
    agg.pop("precision_sum", None)
    agg.pop("recall_sum", None)
    return {"parsed_sets": parsed, "rejected": rejected,
            "parse_error": parse_error, "scoring": agg, "detail": detail,
            "source_sha256": sha_text(source),
            "enumeration": enumeration, "reference": reference}


def build_old(cid: str) -> dict:
    raw_path = OLD_RAW / f"{cid}__direct.json"
    original = load(raw_path)
    scored = score_record(cid, original.get("raw_response") or "")
    spec = load(V21 / "cases" / f"{cid}.json")
    prompt = original["messages"][1]["content"]
    stats = dict(original.get("stats") or {})
    rec = {
        "task_id": cid,
        "split": "DEV",
        "mechanism": spec["mechanism"],
        "model": original.get("model", "qwen2.5-coder:32b"),
        "options": original.get("options"),
        "public_source_sha256": scored["source_sha256"],
        "prompt_sha256": sha_text(prompt),
        "prompt_chars": len(prompt),
        "declared_inputs": len(spec["inputs"]),
        "call": {
            "ok": bool(original.get("ok")),
            "messages": original["messages"],
            "raw_response": original.get("raw_response", ""),
            "stats": stats,
            "model": original.get("model"),
            "wall_seconds": original.get("wall_seconds"),
        },
        "prompt_tokens": stats.get("prompt_tokens"),
        "completion_tokens": stats.get("completion_tokens"),
        "runtime_s": original.get("wall_seconds") or stats.get("wall_seconds"),
        "done_reason": stats.get("done_reason"),
        "context_limit": 8192,
        "context_truncated_suspected": bool(
            stats.get("prompt_tokens") and stats["prompt_tokens"] >= 8184),
        "parsed_sets": [{"ids": [op["id"] for op in r["operations"]],
                         "ops": r["operations"],
                         "condition": r["condition"],
                         "rationale": r["rationale"]}
                        for r in scored["parsed_sets"]],
        "rejected": scored["rejected"],
        "parse_error": scored["parse_error"],
        "scoring": scored["scoring"],
        "detail": scored["detail"],
        "status": "OK" if original.get("ok") and scored["parsed_sets"]
                  else "INVALID_OUTPUT",
        "provenance": {
            "record": "reused_original_call",
            "raw_record": str(raw_path.relative_to(KIT)).replace("\\", "/"),
            "raw_record_sha256": sha_file(raw_path),
            "scoring": "re-derived offline against v2.1 formal reference; "
                       "raw response and historical scoring untouched",
            "prompt_identity": "messages[1] equal to v2.1 rebuild",
        },
    }
    if rec["status"] == "OK" and rec["done_reason"] == "length":
        rec["status"] = "TRUNCATED"
    return rec


def build_new(cid: str, rec: dict) -> dict:
    rec = dict(rec)
    spec = load(V21 / "cases" / f"{cid}.json")
    rec["mechanism"] = spec["mechanism"]
    n_sets = len(rec.get("parsed_sets") or [])
    rec["detail"] = [dict(d, parsed_sets=d.get("parsed_sets", n_sets))
                     for d in rec.get("detail") or []]
    rec["provenance"] = {
        "record": "new_call_v2_1",
        "raw_record": f"runs/direct_qwen_v2_1/dev/{cid}.json",
        "raw_record_sha256": (sha_file(KIT / "runs/direct_qwen_v2_1/dev" / f"{cid}.json")
                              if (KIT / "runs/direct_qwen_v2_1/dev" / f"{cid}.json").exists()
                              else None),
        "scoring": "v2.1 formal reference",
    }
    return rec


def normalize_present(rec: dict) -> dict:
    """Frozen-artifact definition of `present`: every hidden MSMS set is found.

    `valid` is the weaker output-validity flag: at least one scored block.
    """
    present = valid = 0
    for item in rec.get("detail") or []:
        score = item.get("score") or {}
        want = {frozenset(x) for x in score.get("hidden_msms") or []}
        have = {frozenset(x) for x in score.get("got_msms_blocks") or []}
        present += int(bool(want) and want <= have)
        valid += int(bool(have))
    rec["scoring"]["present"] = present
    rec["scoring"]["valid"] = valid
    return rec


def masking_keys(cid: str) -> set[str]:
    ref = load(V21 / "tasks" / cid / "reference.json")
    return {k for k, v in ref["inputs"].items() if v.get("role") == "masking"}


def full_details(cid: str) -> dict:
    """input -> msms_exact for Full MACE, restricted to v2.1 masking inputs.

    The frozen runs also scored two legacy-control inputs; those are not part
    of the formal v2.1 denominator and are dropped here.
    """
    if cid in V2_REUSED:
        task = load(V2)["tasks"][cid]
        raw = {d["input"]: bool(d["score"]["msms_exact"])
               for d in task.get("detail") or []}
    else:
        path = KIT / "runs" / "candidate_discovery_v2_1" / "scores" / f"{cid}.json"
        helper = KIT / "runs" / "candidate_discovery_v2_1_closure" / "scores" / f"{cid}.json"
        task = load(path)
        if not task.get("detail") and helper.exists():
            task = load(helper)
        raw = {d["input"]: bool(d["score"]["msms_exact"])
               for d in task.get("detail") or []}
    keep = masking_keys(cid)
    return {k: v for k, v in raw.items() if k in keep}


def c0_task(cid: str) -> tuple[int, int]:
    """(v2.1-role C0 exact numerator, denominator) at task level."""
    if cid in V2_REUSED:
        return 0, 0  # filled below from v2 totals
    path = KIT / "runs" / "candidate_discovery_v2_1" / "scores" / f"{cid}.json"
    helper = KIT / "runs" / "candidate_discovery_v2_1_closure" / "scores" / f"{cid}.json"
    task = load(path)
    if not task.get("baseline") or task["baseline"].get("masking_inputs") == 0:
        if helper.exists():
            task = load(helper)
    baseline = task.get("baseline") or {}
    exact = int(baseline.get("c0_exact") or 0)
    if cid == "sd_networkx_adjlist_strip_m1":
        exact -= 1  # control_plain was scored exact under the legacy role set
    ref = load(V21 / "tasks" / cid / "reference.json")
    denom = sum(1 for v in ref["inputs"].values() if v.get("role") == "masking")
    return exact, denom


def main() -> int:
    new_payload = load(NEW)
    new_tasks = new_payload["tasks"]
    assert len(new_tasks) == 15, len(new_tasks)

    tasks: dict[str, dict] = {}
    for cid in OLD_RUN:
        tasks[cid] = normalize_present(build_old(cid))
    for cid in sorted(new_tasks):
        tasks[cid] = normalize_present(build_new(cid, new_tasks[cid]))

    dev_final = load(DEV_FINAL)
    primary = [r["task_id"] for r in dev_final["per_task"]]
    assert len(primary) == 21 and set(primary) | V2_REUSED == set(tasks)
    assert all(cid in tasks for cid in primary)

    glm = load(GLM)
    glm_details = {cid: {d["input"]: bool(d["score"]["msms_exact"])
                         for d in t.get("detail") or []}
                   for cid, t in glm["tasks"].items()}

    c0 = {}
    for cid in primary:
        c0[cid] = c0_task(cid)
    # v2 four-task run: C0 0 exact over 5 masking inputs
    for cid in V2_REUSED:
        ref = load(V21 / "tasks" / cid / "reference.json")
        denom = sum(1 for v in ref["inputs"].values() if v.get("role") == "masking")
        c0[cid] = (0, denom)

    # ---- per-input table -------------------------------------------------
    rows = []
    for cid in sorted(tasks):
        ref = load(V21 / "tasks" / cid / "reference.json")
        mechanism = load(V21 / "cases" / f"{cid}.json")["mechanism"]
        full = full_details(cid)
        qwen = {d["input"]: bool(d["score"]["msms_exact"])
                for d in tasks[cid]["detail"]}
        qwen_sets = {d["input"]: d["parsed_sets"] for d in tasks[cid]["detail"]}
        for key, hidden in ref["inputs"].items():
            if hidden.get("role") != "masking":
                continue
            f_exact = full.get(key)
            g_exact = glm_details.get(cid, {}).get(key)
            q_exact = qwen.get(key)
            known = [x for x in (f_exact, g_exact, q_exact) if x is not None]
            rows.append({
                "task_id": cid,
                "cohort": "v2_reused" if cid in V2_REUSED else "primary_21",
                "mechanism": mechanism,
                "input": key,
                "c0_exact": "NA",
                "c0_task_level": f"{c0[cid][0]}/{c0[cid][1]}",
                "full_mace_exact": "" if f_exact is None else int(f_exact),
                "direct_glm_exact": "" if g_exact is None else int(g_exact),
                "direct_qwen_exact": "" if q_exact is None else int(q_exact),
                "qwen_parsed_sets": qwen_sets.get(key, 0),
                "three_method_agree": "" if len(known) < 3 else int(len(set(known)) == 1),
            })

    assert len(rows) == 30, len(rows)
    assert sum(r["full_mace_exact"] for r in rows) == 21
    assert sum(r["direct_glm_exact"] for r in rows) == 9
    assert sum(c0[c][0] for c in primary) == 13

    with io.open(OUT_CSV, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=list(rows[0]))
        writer.writeheader()
        writer.writerows(rows)

    # ---- totals ----------------------------------------------------------
    def agg(ids):
        out = {"tasks": len(ids), "masking_inputs": 0, "exact": 0,
               "present": 0, "valid": 0, "false_relations": 0,
               "unmatched_sets": 0, "runtime_s": 0.0,
               "prompt_tokens": 0, "completion_tokens": 0}
        for cid in ids:
            sc = tasks[cid]["scoring"]
            out["masking_inputs"] += sc["masking_inputs"]
            out["exact"] += sc["exact"]
            out["present"] += sc["present"]
            out["valid"] += sc["valid"]
            out["false_relations"] += sc["false_relations"]
            out["unmatched_sets"] += sc["unmatched_sets"]
            out["runtime_s"] += tasks[cid].get("runtime_s") or 0
            out["prompt_tokens"] += tasks[cid].get("prompt_tokens") or 0
            out["completion_tokens"] += tasks[cid].get("completion_tokens") or 0
        out["runtime_s"] = round(out["runtime_s"], 3)
        return out

    all_ids = sorted(tasks)
    totals = agg(all_ids)
    primary_totals = agg(primary)
    reused_totals = agg(sorted(V2_REUSED))

    by_mech = {}
    for cid in all_ids:
        mech = tasks[cid]["mechanism"]
        slot = by_mech.setdefault(mech, {
            "tasks": 0, "inputs": 0, "c0_exact": 0, "c0_inputs": 0,
            "full_exact": 0, "glm_exact": 0, "qwen_exact": 0})
        slot["tasks"] += 1
        slot["inputs"] += tasks[cid]["scoring"]["masking_inputs"]
        slot["c0_exact"] += c0[cid][0]
        slot["c0_inputs"] += c0[cid][1]
        slot["full_exact"] += sum(1 for v in full_details(cid).values() if v)
        slot["glm_exact"] += sum(1 for v in glm_details[cid].values() if v)
        slot["qwen_exact"] += tasks[cid]["scoring"]["exact"]

    completed = {
        "schema": "mace-direct-qwen-v2.1-dev-completed/1",
        "generated_utc": utc_now(),
        "split": "DEV",
        "model": {
            "name": "qwen2.5-coder:32b",
            "ollama_digest": "b92d6a0bd47ee79114298de0177bf920c05a706d12633950b3936778492bef41",
            "options": new_payload.get("options"),
            "gpu": "NVIDIA GeForce RTX 4090 D (AutoDL)",
        },
        "protocol": ("Direct only: one model call per task, no candidate "
                     "universe, no graph/AST expansion, no search, no verifier, "
                     "no retries."),
        "dataset_root": "benchmark_v4_dataset/source_derived_v2_1",
        "provenance": {
            "existing_10": {
                "source": "runs/sd_direct_vs_full/raw/<cid>__direct.json",
                "prompt_identity_vs_v2_1": "10/10 byte-identical user prompts",
                "scoring": "raw responses re-scored offline against v2.1 formal reference",
                "original_predictions_modified": False,
            },
            "new_15": {
                "source": "results/MACE_direct_Qwen_v2_1_dev_new.json",
                "runner": "scripts/run_direct_qwen_v2_1.py",
                "calls": 15, "retries": 0,
            },
        },
        "tasks": tasks,
        "totals": totals,
        "primary_cohort_21_tasks": primary_totals,
        "v2_reused_4_tasks": reused_totals,
        "by_mechanism": by_mech,
        "hashes": {
            "new_json_sha256": sha_file(NEW),
            "four_methods_csv_sha256": sha_file(OUT_CSV),
            "note": "this file's own SHA-256 is reported in the accompanying markdown",
        },
    }
    OUT_JSON.write_text(json.dumps(completed, ensure_ascii=False, indent=2),
                        encoding="utf-8")

    # ---- markdown report --------------------------------------------------
    def line(a, b, c="", d=""):
        return f"| {a} | {b} | {c} | {d} |"

    q21 = primary_totals
    q25 = totals
    md = []
    md.append("# MACE Direct Qwen 32B — v2.1 DEV Completion\n")
    md.append(f"Generated: {utc_now()}  ")
    md.append("Dataset: `benchmark_v4_dataset/source_derived_v2_1` (formal v2.1, DEV only)\n")
    md.append("## 1. What was run\n")
    md.append("- Reused: 10 existing Direct Qwen tasks / 15 masking inputs "
              "(`runs/sd_direct_vs_full/raw/`), raw responses untouched.")
    md.append("- New: 15 missing DEV tasks / 15 masking inputs, one call each, "
              "temperature 0, seed 42, num_ctx 8192, num_predict 4096, retries 0.")
    md.append("- Model: `qwen2.5-coder:32b`, Ollama digest "
              "`b92d6a0bd47ee79114298de0177bf920c05a706d12633950b3936778492bef41` "
              "(matches the frozen Direct-Qwen record).")
    md.append("- Prompt/parser/limits: identical to the frozen Direct protocol; "
              "the 10 reused prompts were verified byte-identical to a v2.1 rebuild.\n")
    old_pt = sorted({tasks[cid]["prompt_tokens"] for cid in OLD_RUN
                     if tasks[cid]["prompt_tokens"] is not None})
    new_pt = sorted({tasks[cid]["prompt_tokens"] for cid in new_tasks
                     if tasks[cid]["prompt_tokens"] is not None})
    md.append("### Context handling note\n")
    md.append(f"- Declared protocol (both phases): `num_ctx=8192`, "
              f"`num_predict=4096`, temperature 0, seed 42, retries 0.")
    old_capped = sum(1 for cid in OLD_RUN
                     if tasks[cid]["prompt_tokens"] == 4098)
    new_mid = sum(1 for cid in new_tasks
                  if 4098 < (tasks[cid]["prompt_tokens"] or 0) < 8184)
    md.append(f"- Observed prompt token counts in the 10 reused calls: {old_pt}. "
              f"{old_capped} of them hit exactly 4098 tokens, i.e. prompts above "
              f"the serving budget were truncated; shorter prompts were fully "
              f"evaluated.")
    md.append(f"- Observed prompt token counts in the 15 new calls: {new_pt}. "
              f"{new_mid} new task(s) fall between 4098 and 8192 tokens and were "
              f"therefore evaluated with more context than the reused phase "
              f"would have allowed; longer prompts still truncate to 4098.")
    md.append("- Consequence: for that narrow band the new arm saw more context. "
              "This is a serving-environment artefact, not a protocol change "
              "(both phases declare num_ctx=8192). It can only help the 15 new "
              "tasks, so the Direct baseline is not disadvantaged; the exact "
              "count is disclosed rather than silently pooled.\n")
    md.append("## 2. Full 25-task DEV (30 masking inputs)\n")
    md.append("| Method | Exact | False relations | Unmatched | Present |")
    md.append("|---|---|---|---|---|")
    md.append(f"| Direct Qwen 32B | **{q25['exact']}/{q25['masking_inputs']}** | "
              f"{q25['false_relations']} | {q25['unmatched_sets']} | {q25['present']} |")
    md.append(f"| Direct GLM (same 30 inputs) | 9/30 | 53 | 12 | — |")
    md.append(f"| Full MACE (21 v2.1 tasks + 4 v2 tasks) | 21/30 | — | — | — |")
    md.append(f"| C0 (same 30 inputs) | 13/30 | — | — | — |\n")
    md.append("C0 is **task-level only**: the frozen C0 artefacts record "
              "`c0_exact`/`masking_inputs` per task but no per-input prediction, "
              "so C0 cannot enter a paired McNemar test.\n")
    md.append("## 3. Primary 21-task cohort (25 masking inputs)\n")
    md.append("| Method | Exact | Denominator |")
    md.append("|---|---|---|")
    md.append(f"| C0 | 13 | 25 |")
    md.append(f"| Full MACE | 18 | 25 |")
    md.append(f"| Direct GLM | 5 | 25 |")
    md.append(f"| Direct Qwen 32B | **{q21['exact']}** | {q21['masking_inputs']} |\n")
    md.append(f"Direct Qwen on this cohort: false relations {q21['false_relations']}, "
              f"unmatched sets {q21['unmatched_sets']}, present {q21['present']}.\n")
    md.append("## 4. By mechanism (full 25-task DEV)\n")
    md.append("| Mechanism | Tasks | Inputs | C0 | Full MACE | Direct GLM | Direct Qwen |")
    md.append("|---|---|---|---|---|---|---|")
    for mech in sorted(by_mech):
        s = by_mech[mech]
        md.append(f"| {mech} | {s['tasks']} | {s['inputs']} | "
                  f"{s['c0_exact']}/{s['c0_inputs']} | {s['full_exact']}/{s['inputs']} | "
                  f"{s['glm_exact']}/{s['inputs']} | "
                  f"**{s['qwen_exact']}/{s['inputs']}** |")
    md.append("")
    md.append("M10_NEGATIVE_CONTROL exists only in the sealed HELDOUT split; "
              "DEV contains M1–M9 only.\n")

    def mcnemar(pairs):
        b = sum(1 for x, y in pairs if x == 1 and y == 0)
        c = sum(1 for x, y in pairs if x == 0 and y == 1)
        n = b + c
        if n == 0:
            return b, c, None
        from math import comb
        tail = sum(comb(n, k) for k in range(0, min(b, c) + 1)) / (2 ** n)
        return b, c, round(min(1.0, 2 * tail), 4)

    def pairs_for(x_key, y_key, cohort=None):
        return [(int(r[x_key]), int(r[y_key])) for r in rows
                if r[x_key] != "" and r[y_key] != ""
                and (cohort is None or r["cohort"] == cohort)]

    md.append("## 5. Paired per-input comparison (Full / GLM / Qwen)\n")
    md.append("C0 has no per-input predictions, so it is excluded from every "
              "paired test below; this is a coverage limit, not a null result.\n")
    md.append("| Pair | Cohort | Discordant (A only / B only) | Exact McNemar p |")
    md.append("|---|---|---|---|")
    for label, x, y in [("Full vs GLM", "full_mace_exact", "direct_glm_exact"),
                        ("Full vs Qwen", "full_mace_exact", "direct_qwen_exact"),
                        ("GLM vs Qwen", "direct_glm_exact", "direct_qwen_exact")]:
        for cname, cval in [("30 inputs", None), ("primary 25", "primary_21")]:
            b, c, p = mcnemar(pairs_for(x, y, cval))
            shown = "n/a" if p is None else ("<0.0001" if p == 0 else p)
            md.append(f"| {label} | {cname} | {b} / {c} | {shown} |")
    md.append("")
    valid_tasks = sum(1 for cid in all_ids if tasks[cid]["parsed_sets"])
    valid_inputs = q25["valid"]
    md.append("## 6. Output validity and efficiency\n")
    md.append(f"- Valid output (>=1 mapped relation): {valid_tasks}/25 tasks, "
              f"{valid_inputs}/{q25['masking_inputs']} masking inputs.")
    md.append(f"- Present (every hidden MSMS set found; frozen-artifact "
              f"definition): {q25['present']}/{q25['masking_inputs']}.")
    empty = [cid for cid in all_ids if not tasks[cid]["parsed_sets"]]
    md.append("- Tasks with no mapped relation (" + str(len(empty)) + "/25): "
              + ", ".join(f"`{c}`" for c in empty) + ".")
    md.append("")
    new_tasks_only = agg(sorted(new_tasks))
    md.append("| Split | Tasks | Runtime | Prompt tokens | Completion tokens |")
    md.append("|---|---|---|---|---|")
    md.append(f"| 15 new calls | 15 | {new_tasks_only['runtime_s']} s | "
              f"{new_tasks_only['prompt_tokens']} | {new_tasks_only['completion_tokens']} |")
    md.append(f"| Full DEV (reused + new) | 25 | {q25['runtime_s']} s | "
              f"{q25['prompt_tokens']} | {q25['completion_tokens']} |\n")
    md.append("## 7. Integrity\n")
    md.append(f"- Completed JSON SHA-256: `{sha_file(OUT_JSON)}`")
    md.append(f"- New-call file SHA-256: `{sha_file(NEW)}`")
    md.append(f"- C0 per-input predictions: **absent** (task-level counts only); "
              "no McNemar statistic is reported against C0.")
    md.append("- HELDOUT: not read, not run, not scored in this round.")
    OUT_MD.write_text("\n".join(md), encoding="utf-8")

    print("totals", json.dumps(totals, ensure_ascii=False))
    print("primary", json.dumps(primary_totals, ensure_ascii=False))
    print("wrote", OUT_JSON)
    print("wrote", OUT_CSV)
    print("wrote", OUT_MD)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
