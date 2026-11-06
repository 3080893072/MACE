"""Tests for Qwen semantic relation discovery and AST proposal mapping.

The properties under test are the ones the round instruction makes
non-negotiable:

* a model proposal is accepted only through a real AST statement identity;
* ``U_graph``, ``U_qwen`` and ``U_union`` stay separate, and no graph
  operation is pruned;
* relations stay ``HYPOTHESIS`` until the causal search confirms them;
* masking relations become MSMS *kept* sets and MMBS *disabled* sets;
* an unexecutable proposal is reported, never silently dropped or executed;
* the pilot oracle preserves the three-valued masked/exposed semantics.
"""
from __future__ import annotations

import json

import pytest

from open_ops.pilot_oracle import PilotOracle
from open_ops.semantic_relations import (
    SourceIndex, build_prompt, build_universes, map_proposal,
    parse_semantic_hypotheses, relations_to_role_hypotheses, role_tuples)

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

GRAPH = [
    {"id": "op_L4_C4_if", "file": "<program>", "line": 4, "first_line": 4,
     "last_line": 5, "col": 4, "kind": "if", "code": "if c == 0:\n        v = v // 6 * 6"},
    {"id": "op_L6_C4_if", "file": "<program>", "line": 6, "first_line": 6,
     "last_line": 7, "col": 4, "kind": "if", "code": "if d == 0:\n        v = v // 7 * 7"},
]


def index() -> SourceIndex:
    return SourceIndex.from_source("<program>", SOURCE)


# ---------------------------------------------------------------------------
# Source mapping
# ---------------------------------------------------------------------------
def test_resolve_exact_line_and_span():
    resolved = index().resolve(4)
    assert resolved["status"] == "mapped"
    span = resolved["span"]
    assert (span.node_type, span.first_line, span.last_line) == ("If", 4, 5)


def test_resolve_uses_text_to_pick_the_right_statement():
    resolved = index().resolve(4, "if c == 0:")
    assert resolved["status"] == "mapped"
    assert resolved["span"].first_line == 4


def test_resolve_recovers_a_one_line_shift():
    resolved = index().resolve(5, "if c == 0:")
    assert resolved["status"] == "mapped"
    assert resolved["span"].first_line == 4
    assert resolved["line_shift"] == -1


def test_resolve_rejects_text_from_another_statement():
    resolved = index().resolve(4, "if zzz == 0:")
    assert resolved["status"] == "rejected"
    assert resolved["reason"] == "text_mismatch"


def test_resolve_rejects_the_target_line():
    resolved = index().resolve(3, "v = v + 6", exclude_lines=[3])
    assert resolved["status"] == "rejected"
    assert resolved["reason"] == "target_line"


def test_resolve_rejects_a_line_without_a_statement():
    assert index().resolve(999)["reason"] == "no_statement_at_line"


# ---------------------------------------------------------------------------
# Universes
# ---------------------------------------------------------------------------
def test_known_proposal_is_graph_and_new_proposal_is_qwen():
    universes = build_universes(
        GRAPH,
        [{"line": 4, "text": "if c == 0:"},
         {"line": 8, "text": "return v"}],
        index(), style="pilot", exclude_lines=[3])
    assert [op["id"] for op in universes["U_graph"]] == [
        "op_L4_C4_if", "op_L6_C4_if"]
    assert len(universes["U_qwen"]) == 1
    assert universes["U_qwen"][0]["id"].startswith("op_L8")
    assert len(universes["U_union"]) == 3
    # The graph universe is never pruned.
    assert {op["id"] for op in universes["U_graph"]} <= {
        op["id"] for op in universes["U_union"]}


def test_duplicate_new_proposal_is_recorded_once():
    universes = build_universes(
        GRAPH, [{"line": 8}, {"line": 8}], index(), style="pilot",
        exclude_lines=[3])
    assert len(universes["U_qwen"]) == 1
    assert universes["duplicates"] == [universes["U_qwen"][0]["id"]]


def test_mapping_failure_is_reported_not_ignored():
    universes = build_universes(
        GRAPH, [{"line": 4, "text": "if wrong == 0:"}], index(),
        style="pilot", exclude_lines=[3])
    assert universes["U_qwen"] == []
    assert universes["rejected"][0]["reason"] == "text_mismatch"


def test_v3_ids_use_the_frozen_file_line_convention():
    result = map_proposal({"file": "src/x.py", "line": 4},
                          index(), GRAPH, style="v3")
    # The index file does not match the proposal, so it is rejected rather
    # than silently remapped.
    assert result["status"] == "rejected"
    assert result["reason"] == "wrong_file"

    v3_index = SourceIndex.from_source("src/x.py", SOURCE)
    result = map_proposal({"file": "src/x.py", "line": 4},
                          v3_index, GRAPH, style="v3")
    assert result["status"] == "mapped"
    assert result["op"]["id"] == "src/x.py:4-5"


# ---------------------------------------------------------------------------
# Hypothesis parsing
# ---------------------------------------------------------------------------
def _parse(payload, graph=GRAPH):
    return parse_semantic_hypotheses(
        json.dumps(payload), index(), graph, style="pilot",
        exclude_lines=[3])


def test_independent_and_cooperative_relations_are_kept_as_hypotheses():
    parsed = _parse({"relations": [
        {"kind": "independent",
         "operations": [{"line": 4, "text": "if c == 0:"}],
         "condition": "c < 1"},
        {"kind": "cooperative",
         "operations": [{"line": 4, "text": "if c == 0:"},
                        {"line": 6, "text": "if d == 0:"}],
         "condition": "c < 1 and d < 1"},
    ]})
    assert parsed["format"] == "structured"
    assert [rel["kind"] for rel in parsed["relations"]] == [
        "independent", "cooperative"]
    assert all(rel["status"] == "HYPOTHESIS"
               for rel in parsed["relations"])
    assert parsed["relations"][1]["ops"] == [
        "op_L4_C4_if", "op_L6_C4_if"]


def test_fallback_and_coexisting_kinds_are_recognised():
    parsed = _parse({"relations": [
        {"kind": "fallback",
         "operations": [{"line": 4}, {"line": 6}]},
        {"kind": "coexisting",
         "operations": [{"line": 4}, {"line": 6}]},
    ]})
    assert [rel["kind"] for rel in parsed["relations"]] == [
        "fallback", "coexisting"]


def test_unknown_operation_rejects_the_whole_relation():
    parsed = _parse({"relations": [
        {"kind": "independent",
         "operations": [{"line": 4}, {"line": 999}]},
    ]})
    assert parsed["relations"] == []
    assert parsed["rejected"][0]["reason"] == "operation_mapping_failed"


def test_unknown_relation_kind_is_rejected():
    parsed = _parse({"relations": [
        {"kind": "magic", "operations": [{"line": 4}]}]})
    assert parsed["relations"] == []
    assert parsed["rejected"][0]["reason"] == "unknown_kind"


def test_duplicate_relation_is_rejected():
    parsed = _parse({"relations": [
        {"kind": "independent", "operations": [{"line": 4}]},
        {"kind": "independent", "operations": [{"line": 4}]},
    ]})
    assert len(parsed["relations"]) == 1
    assert parsed["rejected"][0]["reason"] == "duplicate_relation"


def test_unparseable_output_is_not_treated_as_empty_success():
    parsed = parse_semantic_hypotheses("no json here", index(), GRAPH,
                                       style="pilot")
    assert parsed["format"] == "unparseable"
    assert parsed["relations"] == []


def test_top_level_role_lists_are_accepted_as_aliases():
    parsed = _parse({"independent_operations": [[{"line": 4}]],
                     "fallback_paths": [[{"line": 4}, {"line": 6}]]})
    assert [rel["kind"] for rel in parsed["relations"]] == [
        "independent", "fallback"]


def test_new_operation_appears_in_the_operation_report():
    parsed = _parse({"relations": [
        {"kind": "independent", "operations": [{"line": 8}]}]})
    assert parsed["relations"][0]["in_graph"] is False
    assert [op["id"] for op in parsed["operations"]][0].startswith("op_L8")


# ---------------------------------------------------------------------------
# Role translation
# ---------------------------------------------------------------------------
def _roles(relations, executable=None):
    return relations_to_role_hypotheses(relations, executable_ops=executable)


def test_masking_relation_feeds_both_roles_with_different_sets():
    relations = [{"relation_index": 0, "kind": "independent",
                  "ops": ["a"], "condition": "x > 0"}]
    roles = _roles(relations, executable={"a", "b"})
    assert role_tuples(roles, "msms") == [("a",)]
    assert role_tuples(roles, "mmbs") == [("a",)]


def test_fallback_paths_become_separate_msms_hypotheses():
    relations = [
        {"relation_index": 0, "kind": "fallback", "ops": ["a"]},
        {"relation_index": 1, "kind": "fallback", "ops": ["b"]},
    ]
    roles = _roles(relations, executable={"a", "b"})
    assert role_tuples(roles, "msms") == [("a",), ("b",)]


def test_coexisting_relation_only_feeds_mmbs():
    relations = [{"relation_index": 0, "kind": "coexisting",
                  "ops": ["a", "b"]}]
    roles = _roles(relations, executable={"a", "b"})
    assert role_tuples(roles, "msms") == []
    assert role_tuples(roles, "mmbs") == [("a", "b")]


def test_unexecutable_operation_is_not_handed_to_the_search():
    relations = [{"relation_index": 0, "kind": "independent",
                  "ops": ["a", "outside"]}]
    roles = _roles(relations, executable={"a", "b"})
    assert role_tuples(roles, "msms") == []
    assert role_tuples(roles, "mmbs") == []
    assert roles["skipped"][0]["status"] == "HYPOTHESIS_UNEXECUTABLE"


# ---------------------------------------------------------------------------
# Pilot oracle
# ---------------------------------------------------------------------------
class FakeVerifier:
    def __init__(self):
        self.ops = ["B", "E"]
        self.calls = 0

    def op_for_line(self, line):
        return {4: "B", 6: "E"}.get(line)

    def matrix(self, disabled):
        self.calls += 1
        disabled = set(disabled)
        plus = ["return", ["int", 3 if "E" not in disabled else 7]]
        minus = ["return", ["int", 3]]
        return {"plus": {"case": {"observation": plus}},
                "minus": {"case": {"observation": minus}}}


def test_pilot_oracle_masked_and_exposed():
    oracle = PilotOracle(FakeVerifier(), "case", {"B": 4, "E": 6})
    masked = oracle.evaluate(["B"])          # E still masks -> equal
    assert masked.status == "OK"
    assert masked.masked is True and masked.exposed is False
    exposed = oracle.evaluate(["B", "E"])
    assert exposed.masked is False and exposed.exposed is True


def test_pilot_oracle_unknown_operation_is_invalid_not_false():
    oracle = PilotOracle(FakeVerifier(), "case", {"B": 4})
    record = oracle.evaluate(["outside"])
    assert record.status == "INVALID"
    assert record.masked is None and record.exposed is None


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------
def test_prompt_numbers_absolute_file_lines():
    prompt = build_prompt("t", SOURCE[SOURCE.index("    if c") :],
                          {"line": 4, "text": "if c == 0:"}, ["x.py"],
                          {"args": [], "cases": []}, GRAPH,
                          line_offset=3)
    assert "   4 | " in prompt
    assert "if c == 0:" in prompt
    assert "   1 | " not in prompt


def test_prompt_lists_graph_operations_without_hidden_roles():
    prompt = build_prompt("t", SOURCE, {"line": 3, "text": "v = v + 6"},
                          ["<program>"], {"args": [], "cases": []}, GRAPH)
    assert "op_L4_C4_if" in prompt
    assert "# OP_" not in prompt


# ---------------------------------------------------------------------------
# Integration with the real pilot harness
# ---------------------------------------------------------------------------
from benchmark_v3_baselines.graph_search import (  # noqa: E402
    search_relations, search_relations_role_separated)
from open_ops import discover  # noqa: E402
from scripts.check_open_interface import Verifier  # noqa: E402

KIT = __import__("pathlib").Path(__file__).resolve().parents[1]


def _pilot(task_id):
    tasks = {t["task_id"]: t for t in json.loads(
        (KIT / "benchmark_pilot" / "tasks.json").read_text(
            encoding="utf-8"))["tasks"]}
    attribution = json.loads(
        (KIT / "benchmark_pilot" / "attribution.json").read_text(
            encoding="utf-8"))["controlled"]
    task = tasks[task_id]
    verifier = Verifier(task, attribution[task_id])
    candidates = discover(task).candidates
    graph = [{
        "id": op.key, "file": "<program>", "line": op.line,
        "first_line": op.line, "last_line": op.end_line, "col": op.col,
        "kind": op.kind, "code": op.text,
    } for op in candidates]
    index = SourceIndex.from_source("<program>", task["program"]["source"])
    return task, verifier, graph, index


def _role_hyps(payload, graph, index, excluded):
    parsed = parse_semantic_hypotheses(
        json.dumps(payload), index, graph, style="pilot",
        exclude_lines=excluded)
    roles = relations_to_role_hypotheses(
        parsed["relations"], executable_ops={op["id"] for op in graph})
    return parsed, roles


def test_body_line_of_a_graph_operation_is_not_a_new_operation():
    universes = build_universes(
        GRAPH, [{"line": 5, "text": "v = v // 6 * 6"}], index(),
        style="pilot", exclude_lines=[3])
    assert universes["U_qwen"] == []
    assert universes["mapped"][0]["match"] == "contained_in_graph_span"


def test_pilot_fallback_hypotheses_are_gated_and_confirmed():
    task, verifier, graph, index = _pilot("ctrl_03")
    parsed, roles = _role_hyps({
        "relations": [
            {"kind": "fallback",
             "operations": [{"line": 4, "text": "if p == 0:"}],
             "condition": "p < 1"},
            {"kind": "fallback",
             "operations": [{"line": 6, "text": "if q == 0:"}],
             "condition": "q < 1"},
        ]}, graph, index, [3])
    assert parsed["format"] == "structured"
    assert len(parsed["relations"]) == 2

    case_id, args = next(
        (cid, a) for cid, a in verifier.cases
        if a["p"] == 0 and a["q"] == 0)
    oracle = PilotOracle(verifier, case_id,
                         {op["id"]: op["first_line"] for op in graph})
    result = search_relations_role_separated(
        None, args, [op["id"] for op in graph], budget=16,
        hypotheses={"msms": role_tuples(roles, "msms"),
                    "mmbs": role_tuples(roles, "mmbs")},
        oracle=oracle)

    assert sorted(result["msms_ids"]) == [
        ["op_L4_C4_if"], ["op_L6_C4_if"]]
    assert result["mmbs_ids"] == [["op_L4_C4_if", "op_L6_C4_if"]]
    assert result["first_msms"]["evaluations"] == 2
    assert result["duplicate_probes"] == 0
    gate = result["hypotheses"]["gate"]
    assert [entry["witness"] for entry in gate["msms"]] == [True, True]
    assert [entry["witness"] for entry in gate["mmbs"]] == [False, False]


def test_pilot_full_budget_matches_exhaustive():
    task, verifier, graph, index = _pilot("ctrl_02")
    universe = [op["id"] for op in graph]
    case_id, args = next(iter(verifier.cases))
    oracle = PilotOracle(verifier, case_id,
                         {op["id"]: op["first_line"] for op in graph})
    result = search_relations_role_separated(
        None, args, universe, budget=None, oracle=oracle)
    reference = search_relations(
        None, {}, universe, oracle=oracle, mode="exhaustive",
        adaptive=False)
    assert result["msms_ids"] == reference["msms_ids"]
    assert result["mmbs_ids"] == reference["mmbs_ids"]
    assert result["evaluations"] == reference["evaluations"] == 2 ** len(universe)


def test_v3_prompt_numbers_absolute_file_lines():
    from scripts.run_semantic_relation_discovery import v3_prompt_parts
    parts = v3_prompt_parts("werkzeug_get_host_default_empty")
    target_line = int(parts["task"]["target_operation"]["line"])
    prompt = build_prompt(
        "t", parts["source"], parts["task"]["target_operation"],
        parts["files"], parts["input_domain"], parts["graph_ops"],
        line_offset=parts["line_offset"])
    assert f"{target_line:>4} | " in prompt
    assert "   1 | " not in prompt
