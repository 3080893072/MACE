"""Aggregate the frozen v2.1 DEV run into CSV + report fields.

Reads only the v2.1 result JSON and public/derived reference files.  Does not
call the model and does not modify the dataset, the v2 result, or any prompt.
"""
from __future__ import annotations

import csv
import hashlib
import importlib.util
import io
import json
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
RESULT = KIT / "results" / "MACE_candidate_discovery_v2_1_dev.json"
CSV_OUT = KIT / "results" / "MACE_candidate_discovery_v2_1_per_task.csv"
V2 = KIT / "results" / "MACE_candidate_discovery_v2.json"
SD = KIT / "benchmark_v4_dataset" / "source_derived"

spec = importlib.util.spec_from_file_location(
    "cd21", KIT / "scripts" / "run_candidate_discovery_v2_1.py")
cd21 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cd21)


def load(path: Path):
    return json.load(io.open(path, encoding="utf-8"))


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


data = load(RESULT)
v2 = load(V2)
v2_sha = sha256(V2)

# Tasks whose causal evaluation could not run: src-layout packages put the
# importable package under <variant>/src, while SDExecutor puts <variant> on
# sys.path.  The probe therefore observes the installed package, plus == minus
# for every input and a_executes is false.  Localised only; not refactored.
UNEVALUABLE = {
    "sd_attrs_asdict_loop_m7",
    "sd_humanize_filesize_gnu_m5",
}

rows = []
coverage: dict[str, dict] = {}
novel_total = novel_correct = novel_wrong = 0
expanded_tasks = 0
expanded_correct_tasks = 0
better = equal = worse = 0
evaluated_tasks = 0

for cid, x in data["tasks"].items():
    mech = x["mechanism"].split("_")[0]
    ref = cd21.reference_for(cid)
    enum = load(SD / "evidence" / cid / "enumeration.json")
    spans = cd21.block_spans(enum)
    byid = {op["id"]: op for op in x["u_union"]}

    ref_masking = [k for k, v in ref["inputs"].items() if v["role"] == "masking"]
    target_blocks: set[str] = set()
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
    if cid in UNEVALUABLE:
        status = "INCOMPLETE"
        note = ("no executable public masking input: src-layout variant import "
                "resolved to the installed package (harness path defect); "
                "C0 and v2.1 both unevaluable")
        c0_evaluable = False
    else:
        status = "OK"
        c0_evaluable = True
        note = ""
        evaluated_tasks += 1
        if cid == "sd_pygments_latex297_italic":
            note = ("SEARCH_INCOMPLETE on 3/3 inputs (16/64 subsets per input; "
                    "budget not expanded per protocol); 0/2 is a budget-limited "
                    "negative, not a proven absence of a masking set")
        if s["exact"] > c0e:
            better += 1
        elif s["exact"] == c0e:
            equal += 1
        else:
            worse += 1

    m = coverage.setdefault(mech, {
        "mechanism": x["mechanism"], "tasks_total": 0,
        "tasks_evaluable": 0, "tasks_unevaluable": 0,
        "inputs": 0, "exact": 0, "present": 0, "c0_exact": 0,
        "tasks_exact_all": 0})
    m["tasks_total"] += 1
    if cid in UNEVALUABLE:
        m["tasks_unevaluable"] += 1
    else:
        m["tasks_evaluable"] += 1
        m["inputs"] += scored
        m["exact"] += s["exact"]
        m["present"] += s["present"]
        m["c0_exact"] += c0e
        if scored and s["exact"] == scored:
            m["tasks_exact_all"] += 1

    stats = x["call"].get("stats") or {}
    incomplete = sum(
        1 for v in x["search"].values() if not v.get("complete"))
    cooperative = ""
    alternative = ""
    if mech in ("M2", "M3") and cid not in UNEVALUABLE:
        cooperative = f"{s['exact']}/{scored}"
    if mech == "M4" and cid not in UNEVALUABLE:
        alternative = f"{s['exact']}/{scored}"

    if cid in UNEVALUABLE:
        comparison = "not_evaluable"
    elif not c0_evaluable:
        comparison = "not_evaluable"
    elif s["exact"] > c0e:
        comparison = "better"
    elif s["exact"] == c0e:
        comparison = "equal"
    else:
        comparison = "worse"

    rows.append({
        "task_id": cid,
        "mechanism": x["mechanism"],
        "status": status,
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
        "cooperative_accuracy": cooperative,
        "alternative_accuracy": alternative,
        "probe_count": x["cost"]["probe_executions"],
        "runtime_s": x["cost"]["wall_seconds"],
        "prompt_tokens": stats.get("prompt_tokens"),
        "completion_tokens": stats.get("completion_tokens"),
        "c0_exact": c0e,
        "c0_false": x["baseline"]["c0_false"] or 0,
        "c0_scored_inputs": scored if c0_evaluable else 0,
        "comparison_vs_c0": comparison,
        "search_incomplete_inputs": incomplete,
    })

assert len(rows) == 21


def _row(cid):
    return next(r for r in rows if r["task_id"] == cid)


for cid, x in data["tasks"].items():
    r = _row(cid)
    x["evaluation_status"] = r["status"]
    if r["status"] == "INCOMPLETE":
        x.setdefault("model_call_status", x.get("status", "OK"))
        x["status"] = "INCOMPLETE"
    x["evaluation_note"] = r["completeness_note"]
    x["novel_qwen_correct"] = r["novel_correct"]
    x["novel_qwen_wrong"] = r["novel_wrong"]
    x["comparison_vs_c0"] = r["comparison_vs_c0"]
    x["cooperative_accuracy"] = r["cooperative_accuracy"]
    x["alternative_accuracy"] = r["alternative_accuracy"]
    x["prompt_tokens"] = r["prompt_tokens"]
    x["completion_tokens"] = r["completion_tokens"]

columns = list(rows[0])
CSV_OUT.parent.mkdir(parents=True, exist_ok=True)
with open(CSV_OUT, "w", encoding="utf-8", newline="") as fh:
    w = csv.DictWriter(fh, fieldnames=columns)
    w.writeheader()
    w.writerows(rows)

# ---- aggregate + report fields in the result JSON ----------------------
tot = data["totals"]
tot.update({
    "tasks_total": 21,
    "tasks_completed": 21 - len(UNEVALUABLE),
    "tasks_incomplete": len(UNEVALUABLE),
    "masking_inputs_evaluated": sum(r["scored_masking_inputs"] for r in rows),
    "c0_exact_evaluated": sum(r["c0_exact"] for r in rows),
    "new_exact_evaluated": sum(r["msms_exact"] for r in rows),
    "qwen_novel_candidates": novel_total,
    "qwen_novel_correct": novel_correct,
    "qwen_novel_wrong": novel_wrong,
    "tasks_with_qwen_expansion": expanded_tasks,
    "tasks_with_correct_expansion": expanded_correct_tasks,
    "tasks_better_than_c0": better,
    "tasks_equal_to_c0": equal,
    "tasks_worse_than_c0": worse,
    "cooperative_exact": sum(r["msms_exact"] for r in rows
                             if r["mechanism"].startswith(("M2_", "M3_"))),
    "cooperative_inputs": sum(r["scored_masking_inputs"] for r in rows
                              if r["mechanism"].startswith(("M2_", "M3_"))),
    "alternative_exact": sum(r["msms_exact"] for r in rows
                             if r["mechanism"].startswith("M4_")),
    "alternative_inputs": sum(r["scored_masking_inputs"] for r in rows
                              if r["mechanism"].startswith("M4_")),
})

data["coverage_by_mechanism"] = coverage
data["baseline_scope"] = {
    "compared_methods": ["A_role_separated_C0", "B_full_mace_plus_candidate_discovery_v2"],
    "direct_qwen_32b": (
        "not part of this round's comparison.  totals.direct_exact (0) and "
        "totals.old_full_exact (5) are legacy values from the earlier 10-task "
        "direct-vs-full run, available only for 6 formal tasks; they are kept "
        "for provenance and must not be compared with the 21-task totals."),
}
data["qwen_expansion"] = {
    "tasks_with_qwen_expansion": expanded_tasks,
    "tasks_with_correct_expansion": expanded_correct_tasks,
    "novel_candidates": novel_total,
    "novel_correct_by_block_projection": novel_correct,
    "novel_wrong_by_block_projection": novel_wrong,
    "precision": round(novel_correct / novel_total, 3) if novel_total else None,
}
data["harness_finding"] = {
    "tasks": sorted(UNEVALUABLE),
    "root_cause": (
        "SDExecutor._run_probe puts the variant root on sys.path.  For "
        "src-layout packages (attrs, humanize) the importable package lives "
        "under <variant>/src/<pkg>, so the probe imported the installed "
        "package instead of the variant.  plus == minus for every input and "
        "a_executes() is false; no public masking input can be found."),
    "evidence": {
        "sd_attrs_asdict_loop_m7": (
            "in1/in2 plus == minus, a_executes=False; U_graph=0; "
            "C0 masking inputs=0"),
        "sd_humanize_filesize_gnu_m5": (
            "in1/in2/in3 plus == minus, a_executes=False; U_graph=0; "
            "C0 masking inputs=0"),
    },
    "scope": (
        "Only these two of the 21 tasks use a src/ layout; both methods "
        "(C0 and Full MACE + Candidate Discovery v2) are affected equally.  "
        "Localised once; no refactor performed, per protocol.  Both tasks are "
        "marked INCOMPLETE and excluded from accuracy denominators."),
}

frozen = ["sd_pygments_bbcode70_italic", "sd_pygments_bbcode64_color",
          "sd_pygments_groff73_italic", "sd_networkx_gexf448_slices"]
data["dataset"] = {
    "source_derived_dev_tasks": 25,
    "selected_for_v2_1": 21,
    "excluded_already_tested_by_v2": frozen,
    "heldout_read": False,
    "mechanisms_in_v2_1": sorted({x["mechanism"] for x in data["tasks"].values()}),
}

v2_bb = v2["tasks"]["sd_pygments_bbcode64_color"]
v2_nx = v2["tasks"]["sd_networkx_gexf448_slices"]
v2_groff = v2["tasks"]["sd_pygments_groff73_italic"]
data["special_tracking"] = {
    "note": "Reused from the frozen v2 result; these three tasks were not re-run in v2.1.",
    "bbcode64": {
        "v2_sha256": v2_sha,
        "u_graph": [o["id"] for o in v2_bb["u_graph"]],
        "u_qwen": [o["id"] for o in v2_bb["u_qwen"]],
        "hidden": {"U1": "lines 64-67", "U2": "lines 80-89"},
        "line_67": {
            "mapping": "U1 (confirmed minimal singleton)",
            "provenance": "qwen",
            "verdict": "correct",
            "reason": "restores the first colour close; confirmed by causal verification",
        },
        "line_71": {
            "mapping": "outside U1/U2 (stray)",
            "provenance": "C0 + qwen",
            "verdict": "false relation",
            "reason": "bold close is causally confirmed as a masking singleton on the probe but is not part of the hidden alternative path",
        },
        "line_88": {
            "mapping": "inside U2 (lines 80-89)",
            "provenance": "U_ast only; proposed by neither C0 nor qwen",
            "verdict": "omitted",
            "reason": ("qwen latched onto line 67 as the colour alternative and "
                       "never proposed the later self.styles override at 82-89. "
                       "Line 88 alone is also not minimal: the assignment at 89 "
                       "(or the guard at 82 plus 88-89) must travel with it. "
                       "Line 88 and the 88->89 dependency edge were both in the "
                       "prompt, so this is a reasoning/granularity miss, not "
                       "missing context."),
        },
        "score": v2_bb["scoring"],
    },
    "networkx448": {
        "v2_sha256": v2_sha,
        "hidden": {"U1": "lines 448-451"},
        "line_404": {
            "code": "edge_data = data.copy()",
            "provenance": "C0 only (not proposed by qwen)",
            "mapping": "outside U1; keep-alive operation",
            "verdict": "stray",
            "reason": ("deleting 404 leaves edge_data undefined downstream, so "
                       "the probe cannot return.  The keep-set search must retain "
                       "it to observe masking; {404,451} is confirmed but 404 "
                       "projects as a stray, making the answer non-exact."),
        },
        "line_451": {
            "code": "edge_data = self.add_slices(edge_element, edge_data) (guarded)",
            "provenance": "C0 + qwen",
            "mapping": "U1",
            "verdict": "correct leg",
        },
        "line_456": {
            "code": "edge_data = self.add_attributes(...)",
            "provenance": "C0 + qwen",
            "mapping": "outside U1; downstream",
            "verdict": "erroneous relation (rejected)",
            "reason": ("qwen claims shared-state compensation.  Verification: "
                       "{456} NOT_MASKED, {451,456} NOT_MASKED, "
                       "{404,451,456} NOT_MINIMAL.  It never masks A."),
        },
        "score": v2_nx["scoring"],
    },
    "groff73": {
        "v2_sha256": v2_sha,
        "hidden": {"U1,U2,U3": "three cooperative legs"},
        "v2_result": {
            "u_graph": [o["id"] for o in v2_groff["u_graph"]],
            "u_qwen": [o["id"] for o in v2_groff["u_qwen"]],
            "confirmed": v2_groff["verification"]["in1"]["confirmed"],
            "score": v2_groff["scoring"],
        },
        "stability_in_v2_1_m3": {
            "sd_docutils_ellipsis_m3": {
                "confirmed": ["docutils/utils/smartquotes.py:812-812",
                              "docutils/utils/smartquotes.py:815-815",
                              "docutils/utils/smartquotes.py:818-818"],
                "exact": "1/1",
            },
            "sd_docutils_language_tag_m3": {
                "confirmed": ["docutils/utils/__init__.py:706-706",
                              "docutils/utils/__init__.py:709-709",
                              "docutils/utils/__init__.py:712-712"],
                "exact": "1/1",
                "note": ("qwen proposed 706/709/712/715 as one set; strict "
                         "minimality removed 715; the verified minimal triple "
                         "projects exactly onto U1/U2/U3"),
            },
            "conclusion": "three-operation cooperative pattern 3/3 across Groff73 + the two v2.1 M3 tasks",
        },
    },
}

data["answers"] = {
    "q1_qwen_expanded_u": (
        "Yes, on 13/21 tasks (22 novel operations).  U_graph already covered "
        "the hidden blocks in 8 tasks, so recall did not change there; in 8 "
        "tasks Qwen added at least one operation inside the hidden family.  "
        "In 5 tasks the expansion added only wrong operations "
        "(backticks, smartquotes, latex297, style95, toml)."),
    "q2_new_candidates_correct": (
        "10/22 novel candidates fall inside a hidden MSMS block (45.5%).  "
        "12/22 are outside every hidden MSMS block.  Block projection is a "
        "span test, not a causal proof: 2 tasks (attrs, humanize) could not be "
        "causally verified at all."),
    "q3_beats_c0": (
        "Aggregate: 17/25 exact vs C0 12/25 on the same 25 evaluated masking "
        "inputs; false relations 5 vs 9 (4 fewer).  Per task: better in 6, "
        "equal in 12, worse in 1 (smartquotes_strip 0 vs 1), not evaluable in "
        "2.  So it is an improvement, not a uniform win."),
    "q4_cooperative_patterns": (
        "Stable.  Two-operation M2: 4/4 exact (coverage, educate_dashes, "
        "make_id_nonid, stupefy_emdash).  Three-operation M3: 2/2 exact "
        "(ellipsis, language_tag), and with frozen Groff73 that is 3/3 for "
        "the three-leg pattern.  Alternative-path M4: 1/1 (isort)."),
    "q5_failing_mechanisms": (
        "M6 cross-function state 0/2 and M9 exception fallback 0/3 both fail "
        "because C0 and Qwen stay inside A's function while the hidden block "
        "is in another method (latex 330-353, style95 126-138).  M1 has two "
        "residual failures: make_id_lower 0/2 (strict minimality left every "
        "candidate UNKNOWN) and smartquotes 0/1 (a probe artefact at line 277 "
        "is required to keep the probe returning, producing a stray).  M5/M7 "
        "each have one evaluated success and one unevaluable src-layout task."),
    "q6_freeze_and_heldout": (
        "Worth one HELDOUT confirmation, conditionally.  The v2 core never "
        "regressed on cooperative/alternative tasks and added +5 exact over C0, "
        "but the gain is concentrated in M2/M3/M4 and M1 tasks whose target "
        "block is single-line.  Do not claim general superiority.  Before "
        "HELDOUT, fix the one-line src-layout sys.path defect and re-evaluate "
        "attrs/humanize (no new Qwen call; reuse the recorded responses), and "
        "keep M6/M9 as known failures rather than tuning the prompt on them."),
}

RESULT.write_text(json.dumps(data, ensure_ascii=False, indent=2),
                  encoding="utf-8")
print("wrote", CSV_OUT)
print("wrote", RESULT)
print("csv sha256", sha256(CSV_OUT))
print("json sha256", sha256(RESULT))
