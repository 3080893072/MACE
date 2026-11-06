"""Synthetic algorithmic cases for the graph-guided causal search.

These cases are *algorithm checks*, not benchmark results.  They exercise
specific failure modes of subset enumeration and of the EXP-1 emission
filter without executing real code.  Each case supplies a truth table over
disabled sets; the expected minimal sets were derived by hand from the
public MSMS/MMBS definitions.

Scenario map
------------
1. ``single_op``                one deleted operation masks A
2. ``two_op_collaboration``     no member alone masks; the pair does
3. ``two_fallback_paths``       two alternative pairs each mask
4. ``non_monotonic``            masked status is not monotone
5. ``cross_function_state``     state written in one function, read in another
6. ``alias_indirect``           dependence visible only through an alias
7. ``unknown_intervention``     UNKNOWN evidence must not become False
8. ``missing_edge_risk``        a candidate with no static path must remain
9. ``universe_change``          minimality is relative to the universe
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List

from benchmark_v3_baselines.graph_search import (
    SyntheticOracle, search_relations, subset_key)

CASES: List[Dict[str, Any]] = [
    {
        "name": "single_op",
        "universe": ["a", "b"],
        "masked": [(), ("a",)],
        "exposed": [("b",)],
        "unknown": [],
        "invalid": [],
        "expected_msms": [["b"]],
        "expected_mmbs": [["b"]],
        "note": "deleting b exposes A; keeping b while deleting a masks",
    },
    {
        "name": "two_op_collaboration",
        "universe": ["a", "b", "c", "d"],
        "masked": [(), ("a", "b")],
        "exposed": [("d",)],
        "unknown": [],
        "invalid": [],
        "expected_msms": [["c", "d"]],
        "expected_mmbs": [["d"]],
        "note": "a and b are inert alone; deleting both masks A",
    },
    {
        "name": "two_fallback_paths",
        "universe": ["a", "b", "c", "d"],
        "masked": [(), ("a", "b"), ("c", "d")],
        "exposed": [("d",)],
        "unknown": [],
        "invalid": [],
        "expected_msms": [["a", "b"], ["c", "d"]],
        "expected_mmbs": [["d"]],
        "note": "two independent pairs can each mask A",
    },
    {
        "name": "non_monotonic",
        "universe": ["a", "b", "c"],
        "masked": [(), ("a",), ("a", "b", "c")],
        "exposed": [("a", "b")],
        "unknown": [],
        "invalid": [],
        "expected_msms": [["b", "c"]],
        "expected_mmbs": [["a", "b"]],
        "note": "masked({a}) true, masked({a,b}) false, masked({a,b,c}) true",
    },
    {
        "name": "cross_function_state",
        "universe": ["set_state", "read_state", "alias_bind"],
        "masked": [(), ("set_state", "alias_bind")],
        "exposed": [("read_state",)],
        "unknown": [],
        "invalid": [],
        "expected_msms": [["read_state"]],
        "expected_mmbs": [["read_state"]],
        "note": "state written in one function and read in another",
    },
    {
        "name": "alias_indirect",
        "universe": ["a", "b", "c"],
        "masked": [(), ("b", "c")],
        "exposed": [("a",)],
        "unknown": [],
        "invalid": [],
        "expected_msms": [["a"]],
        "expected_mmbs": [["a"]],
        "note": "dependence is only visible through an alias pair",
    },
    {
        "name": "unknown_intervention",
        "universe": ["a", "b", "c"],
        "masked": [(), ("a",)],
        "exposed": [],
        "unknown": [("a", "b")],
        "invalid": [],
        "expected_msms": [],
        "expected_mmbs": [],
        "note": "treating UNKNOWN as False would wrongly confirm {b,c} and U",
    },
    {
        "name": "missing_edge_risk",
        "universe": ["remote", "a", "b"],
        "masked": [(), ("remote", "b")],
        "exposed": [("a",)],
        "unknown": [],
        "invalid": [],
        "expected_msms": [["a"]],
        "expected_mmbs": [["a"]],
        "note": "remote has no static path to A but is still causal",
    },
    {
        "name": "universe_change",
        "universe": ["a", "b"],
        "extra_universe": ["a", "b", "c"],
        "masked": [(), ("a",), ("a", "b")],
        "exposed": [("a", "b")],
        "unknown": [],
        "invalid": [],
        "expected_msms": [["b"]],
        "expected_mmbs": [["a", "b"]],
        "expected_msms_extra": [["c"]],
        "note": "same truth table, different universe, different minimal set",
    },
]


def run_case(case: Dict[str, Any], *, mode: str = "graph",
             budget: int | None = None) -> Dict[str, Any]:
    universe = list(case.get("extra_universe") or case["universe"])
    oracle = SyntheticOracle(case["masked"], case["exposed"],
                             case["unknown"], case["invalid"])
    return search_relations(
        None, {}, universe, oracle=oracle, mode=mode, budget=budget,
        adaptive=False,
        graph_scores={op: 0.0 for op in universe})


def evidence_is_ok(result: Dict[str, Any], sets: Iterable[Iterable[str]]) -> bool:
    """Every emitted set must trace to an OK intervention record."""
    status = result.get("evidence_status", {})
    for item in sets:
        key = subset_key(item)
        if status.get(key) != "OK":
            return False
    return True
