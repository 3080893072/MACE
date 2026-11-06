"""Algorithm tests for EXP-1 emission and graph-guided causal search.

No hidden reference, scorer, model, or real probe is used here.  The
synthetic cases supply truth tables and the subgraph tests use small toy
sources, so a failure points at the algorithm rather than at a repository.
"""
from __future__ import annotations

import pytest

import itertools

from benchmark_v3_baselines.baseline_c import emission_allowed
from benchmark_v3_baselines.execution import _variant_name
from benchmark_v3_baselines.graph_search import (
    EvalRecord, search_relations, subset_key)
from benchmark_v3_baselines.subgraph import (
    build, candidate_ops, candidate_selection)
from benchmark_v3_baselines.synthetic_cases import CASES, run_case


# ---------------------------------------------------------------------------
# EXP-1: emission filter
# ---------------------------------------------------------------------------
def test_exp1_joint_collaboration_survives_minimality_only():
    # a and b are individually inert, so neither is in ``active``; deleting
    # both masks A.  The frozen filter drops the pair, EXP-1 keeps it.
    sets = [["a", "b"]]
    assert emission_allowed(sets, active=["c"], emission_mode="active_filtered") == []
    assert emission_allowed(sets, active=["c"], emission_mode="minimality_only") == [["a", "b"]]


def test_exp1_independent_members_kept_in_both_modes():
    sets = [["b"], ["b", "c"]]
    active = ["b", "c"]
    assert emission_allowed(sets, active, "active_filtered") == [["b"], ["b", "c"]]
    assert emission_allowed(sets, active, "minimality_only") == [["b"], ["b", "c"]]


def test_exp1_rejects_unknown_emission_mode():
    with pytest.raises(ValueError):
        emission_allowed([["a"]], ["a"], "guess")


class _KeyErrorExecutor:
    """Executor stand-in: any non-empty deletion is an illegal intervention."""

    universe = {}
    _runs = {}

    def observation(self, disabled, side, payload):
        if disabled:
            raise KeyError(disabled[0])
        return {"outcome": "return", "value": 1}


def test_exp1_illegal_intervention_is_invalid_not_emitted():
    result = search_relations(
        _KeyErrorExecutor(), {}, ["a", "b"], mode="graph")
    assert result["invalid_subsets"] == 3
    assert result["msms_ids"] == []
    assert all(status == "INVALID"
               for key, status in result["evidence_status"].items()
               if key != "EMPTY")
    assert result["complete"] is True
    assert result["evidence_complete"] is False


def test_exp1_unknown_subset_blocks_minimality():
    case = next(c for c in CASES if c["name"] == "unknown_intervention")
    result = run_case(case)
    # Treating UNKNOWN as False would confirm {b,c} and {a,b,c}.
    assert result["msms_ids"] == []
    assert result["msms_unknown"]
    assert result["evidence_complete"] is False


def test_exp1_non_monotonic_is_not_pruned():
    case = next(c for c in CASES if c["name"] == "non_monotonic")
    result = run_case(case)
    assert result["masked"][subset_key(("a",))] is True
    assert result["masked"][subset_key(("a", "b"))] is False
    assert result["masked"][subset_key(("a", "b", "c"))] is True
    assert result["msms_ids"] == [["b", "c"]]


def test_variant_names_are_unique_after_truncation():
    # Regression: the old name was the truncated subset key, so distinct
    # subsets of three or more operations shared a variant directory and a
    # cached probe could read another subset's source tree.
    prefix = "c_werkzeug_get_host_default_empty"
    ids = [f"src/werkzeug/sansio/utils.py:{line}-{line}"
           for line in (85, 87, 90, 93, 95, 101)]
    names = set()
    for size in range(len(ids) + 1):
        for combo in itertools.combinations(ids, size):
            for side in ("plus", "minus"):
                name = _variant_name(prefix, side, combo)
                assert len(name) <= 110
                assert name not in names, (side, combo)
                names.add(name)
    assert len(names) == 2 * 2 ** len(ids)


# ---------------------------------------------------------------------------
# Nine algorithmic scenarios
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_synthetic_case_graph_matches_exhaustive(case):
    graph = run_case(case, mode="graph")
    exhaustive = run_case(case, mode="exhaustive")
    assert graph["msms_ids"] == exhaustive["msms_ids"]
    assert graph["mmbs_ids"] == exhaustive["mmbs_ids"]
    assert graph["evidence_complete"] == exhaustive["evidence_complete"]


@pytest.mark.parametrize("case", CASES, ids=[c["name"] for c in CASES])
def test_synthetic_case_expected_relations(case):
    result = run_case(case)
    expected_msms = case.get("expected_msms_extra") or case["expected_msms"]
    assert result["msms_ids"] == expected_msms
    assert result["mmbs_ids"] == case["expected_mmbs"]
    assert result["complete"] is True


def test_synthetic_relations_have_intervention_evidence():
    for case in CASES:
        result = run_case(case)
        for relation in result["msms_ids"] + result["mmbs_ids"]:
            # Every emitted relation traces to an OK observation record.
            keys = {subset_key(relation)}
            if relation in result["msms_ids"]:
                keys.add(subset_key(set(result["universe"]) - set(relation)))
            for key in keys:
                assert result["evidence_status"].get(key) == "OK"


def test_budget_marks_run_incomplete():
    case = next(c for c in CASES if c["name"] == "non_monotonic")
    result = run_case(case, budget=2)
    assert result["evaluations"] == 2
    assert result["complete"] is False
    assert "complete" not in result or result["complete"] is False


def test_two_fallback_paths_are_both_found():
    case = next(c for c in CASES if c["name"] == "two_fallback_paths")
    result = run_case(case, mode="graph")
    assert sorted(result["msms_ids"]) == [["a", "b"], ["c", "d"]]


def test_missing_edge_candidate_is_not_pruned():
    case = next(c for c in CASES if c["name"] == "missing_edge_risk")
    result = run_case(case)
    assert result["universe"] == ["a", "b", "remote"]
    assert result["msms_ids"] == [["a"]]
    assert result["evaluations"] == 2 ** len(result["universe"])


def test_universe_change_changes_minimality():
    case = next(c for c in CASES if c["name"] == "universe_change")
    small = run_case({**case, "extra_universe": None})
    large = run_case(case)
    assert small["msms_ids"] == [["b"]]
    assert large["msms_ids"] == [["c"]]


# ---------------------------------------------------------------------------
# Subgraph construction
# ---------------------------------------------------------------------------
TOY = """\
def f(x):
    total = 0
    if x:
        total = x + 1
    else:
        total = x - 1
    alias = total
    mystery(total)
    return alias
"""

SCOPED = """\
class A:
    def __init__(self, v):
        self.v = v
        self.v = self.v + 1
        self.v = str(self.v)

class B:
    def __init__(self, w):
        super().__init__()
        self.w = w
        self.w = w + 2
"""


def _task(line: int) -> dict:
    return {"file": "toy.py",
            "target_operation": {"file": "toy.py", "line": line,
                                 "function": "f"}}


def test_subgraph_has_data_control_alias_unknown_edges():
    graph = build(_task(7), TOY)
    kinds = {edge["kind"] for edge in graph["edges"]}
    assert {"data", "control", "alias", "call"} <= kinds
    assert any(edge["confidence"] == "UNKNOWN" for edge in graph["edges"])
    assert any("mystery" in note for note in graph["unknowns"])
    # assignment alias from ``alias = total`` to the earlier definition
    assert any(edge["kind"] == "alias" and edge["src"] == "toy.py:7-7"
               and edge["dst"] == "toy.py:2-2" for edge in graph["edges"])


def test_control_nodes_do_not_own_body_facts():
    graph = build(_task(7), TOY)
    control = next(node for node in graph["nodes"]
                   if node["first_line"] == 3 and node["last_line"] == 6)
    # The if-node contributes only its guard ``x``; it must not inherit
    # ``total`` from either branch.
    assert "x" in control["uses"]
    assert "total" not in control["defs"]
    assert "total" not in control["uses"]


def test_class_scope_prevents_unrelated_method_candidates():
    task = {"file": "toy.py",
            "target_operation": {"file": "toy.py", "line": 4,
                                 "function": "A.__init__"}}
    graph = build(task, SCOPED)
    lines = {item["first_line"] for item in graph["candidates"]}
    assert 4 not in lines                      # target itself is not deletable
    assert not lines & {9, 10, 11}             # class B stays out


def test_candidate_truncation_is_reported():
    graph = build(_task(7), TOY)
    selection = candidate_selection(graph, max_ops=1)
    assert selection["selected"] == 1
    assert selection["eligible"] > 1
    assert selection["truncated"] is True
    assert selection["omitted"]
    assert len(candidate_ops(graph, max_ops=1)) == 1


def test_static_dependence_is_not_a_causal_claim():
    # The toy graph has data/control edges to both branch assignments, but
    # only the pair the oracle actually marks masked may produce a relation.
    graph = build(_task(7), TOY)
    ids = [item["id"] for item in candidate_ops(graph, 3)]
    assert len(ids) == 3
    from benchmark_v3_baselines.graph_search import SyntheticOracle
    pair = tuple(sorted(ids[:2]))
    result = search_relations(
        None, {}, ids,
        oracle=SyntheticOracle([(), pair], [], [], []), mode="graph")
    complement = [op for op in sorted(ids) if op not in pair]
    assert complement in result["msms_ids"]
    assert [pair[0]] not in result["msms_ids"]
    assert [pair[1]] not in result["msms_ids"]
    assert result["mmbs_ids"] == []
