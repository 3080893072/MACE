"""Regression and safety tests for the independent verifier v2."""
from __future__ import annotations

import builtins
import json
from pathlib import Path

import pytest

from benchmark_pilot import verifier_v2 as v2

ROOT = Path(__file__).resolve().parent.parent
TASKS = ROOT / "benchmark_pilot" / "tasks.json"
ATTR = ROOT / "benchmark_pilot" / "attribution.json"


def _load_controlled():
    if not (TASKS.exists() and ATTR.exists()):
        pytest.skip("run scripts/pilot_build.py first")
    tasks = json.loads(TASKS.read_text(encoding="utf-8"))
    attr = json.loads(ATTR.read_text(encoding="utf-8"))
    return {t["task_id"]: t for t in tasks["tasks"] if t["kind"] == "controlled"}, attr["controlled"]


def test_ordinary_assignment_can_be_disabled():
    source = "def program(x):\n    y = 0\n    y = 1\n    return y\n"
    assert v2.variant_source(source, {3}).count("y = 1") == 0
    out = v2.Program(v2.variant_source(source, {3})).call({"x": 0})
    assert out.ok and out.observation == ["return", ["int", 0]]


def test_assignment_relation_is_independent_on_witness():
    plus = "def program(x):\n    y = 0\n    y = 1\n    return y\n"
    minus = "def program(x):\n    pass\n    y = 1\n    return y\n"
    cases = v2.validate_cases([("c", {"x": 0})], ["x"])
    matrix = v2.run_matrix(plus, minus, {"B": 3}, cases, target_line=2)
    result = v2.verify_relation(matrix, "independent", ["B"], "c")
    assert result["valid"] is True
    assert result["status"] == "VERIFIED"
    assert result["scope"] == "single_witness"
    assert matrix.base_target_hits["c"] is True


def test_target_line_cannot_be_an_operation_line():
    source = "def program(x):\n    y = 0\n    y = 1\n    return y\n"
    with pytest.raises(v2.InterventionError):
        v2.resolve_operations(source, {"B": 2}, target_line=2)


def test_ambiguous_or_multiline_operation_line_is_rejected():
    ambiguous = "def program(x):\n    if x: y = 1\n    return y\n"
    with pytest.raises(v2.InterventionError):
        v2.resolve_operations(ambiguous, {"B": 2})
    multiline = "def program(x):\n    y = (\n        1\n    )\n    return y\n"
    with pytest.raises(v2.InterventionError):
        v2.resolve_operations(multiline, {"B": 2})


def test_missing_operation_line_is_rejected():
    source = "def program(x):\n    return x\n"
    with pytest.raises(v2.InterventionError):
        v2.resolve_operations(source, {"B": 99})


def test_legal_input_failure_is_not_a_masked_witness():
    plus = "def program(x):\n    return 10 // x\n"
    minus = "def program(x):\n    pass\n    return 10 // x\n"
    cases = v2.validate_cases([("zero", {"x": 0})], ["x"])
    matrix = v2.run_matrix(plus, minus, {}, cases, target_line=2)
    assert matrix.row(frozenset(), "zero").status == "INVALID_INPUT"
    result = v2.verify_relation(matrix, "independent", [], "zero")
    assert result["valid"] is False
    assert result["status"] == "MALFORMED_CLAIM"


def test_illegal_variant_is_reported_not_silently_false():
    plus = "def program(x):\n    y = 0\n    y = 1\n    return y\n"
    minus = "def program(x):\n    pass\n    y = \n    return y\n"
    cases = v2.validate_cases([("c", {"x": 0})], ["x"])
    matrix = v2.run_matrix(plus, minus, {"B": 3}, cases, target_line=2)
    result = v2.verify_relation(matrix, "independent", ["B"], "c")
    assert result["status"] == "ILLEGAL_INTERVENTION"
    assert matrix.errors


def test_guard_interpreter_does_not_call_builtin_eval(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError("guard evaluation must not call eval")

    monkeypatch.setattr(builtins, "eval", forbidden)
    assert v2.eval_guard("x == 1 and y < 3", ["x", "y"], {"x": 1, "y": 2}) is True
    assert v2.eval_guard("not (x == 2)", ["x"], {"x": 1}) is True


def test_guard_rejects_unsupported_constructs_and_unknown_names():
    with pytest.raises(v2.GuardError):
        v2.eval_guard("len(x) > 0", ["x"], {"x": 1})
    with pytest.raises(v2.GuardError):
        v2.eval_guard("y == 1", ["x"], {"x": 1})
    with pytest.raises(v2.GuardError):
        v2.eval_guard("x == 'a'", ["x"], {"x": 1})
    with pytest.raises(v2.GuardError):
        v2.eval_guard("1 // 0 == 0", [], {})


def test_guard_witness_scope_is_not_domain_exactness():
    cases = [v2.Case("a", {"x": 0}), v2.Case("b", {"x": 1})]
    masked = {"a": True, "b": False}
    witness = v2.verify_guard_witness("x == 0", ["x"], {"x": 0})
    assert witness["scope"] == "witness"
    assert witness["valid"] is True
    assert "exact" not in witness
    domain = v2.verify_guard_domain("x == 0", ["x"], cases, masked)
    assert domain["scope"] == "domain"
    assert domain["exact"] is True
    assert domain["domain_size"] == 2


def test_guard_domain_reports_incomplete_guard():
    cases = [v2.Case("a", {"x": 0}), v2.Case("b", {"x": 1})]
    masked = {"a": True, "b": True}
    row = v2.verify_guard_domain("x == 0", ["x"], cases, masked)
    assert row["sound"] is True
    assert row["complete"] is False
    assert row["exact"] is False


def test_old_controlled_matrix_matches_known_relations():
    tasks, attr = _load_controlled()

    def matrix_for(tid):
        task = tasks[tid]
        row = attr[tid]
        cases = v2.validate_cases(
            [(f"case_{i:04d}", args)
             for i, args in enumerate(task["input_domain"]["cases"])],
            [a["name"] for a in task["input_domain"]["args"]],
        )
        return v2.run_matrix(
            task["program"]["source"],
            task["deletion"]["p_minus_source"],
            row["op_lines"],
            cases,
            target_line=task["program"]["target_A"]["line"],
        )

    m = matrix_for("ctrl_01")
    assert v2.verify_relation(m, "independent", ["B"], "case_0000")["valid"]

    m = matrix_for("ctrl_02")
    assert v2.verify_relation(m, "cooperative", ["C", "D"], "case_0000")["valid"]
    assert not v2.verify_relation(m, "independent", ["C"], "case_0000")["valid"]

    m = matrix_for("ctrl_03")
    assert v2.verify_relation(m, "independent", ["B"], "case_0000")["valid"]
    assert v2.verify_relation(m, "coexisting", ["B", "E"], "case_0008")["valid"]
    assert v2.verify_relation(m, "cooperative", ["C", "D"], "case_0012")["valid"]
