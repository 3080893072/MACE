"""Tests for the deterministic operation-level discovery baseline."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from open_ops import discover, to_submission  # noqa: E402
from open_ops.discover import check_condition  # noqa: E402
from check_open_interface import Verifier  # noqa: E402

TASKS_PATH = ROOT / "benchmark_pilot" / "tasks.json"
ATTR_PATH = ROOT / "benchmark_pilot" / "attribution.json"


@pytest.fixture(scope="module")
def tasks():
    if not TASKS_PATH.exists():
        pytest.skip("run scripts/pilot_build.py first")
    return {t["task_id"]: t for t in json.loads(TASKS_PATH.read_text(encoding="utf-8"))["tasks"]}


@pytest.fixture(scope="module")
def attribution():
    return json.loads(ATTR_PATH.read_text(encoding="utf-8"))["controlled"]


def _relation_set(result):
    return {(r.kind, frozenset(op.line for op in r.operations))
            for r in result.relations}


def _verify_with_benchmark(task, attribution, result):
    verifier = Verifier(task, attribution)
    submission = to_submission(result)
    assert len(submission["relations"]) == len(result.relations)
    return [verifier.verify_relation(rel) for rel in submission["relations"]]


def test_ctrl_02_discovers_cd_cooperative(tasks, attribution):
    result = discover(tasks["ctrl_02"])
    assert result.status == "OK"
    assert [op.line for op in result.candidates] == [4, 6]
    assert _relation_set(result) == {("cooperative", frozenset({4, 6}))}
    rel = result.relations[0]
    assert rel.status == "VERIFIED"
    assert rel.condition_check["sound"] is True
    assert rel.condition_check["complete"] is True
    assert rel.condition_check["exact"] is True
    assert rel.condition_check["witness_value"] is True
    assert rel.witness_input["c"] == 0 and rel.witness_input["d"] == 0
    assert all(v for v in rel.checks["proper_subsets_do_not_mask"].values())
    verified = _verify_with_benchmark(tasks["ctrl_02"], attribution["ctrl_02"], result)
    assert verified[0]["status"] == "VERIFIED"


def test_ctrl_03_discovers_all_relation_kinds(tasks, attribution):
    result = discover(tasks["ctrl_03"])
    assert result.status == "OK"
    assert [op.line for op in result.candidates] == [4, 6, 8, 10]
    assert _relation_set(result) == {
        ("independent", frozenset({4})),
        ("independent", frozenset({6})),
        ("cooperative", frozenset({8, 10})),
        ("coexisting", frozenset({4, 6})),
    }
    for rel in result.relations:
        assert rel.status == "VERIFIED", (rel.kind, rel.condition_check)
        assert rel.condition_check["exact"] is True
        assert rel.condition_check["witness_value"] is True
    verified = _verify_with_benchmark(tasks["ctrl_03"], attribution["ctrl_03"], result)
    assert [v["status"] for v in verified] == ["VERIFIED"] * 4


CONTROL_STATE_SOURCE = '''def program(x, c):
    v = x
    v = v + 1  # TARGET_A
    flag = c == 0
    if flag:
        v = x
    return v
'''

CONTROL_STATE_MINUS = '''def program(x, c):
    v = x
    pass  # P-: A deleted
    flag = c == 0
    if flag:
        v = x
    return v
'''


def _control_state_task():
    return {
        "task_id": "control_state",
        "entry": "program",
        "program": {"source": CONTROL_STATE_SOURCE,
                    "target_A": {"line": 3}},
        "deletion": {"p_minus_source": CONTROL_STATE_MINUS},
        "input_domain": {
            "args": [{"name": "x"}, {"name": "c"}],
            "cases": [{"x": x, "c": c} for x in (0, 1, 2) for c in (0, 1)],
        },
    }


def test_control_state_assignment_is_part_of_cooperative_relation():
    result = discover(_control_state_task())
    assert result.status == "OK"
    assert [op.line for op in result.candidates] == [4, 5]
    # B alone (line 5) is not independent: without C (line 4), flag is unbound.
    assert _relation_set(result) == {("cooperative", frozenset({4, 5}))}
    assert not any(r.kind == "independent" for r in result.relations)
    rel = result.relations[0]
    assert rel.status == "VERIFIED"
    assert rel.condition_check["exact"] is True
    assert rel.checks["only_set_masks"] is True
    assert rel.checks["disabling_set_exposes"] is True


def test_dead_store_is_not_a_candidate():
    source = '''def program(x, c):
    v = x
    v = v + 1  # TARGET_A
    dead = 99
    if c == 0:
        v = x
    return v
'''
    minus = '''def program(x, c):
    v = x
    pass  # P-: A deleted
    dead = 99
    if c == 0:
        v = x
    return v
'''
    task = {
        "task_id": "dead_store",
        "entry": "program",
        "program": {"source": source, "target_A": {"line": 3}},
        "deletion": {"p_minus_source": minus},
        "input_domain": {
            "args": [{"name": "x"}, {"name": "c"}],
            "cases": [{"x": x, "c": c} for x in (0, 1) for c in (0, 1)],
        },
    }
    result = discover(task)
    assert [op.line for op in result.candidates] == [5]


def test_no_downstream_candidates_returns_unknown():
    source = '''def program(x):
    v = x
    v = v + 1  # TARGET_A
    return v
'''
    minus = '''def program(x):
    v = x
    pass  # P-: A deleted
    return v
'''
    task = {
        "task_id": "no_candidates",
        "entry": "program",
        "program": {"source": source, "target_A": {"line": 3}},
        "deletion": {"p_minus_source": minus},
        "input_domain": {"args": [{"name": "x"}],
                         "cases": [{"x": 0}, {"x": 1}]},
    }
    result = discover(task)
    assert result.status == "UNKNOWN"
    assert result.candidates == ()


def test_unsupported_loop_is_reported():
    source = '''def program(x, c):
    v = x
    v = v + 1  # TARGET_A
    while c == 0:
        v = x
    return v
'''
    minus = '''def program(x, c):
    v = x
    pass  # P-: A deleted
    while c == 0:
        v = x
    return v
'''
    task = {
        "task_id": "unsupported",
        "entry": "program",
        "program": {"source": source, "target_A": {"line": 3}},
        "deletion": {"p_minus_source": minus},
        "input_domain": {
            "args": [{"name": "x"}, {"name": "c"}],
            "cases": [{"x": 0, "c": 0}, {"x": 0, "c": 1}],
        },
    }
    result = discover(task)
    assert result.status == "UNSUPPORTED"
    assert "While" in result.reason


def test_condition_check_is_domain_wide_not_witness_only():
    cases = [("case_0", {"x": 0}), ("case_1", {"x": 1})]
    labels = {"case_0": True, "case_1": False}
    weak = check_condition("True", cases, ["x"], labels, "case_0")
    assert weak["exact"] is False
    assert weak["sound"] is False
    assert "case_1" in weak["false_accept"]

    exact = check_condition("x == 0", cases, ["x"], labels, "case_0")
    assert exact["exact"] is True
    assert exact["sound"] is True
    assert exact["complete"] is True


def test_candidate_keys_are_source_positions_not_private_labels(tasks):
    result = discover(tasks["ctrl_03"])
    assert all(op.key.startswith("op_L") for op in result.candidates)
    assert all("OP_" not in op.text for op in result.candidates)
