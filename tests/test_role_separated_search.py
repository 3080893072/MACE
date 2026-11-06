"""Regression tests for the role-separated MSMS/MMBS search (v2).

Each test targets one property of the v2 contract:

* MSMS and MMBS have separate score maps and separate queues;
* ``D = EMPTY`` still runs first, ``D = U`` is no longer forced second;
* model hypotheses are gated by real evidence and never prune ``U``;
* UNKNOWN / INVALID never become False;
* a full budget reproduces exhaustive enumeration;
* shared evidence is not probed twice and hypothesis probes are charged.

No hidden scorer, model or real probe is used.
"""
from __future__ import annotations

import json

import pytest

from benchmark_v3_baselines.graph_search import (
    SyntheticOracle, search_relations, search_relations_role_separated,
    subset_key)
from benchmark_v3_baselines.synthetic_cases import CASES
from scripts.run_full_mace_comparison import parse_hypotheses


class CountingOracle:
    """Synthetic oracle that records every intervention it is asked for."""

    def __init__(self, case):
        self.inner = SyntheticOracle(case["masked"], case["exposed"],
                                     case.get("unknown", []),
                                     case.get("invalid", []))
        self.calls: list[str] = []

    def evaluate(self, disabled):
        self.calls.append(subset_key(disabled))
        return self.inner.evaluate(disabled)


def run(case, *, budget=None, msms_scores=None, mmbs_scores=None,
        hypotheses=None, cap=3):
    universe = sorted(case.get("extra_universe") or case["universe"])
    oracle = CountingOracle(case)
    result = search_relations_role_separated(
        None, {}, universe, oracle=oracle, budget=budget,
        msms_scores=msms_scores, mmbs_scores=mmbs_scores,
        hypotheses=hypotheses, max_hypothesis_probes_per_role=cap)
    result["_calls"] = oracle.calls
    return result


def case(name):
    return next(item for item in CASES if item["name"] == name)


def role_order(result, role):
    return [tuple(step["disabled"]) for step in result["schedule"]
            if step["role"] == role]


# ---------------------------------------------------------------------------
# Role independence
# ---------------------------------------------------------------------------
def test_role_scores_are_independent():
    base = case("two_fallback_paths")
    a = run(base, msms_scores={"a": 5.0})
    b = run(base, msms_scores={"c": 5.0})
    assert a["queues"]["msms"] != b["queues"]["msms"]
    assert a["queues"]["mmbs"] == b["queues"]["mmbs"]

    c = run(base, mmbs_scores={"a": 5.0})
    d = run(base, mmbs_scores={"c": 5.0})
    assert c["queues"]["mmbs"] != d["queues"]["mmbs"]
    assert c["queues"]["msms"] == d["queues"]["msms"]


def test_mmbs_order_ignores_msms_scores_and_vice_versa():
    base = case("non_monotonic")
    plain = run(base)
    msms_changed = run(base, msms_scores={"c": 9.0})
    mmbs_changed = run(base, mmbs_scores={"c": 9.0})
    assert msms_changed["queues"]["mmbs"] == plain["queues"]["mmbs"]
    assert mmbs_changed["queues"]["msms"] == plain["queues"]["msms"]
    assert msms_changed["queues"]["msms"] != plain["queues"]["msms"]
    assert mmbs_changed["queues"]["mmbs"] != plain["queues"]["mmbs"]


# ---------------------------------------------------------------------------
# Scheduling: EMPTY first, U not forced second, fair alternation
# ---------------------------------------------------------------------------
def test_empty_intervention_executes_first():
    result = run(case("two_fallback_paths"))
    first = result["schedule"][0]
    assert first["disabled"] == []
    assert first["role"] == "baseline"


@pytest.mark.parametrize("name", ["two_fallback_paths", "non_monotonic"])
def test_universe_is_not_forced_second(name):
    item = case(name)
    result = run(item)
    universe = sorted(item.get("extra_universe") or item["universe"])
    assert result["schedule"][1]["disabled"] != universe
    # The first ordinary evaluation belongs to the MSMS queue: a small kept
    # set, i.e. a large disabled complement, never the full universe.
    assert result["schedule"][1]["role"] == "msms"


def test_roles_alternate_without_starving_either_side():
    result = run(case("two_op_collaboration"))
    roles = [step["role"] for step in result["schedule"]
             if step["role"] in {"msms", "mmbs"}]
    assert roles[:4] == ["msms", "mmbs", "msms", "mmbs"]
    counts = {role: roles.count(role) for role in ("msms", "mmbs")}
    assert abs(counts["msms"] - counts["mmbs"]) <= 1


# ---------------------------------------------------------------------------
# Hypothesis gating
# ---------------------------------------------------------------------------
def test_wrong_hypothesis_receives_no_priority():
    base = case("single_op")           # masked: EMPTY and {a}
    plain = run(base)
    result = run(base, hypotheses={"msms": [("a",)]})   # D = {b}: not masked
    gate = result["hypotheses"]["gate"]["msms"][0]
    assert gate["status"] == "OK"
    assert gate["witness"] is False
    assert gate["prioritised"] is False

    probed = {tuple(entry["disabled"])
              for entry in result["hypotheses"]["gate"]["msms"]}
    expected = [key for role in ("msms", "mmbs")
                for key in role_order(plain, role) if key not in probed]
    got = [key for role in ("msms", "mmbs")
           for key in role_order(result, role)]
    assert got == expected


def test_correct_single_op_hypothesis_is_witnessed_early():
    result = run(case("single_op"), hypotheses={"msms": [("b",)]})
    gate = result["hypotheses"]["gate"]["msms"][0]
    assert gate["witness"] is True and gate["prioritised"] is True
    assert result["first_msms"]["evaluations"] == 2
    assert result["first_msms"]["set"] == ["b"]


def test_collaborative_pair_hypothesis_is_mapped_and_verified():
    result = run(case("two_op_collaboration"),
                 hypotheses={"msms": [("c", "d")]})
    gate = result["hypotheses"]["gate"]["msms"][0]
    assert gate["ops"] == ["c", "d"]
    assert gate["disabled"] == ["a", "b"]
    assert gate["witness"] is True
    assert result["hypotheses"]["accepted"]["msms"] == [["c", "d"]]
    # The witness is not the relation: strict-subset checks still run.
    assert ["c", "d"] in result["msms_ids"]


def test_unmentioned_operations_remain_in_the_search_space():
    result = run(case("two_op_collaboration"),
                 hypotheses={"msms": [("a",)]})    # wrong and partial
    assert result["complete"] is True
    assert result["evaluations"] == result["subsets_total"] == 16
    seen = set()
    for key in result["masked"]:
        if key != "EMPTY":
            seen.update(key.split("+"))
    assert seen == {"a", "b", "c", "d"}
    assert result["msms_ids"] == [["c", "d"]]
    assert result["mmbs_ids"] == [["d"]]


def test_hypothesis_probes_count_toward_the_budget():
    result = run(case("two_op_collaboration"), budget=3,
                 hypotheses={"msms": [("c", "d")], "mmbs": [("d",)]})
    assert result["evaluations"] == 3
    statuses = [entry["status"]
                for role in ("msms", "mmbs")
                for entry in result["hypotheses"]["gate"][role]]
    assert "BUDGET_SKIPPED" not in statuses
    assert result["complete"] is False


def test_hypothesis_verification_is_capped_per_role():
    result = run(case("two_op_collaboration"), cap=3,
                 hypotheses={"msms": [("a",), ("b",), ("c",), ("d",),
                                      ("a", "b")]})
    assert len(result["hypotheses"]["gate"]["msms"]) == 3
    assert len(result["hypotheses"]["accepted"]["msms"]) == 5


def test_unknown_ids_are_rejected_not_searched():
    # A model id outside U must not become a candidate.
    result = run(case("single_op"), hypotheses={"msms": [("b", "zzz")]})
    assert result["hypotheses"]["accepted"]["msms"] == []
    rejected = result["hypotheses"]["rejected"]
    assert rejected and rejected[0]["reason"] == "unknown_ids"
    assert "zzz" not in result["universe"]
    assert result["evaluations"] == result["subsets_total"] == 4


# ---------------------------------------------------------------------------
# Three-valued evidence
# ---------------------------------------------------------------------------
def test_unknown_evidence_is_not_false():
    result = run(case("unknown_intervention"))
    assert result["msms_ids"] == [] and result["mmbs_ids"] == []
    assert result["msms_unknown"]
    assert result["complete"] is True
    assert result["evidence_complete"] is False


def test_invalid_evidence_is_not_false():
    case_dict = {"universe": ["a", "b"], "masked": [()], "exposed": [],
                 "unknown": [], "invalid": [("a",)]}
    result = run(case_dict)
    assert result["invalid_subsets"] == 1
    assert result["msms_ids"] == [] and result["mmbs_ids"] == []
    assert result["evidence_complete"] is False


def test_incomplete_strict_subset_evidence_does_not_confirm():
    case_dict = {"universe": ["a", "b", "c"], "masked": [(), ("a",)],
                 "exposed": [], "unknown": [], "invalid": []}
    result = run(case_dict, budget=2, hypotheses={"msms": [("b", "c")]})
    # The hypothesis itself has a witness...
    assert result["hypotheses"]["gate"]["msms"][0]["witness"] is True
    # ...but minimality is not established without the strict subsets.
    assert result["first_msms"] is None
    assert ["b", "c"] not in result["msms_ids"]
    assert any(item["set"] == ["b", "c"] for item in result["msms_unknown"])


# ---------------------------------------------------------------------------
# Completeness and cache
# ---------------------------------------------------------------------------
@pytest.mark.parametrize("name", [item["name"] for item in CASES])
def test_full_budget_matches_exhaustive(name):
    item = case(name)
    universe = sorted(item.get("extra_universe") or item["universe"])
    result = run(item)
    reference = search_relations(
        None, {}, universe,
        oracle=SyntheticOracle(item["masked"], item["exposed"],
                               item.get("unknown", []),
                               item.get("invalid", [])),
        mode="exhaustive", adaptive=False)
    assert result["msms_ids"] == reference["msms_ids"]
    assert result["mmbs_ids"] == reference["mmbs_ids"]
    assert result["evaluations"] == reference["evaluations"] == 2 ** len(universe)
    assert result["complete"] is True


def test_shared_cache_is_never_probed_twice():
    case_dict = {"universe": ["a", "b"], "masked": [("a",)],
                 "exposed": [("a",)], "unknown": [], "invalid": []}
    result = run(case_dict, hypotheses={"msms": [("b",)],
                                       "mmbs": [("a",)]})
    # MSMS kept {b} and MMBS disabled {a} are the same intervention.
    assert [entry["disabled"]
            for entry in result["hypotheses"]["gate"]["msms"]] == [["a"]]
    assert [entry["disabled"]
            for entry in result["hypotheses"]["gate"]["mmbs"]] == [["a"]]
    assert result["_calls"].count("a") == 1
    assert result["reused_evidence"] >= 1
    assert result["duplicate_probes"] == 0


# ---------------------------------------------------------------------------
# Qwen output protocol
# ---------------------------------------------------------------------------
def test_structured_protocol_keeps_multi_op_hypotheses():
    content = json.dumps({
        "msms_hypotheses": [
            {"kept_ops": ["b", "c"], "condition": "x > 0",
             "rationale": "pair masks", "source_evidence": ["l. 10"]}],
        "mmbs_hypotheses": [
            {"disabled_ops": ["a"], "condition": "x > 0",
             "rationale": "a hides", "source_evidence": ["l. 4"]}],
    })
    parsed = parse_hypotheses(content, ["a", "b", "c"])
    assert parsed["format"] == "structured"
    assert parsed["msms"] == [("b", "c")]
    assert parsed["mmbs"] == [("a",)]
    assert parsed["rejected"] == []


def test_structured_protocol_rejects_unknown_ids():
    parsed = parse_hypotheses(
        '{"msms_hypotheses": [{"kept_ops": ["a", "zz"]}]}', ["a", "b"])
    assert parsed["msms"] == []
    assert parsed["rejected"][0]["reason"] == "unknown_ids"
    assert parsed["rejected"][0]["unknown_ids"] == ["zz"]


def test_legacy_rank_output_becomes_unprioritised_hypotheses():
    parsed = parse_hypotheses(
        '{"msms_rank": ["b", "zz"], "mmbs_rank": ["a"]}', ["a", "b"])
    assert parsed["format"] == "legacy_converted"
    assert parsed["msms"] == [("b",)]
    assert parsed["mmbs"] == [("a",)]
    assert any(item.get("reason") == "unknown_ids"
               for item in parsed["rejected"])
