from mace.fixture import load_fixture
from mace.induct import (Predicate, build_pool, classify, induce,
                         normalise_clauses, split_cases, witnesses)
from mace.symbolic import parse_expr


def test_split_cases_is_disjoint_and_covers_everything():
    cases = [{"x": i} for i in range(40)]
    fit, ev = split_cases(cases)
    assert len(fit) == 20 and len(ev) == 20
    assert {id(c) for c in fit}.isdisjoint({id(c) for c in ev})
    assert {id(c) for c in fit + ev} == {id(c) for c in cases}


def test_witness_labels_follow_the_paired_execution():
    fixture = load_fixture("alt_masking.json")
    data = witnesses(fixture)
    for case in data["cases"]:
        expected = case["args"]["mode"] in (0, 1)
        assert case["masked"] is expected
    # The pre-state is the value before A, the post-state after A.
    first = next(c for c in data["cases"] if c["args"]["mode"] == 0)
    assert first["pre"]["v"] + 1 == first["post"]["v"]


def test_pool_levels_differ_on_list_content():
    fixture = load_fixture("alt_masking.json")
    generic = {p.expr for p in build_pool(fixture, level="generic")}
    full = {p.expr for p in build_pool(fixture, level="full")}
    assert not any("sum(" in expr for expr in generic)
    assert any("sum(" in expr for expr in full)


def test_induction_returns_a_bounded_guard_not_a_proof():
    fixture = load_fixture("toggle_pair.json")
    result = induce(fixture, level="full")
    guard = result["sufficient"]["guard"]
    assert result["check"]["status"] == "BOUNDED"
    assert result["check"]["exact"] is True
    assert "flag" in guard
    assert result["sufficient"]["kind"] == "exact"
    # The guard must be inside the typed term language.
    assert parse_expr(guard) is not None


def test_classify_distinguishes_sufficient_necessary_and_exact():
    always = [[Predicate("True", "const", lambda args: True)]]
    never = [[Predicate("False", "const", lambda args: False)]]
    labels = [{"args": {}, "masked": True}, {"args": {}, "masked": False}]
    assert classify(labels, always)["exact"] is False
    assert classify(labels, always)["sound"] is False
    assert classify(labels, never)["sound"] is True
    assert classify(labels, never)["complete"] is False


def test_absorption_drops_a_strictly_weaker_clause():
    a = Predicate("a", "test", lambda args: True)
    b = Predicate("b", "test", lambda args: True)
    c = Predicate("c", "test", lambda args: True)
    clauses = normalise_clauses([[a], [a, b], [c]])
    assert [p.expr for p in clauses[0]] == ["a"]
    assert {tuple(p.expr for p in clause) for clause in clauses} == {("a",), ("c",)}
