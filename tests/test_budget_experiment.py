"""Tests for the same-universe budget accounting.

These cover the two properties the report relies on:

1. a budget is a deterministic prefix of one full run, with the rounding rule
   fixed in advance (ceil, clipped to the full enumeration);
2. a minimal set is reported as confirmed only after every strict-subset
   comparison it needs is present.  Missing evidence makes it *undecided*,
   never confirmed.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from benchmark_v3_baselines import graph_search  # noqa: E402
from benchmark_v3_baselines.graph_search import (  # noqa: E402
    EvalRecord, EvidenceStore, subset_key)
from scripts.run_budget_experiment import (  # noqa: E402
    FRACTIONS, _classify, _first_index, budget_limit)


@pytest.mark.parametrize("fraction,total,expected", [
    (0.10, 64, 7),      # ceil(6.4)
    (0.25, 64, 16),
    (0.50, 64, 32),
    (0.75, 64, 48),
    (1.00, 64, 64),
    (0.10, 8, 1),       # ceil(0.8) = 1, never zero
    (1.00, 1, 1),
])
def test_budget_rounds_up_and_clips(fraction, total, expected):
    assert budget_limit(fraction, total) == expected


def test_budget_is_prefix_of_one_run():
    """Every fraction maps into [1, total]; the list is non-decreasing."""
    limits = [budget_limit(f, 32) for f in FRACTIONS]
    assert limits == sorted(limits)
    assert limits[0] >= 1
    assert limits[-1] == 32


def _store(records):
    """records: (disabled, masked, exposed); exposed is independent."""
    store = EvidenceStore(oracle=None)
    for disabled, masked, exposed in records:
        store.records[subset_key(disabled)] = EvalRecord(
            tuple(disabled), "OK", masked=masked, exposed=exposed)
        store.order.append(subset_key(disabled))
        store.evaluations += 1
    return store


def test_msms_needs_every_proper_subset():
    """masked({}) is true, so {a,b} masks; without the subset records the
    minimality check cannot confirm it."""
    partial = _store([((), True, False)])
    blocked = graph_search.minimal_masked_sets(["a", "b"], partial)
    assert blocked["confirmed"] == []
    assert any(item["set"] == ["a", "b"] for item in blocked["unknown"])

    complete = _store([((), True, False), (("b",), False, True),
                     (("a",), False, True)])
    confirmed = graph_search.minimal_masked_sets(["a", "b"], complete)
    assert confirmed["confirmed"] == [["a", "b"]]


def test_msms_not_confirmed_when_a_strict_subset_masks():
    """If {a} masks by itself, {a,b} is not minimal even with full evidence."""
    store = _store([((), True, False), (("b",), True, False),
                     (("a",), False, True)])
    result = graph_search.minimal_masked_sets(["a", "b"], store)
    assert ["a", "b"] not in result["confirmed"]


def test_mmbs_checks_empty_subset_too():
    store = _store([(("a",), True, True)])
    blocked = graph_search.minimal_exposed_sets(["a"], store)
    assert blocked["confirmed"] == []
    assert any(item["set"] == ["a"] for item in blocked["unknown"])

    complete = _store([(("a",), True, True), ((), False, False)])
    assert graph_search.minimal_exposed_sets(
        ["a"], complete)["confirmed"] == [["a"]]


def test_first_confirmation_index_waits_for_subset_evidence():
    """The witness appears at index 0, but the strict subsets arrive later,
    so the first confirmed index must be the later one."""
    universe = ["a", "b"]
    trace = [
        {"disabled": [], "status": "OK", "masked": True, "exposed": False},
        {"disabled": ["b"], "status": "OK", "masked": False, "exposed": True},
        {"disabled": ["a"], "status": "OK", "masked": False, "exposed": True},
    ]
    first = _first_index(trace, universe)
    assert first["msms"]["index"] == 3
    assert first["msms"]["set"] == ["a", "b"]
    # MMBS: exposed(["b"]) at index 1 and exposed([]) at index 0, but the
    # empty subset is only in the store by index 2?  [] is at index 0, so
    # {b} is minimal already at index 2 (prefix length 2).
    assert first["mmbs"]["index"] == 2


def test_prefix_truncation_cannot_confirm_beyond_budget():
    universe = ["a", "b", "c"]
    trace = [
        {"disabled": [], "status": "OK", "masked": True, "exposed": False},
        {"disabled": ["c"], "status": "OK", "masked": False, "exposed": True},
        {"disabled": ["b"], "status": "OK", "masked": False, "exposed": True},
    ]
    partial = _first_index(trace, universe)
    assert partial["msms"] is None


def test_classify_splits_missing_from_bad_evidence():
    blocked = [
        {"set": ["a"], "blocked_by": [{"subset": [], "reason": "missing"}]},
        {"set": ["b"], "blocked_by": [{"subset": [], "reason": "UNKNOWN"}]},
        {"set": ["c"], "blocked_by": [
            {"subset": [], "reason": "INVALID"},
            {"subset": ["a"], "reason": "missing"}]},
    ]
    undecided, unknown = _classify(blocked)
    assert undecided == 2
    assert unknown == 1


def test_mmbs_is_monotone_under_universe_expansion():
    """Exposed(D) and D's minimality depend only on D, never on U."""
    store = _store([((), False, False), (("a",), False, True)])
    small = graph_search.minimal_exposed_sets(["a", "b"], store)["confirmed"]
    large = graph_search.minimal_exposed_sets(
        ["a", "b", "c"], store)["confirmed"]
    assert ["a"] in small
    assert ["a"] in large


def test_msms_is_not_monotone_under_universe_expansion():
    """Masked(U \\ S) reads a different disabled set after U grows."""
    store = _store([
        (("b",), True, False),
        (("c",), True, False),
        (("b", "c"), False, True),
        (("a", "c"), False, True),
        ((), False, True),
    ])
    small = graph_search.minimal_masked_sets(["a", "b"], store)["confirmed"]
    large = graph_search.minimal_masked_sets(
        ["a", "b", "c"], store)["confirmed"]
    assert small == [["a"]]
    assert large == [["a", "b"]]


def test_graph_order_and_exhaustive_order_share_the_same_subsets():
    universe = ["a", "b", "c"]
    exhaustive = sorted(graph_search.all_subsets(universe),
                        key=lambda item: (len(item), item))
    scores = {"a": 1.0, "b": 0.5, "c": 0.0}
    pending = set(graph_search.all_subsets(universe))
    graph_order = []
    while pending:
        choice = min(pending, key=lambda item: (
            graph_search._subset_priority(item, universe, scores, {}), item))
        graph_order.append(choice)
        pending.remove(choice)
    assert sorted(map(tuple, exhaustive)) == sorted(map(tuple, graph_order))
    assert graph_order != exhaustive
