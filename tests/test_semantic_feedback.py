"""CPU-only tests for MACE semantic feedback v1.

No model is called here.  The tests pin the properties that make the new mode
different from the old semantic protocol:

* MSMS/MMBS are explicit, separate candidate lists;
* a control statement is context, never a deletable operation;
* a new operation is accepted only after AST identity mapping;
* the pilot singleton-MMBS check does not fall through the size >= 2 guard;
* feedback carries the real failed input, not a hidden reference;
* ``U_graph`` is never pruned and ``U_qwen`` is reported separately.
"""
from __future__ import annotations

import json

from open_ops.semantic_relations import SourceIndex
from scripts.run_semantic_feedback import (
    build_correction_prompt, build_feedback_prompt, candidate_hypotheses,
    map_candidate, parse_candidates, pilot_feedback_entry, universes_from,
    verify_mmbs, verify_msms, verify_real_candidate,
)
from scripts.run_semantic_relation_discovery import pilot_context


SOURCE = """\
def program(x, c, d):
    v = x
    v = v + 6  # TARGET
    if c == 0:
        v = v // 6 * 6
    if d == 0:
        v = v // 7 * 7
    return v
"""

TARGET = {"line": 3, "text": "v = v + 6"}


def _index() -> SourceIndex:
    return SourceIndex.from_source("<program>", SOURCE)


def _graph():
    return [
        {"id": "op_L4_C4_if", "file": "<program>", "first_line": 4,
         "last_line": 5, "line": 4, "kind": "if", "node_type": "If",
         "code": "if c == 0:\n        v = v // 6 * 6"},
        {"id": "op_L6_C4_if", "file": "<program>", "first_line": 6,
         "last_line": 7, "line": 6, "kind": "if", "node_type": "If",
         "code": "if d == 0:\n        v = v // 7 * 7"},
    ]


# ---------------------------------------------------------------------------
# Parsing
# ---------------------------------------------------------------------------
def test_parse_explicit_msms_and_mmbs_lists():
    parsed = parse_candidates(json.dumps({
        "msms_candidates": [{"operations": [{"line": 4}],
                             "condition": "c == 0"}],
        "mmbs_candidates": [{"operations": [{"line": 6}],
                             "condition": True}],
        "notes": "n",
    }))
    assert parsed["format"] == "structured"
    assert len(parsed["msms"]) == 1
    assert len(parsed["mmbs"]) == 1
    assert parsed["notes"] == "n"


def test_parse_rejects_unparseable_text():
    parsed = parse_candidates("not json at all")
    assert parsed["format"] == "unparseable"
    assert parsed["msms"] == []


# ---------------------------------------------------------------------------
# Granularity
# ---------------------------------------------------------------------------
def test_new_control_statement_is_context_not_a_deletable_operation():
    mapped = map_candidate(
        {"operations": [{"file": "<program>", "line": 4, "text": "if c == 0:"}]},
        role="msms", index=_index(), graph_ops=[], style="v3",
        exclude_lines=[3])
    assert mapped["status"] == "rejected"
    assert mapped["reason"] == "no_executable_operation"
    assert [op["first_line"] for op in mapped["control_context"]] == [4]


def test_control_is_stripped_but_a_real_assignment_survives():
    mapped = map_candidate(
        {"operations": [
            {"file": "<program>", "line": 4, "text": "if c == 0:"},
            {"file": "<program>", "line": 5, "text": "v = v // 6 * 6"},
        ]},
        role="msms", index=_index(), graph_ops=[], style="v3",
        exclude_lines=[3])
    assert mapped["status"] == "mapped"
    assert [op["first_line"] for op in mapped["ops"]] == [5]
    assert [op["first_line"] for op in mapped["control_context"]] == [4]
    assert mapped["ops"][0]["in_graph"] is False


def test_graph_operation_is_not_pruned_or_treated_as_context():
    mapped = map_candidate(
        {"operations": [{"file": "<program>", "line": 4, "text": "if c == 0:"}]},
        role="msms", index=_index(), graph_ops=_graph(), style="pilot",
        exclude_lines=[3])
    assert mapped["status"] == "mapped"
    assert mapped["ops"][0]["id"] == "op_L4_C4_if"
    assert mapped["ops"][0]["in_graph"] is True
    assert mapped["control_context"] == []


def test_ubiquitous_duplicate_citation_is_deduplicated():
    mapped = map_candidate(
        {"operations": [
            {"file": "<program>", "line": 4, "text": "if c == 0:"},
            {"file": "<program>", "line": 5, "text": "v = v // 6 * 6"},
        ]},
        role="msms", index=_index(), graph_ops=_graph(), style="pilot",
        exclude_lines=[3])
    assert mapped["status"] == "mapped"
    assert [op["id"] for op in mapped["ops"]] == ["op_L4_C4_if"]


def test_universes_keep_graph_and_report_qwen_separately():
    source = "def f(a):\n    if a:\n        b = 1\n    c = 2\n    return c\n"
    index = SourceIndex.from_source("<program>", source)
    graph = [{"id": "g_if", "file": "<program>", "first_line": 2,
              "last_line": 3, "line": 2, "kind": "if", "node_type": "If",
              "code": "if a:\n        b = 1"}]
    new = map_candidate(
        {"operations": [{"file": "<program>", "line": 4, "text": "c = 2"}]},
        role="msms", index=index, graph_ops=graph, style="v3",
        exclude_lines=[])
    assert new["status"] == "mapped"
    assert new["ops"][0]["in_graph"] is False
    universes = universes_from([new], graph)
    assert {op["id"] for op in universes["U_graph"]} == {"g_if"}
    assert {op["id"] for op in universes["U_qwen"]} == {new["ops"][0]["id"]}
    assert {op["id"] for op in universes["U_union"]} == {
        "g_if", new["ops"][0]["id"]}


def test_hypotheses_are_filtered_by_the_claimed_universe():
    candidates = [{
        "role": "msms", "status": "mapped",
        "ops": [{"id": "op_L4_C4_if"}], "condition": "c == 0"}]
    assert candidate_hypotheses(candidates)["msms"][0]["ops"] == (
        "op_L4_C4_if",)
    assert candidate_hypotheses(candidates, allowed={"other"})["msms"] == []


# ---------------------------------------------------------------------------
# Pilot verification
# ---------------------------------------------------------------------------
def test_ctrl02_cooperative_condition_reports_the_real_false_accept():
    context = pilot_context("ctrl_02")
    verifier = context["verifier"]
    ops = [op for op in context["graph_ops"] if op["first_line"] in (4, 6)]
    candidate = {"role": "msms", "status": "mapped", "ops": ops,
                 "condition": "c == 0 and d == 0", "control_context": []}
    result = verify_msms(candidate, verifier)
    assert result["status"] == "FALSE"
    assert result["condition"]["false_accept"] == ["case_0020"]
    candidate["verification"] = result
    entry = pilot_feedback_entry(candidate, verifier)
    failed = entry["condition"]["failed_inputs"]
    assert failed[0]["case_id"] == "case_0020"
    assert failed[0]["args"] == {"x": 6, "c": 0, "d": 0}
    assert failed[0]["actual_relation_holds"] is False


def test_singleton_mmbs_uses_its_own_check_not_the_size_two_guard():
    context = pilot_context("ctrl_02")
    verifier = context["verifier"]
    candidate = {"role": "mmbs", "status": "mapped",
                 "ops": [context["graph_ops"][0]], "condition": "c == 0",
                 "control_context": []}
    result = verify_mmbs(candidate, verifier)
    assert result["status"] in ("VERIFIED", "INCOMPLETE", "FALSE")
    assert result["checks"]["disabling_set_exposes"] is True
    # The old API would reject this solely for having fewer than two
    # operations.  The custom check must still score the condition.
    old = verifier.verify_relation({
        "operations": [{"line": 4}], "kind": "coexisting",
        "input": {"x": 1, "c": 0, "d": 0}, "condition": "c == 0"})
    assert old["status"] == "FALSE"
    assert "at least two" in old["reason"]
    assert result.get("condition", {}).get("status") in ("VALID", "ABSENT")


# ---------------------------------------------------------------------------
# Real-task verification
# ---------------------------------------------------------------------------
def test_real_candidate_is_confirmed_only_by_the_executor_sets():
    candidate = {"role": "msms", "status": "mapped",
                 "ops": [{"id": "a"}, {"id": "b"}]}
    arm = {"inputs": [
        {"input": {"x": 1}, "searched": True, "complete": True,
         "msms_ids": [["a", "b"]]},
        {"input": {"x": 2}, "searched": False},
    ]}
    result = verify_real_candidate(candidate, arm, "msms")
    assert result["status"] == "SET_CONFIRMED"
    assert result["confirmed_inputs"] == [{"x": 1}]


def test_real_candidate_without_a_set_is_not_confirmed():
    candidate = {"role": "mmbs", "status": "mapped",
                 "ops": [{"id": "a"}]}
    arm = {"inputs": [
        {"input": {"x": 1}, "searched": True, "complete": True,
         "mmbs_ids": []},
    ]}
    result = verify_real_candidate(candidate, arm, "mmbs")
    assert result["status"] == "NOT_CONFIRMED"


# ---------------------------------------------------------------------------
# Prompt and leakage
# ---------------------------------------------------------------------------
def test_feedback_prompt_does_not_carry_hidden_truth_terms():
    prompt = build_feedback_prompt(
        "ctrl_02", SOURCE, TARGET, ["<program>"],
        {"args": [{"name": "x"}], "cases": [{"x": 1}]},
        _graph())
    for forbidden in ("absorber_sets", "coexisting_unmasking_sets",
                      "attribution.json", "per_case", "HIDDEN"):
        assert forbidden not in prompt
    assert "msms_candidates" in prompt
    assert "mmbs_candidates" in prompt
    assert "control context" in prompt


def test_correction_prompt_contains_the_real_counterexample():
    context = pilot_context("ctrl_02")
    verifier = context["verifier"]
    ops = [op for op in context["graph_ops"] if op["first_line"] in (4, 6)]
    candidate = {"role": "msms", "status": "mapped", "ops": ops,
                 "condition": "c == 0 and d == 0", "control_context": []}
    result = verify_msms(candidate, verifier)
    candidate["verification"] = result
    entry = pilot_feedback_entry(candidate, verifier)
    prompt = build_correction_prompt(
        "initial prompt", '{"msms_candidates": []}', [entry])
    assert "case_0020" in prompt
    assert '"x": 6' in prompt
    assert "false_accept" in prompt
    assert "only revision" in prompt
