import importlib.util
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
SPEC = importlib.util.spec_from_file_location("m6_repair",
                                              ROOT / "scripts" / "m6_repair.py")
m6_repair = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(m6_repair)


def _candidate(round_id, guard, valid):
    return {"round": round_id, "guard": guard, "valid": valid}


def test_split_is_disjoint_and_order_independent():
    cases = [{"x": i} for i in range(21)]
    fit, ev = m6_repair.split_cases(cases)
    assert {id(c) for c in fit}.isdisjoint({id(c) for c in ev})
    assert len(fit) + len(ev) == len(cases)
    shuffled = list(reversed(cases))
    fit2, ev2 = m6_repair.split_cases(shuffled)
    assert {c["x"] for c in fit} == {c["x"] for c in fit2}


def test_a_valid_incumbent_is_not_replaced_by_an_invalid_candidate():
    policy = m6_repair.OnlineRetention(lambda item: item["valid"])
    policy.offer(_candidate(1, "good", True))
    chosen = policy.offer(_candidate(2, "bad", False))
    assert chosen["guard"] == "good"


def test_revocation_allows_a_later_valid_candidate():
    states = {"good": True}
    policy = m6_repair.OnlineRetention(lambda item: states[item["guard"]])
    policy.offer(_candidate(1, "good", True))
    states["good"] = False  # a new counterexample revokes the incumbent
    chosen = policy.offer(_candidate(2, "better", True))
    assert chosen["guard"] == "better"


def test_two_invalid_candidates_keep_the_latest_for_reporting():
    policy = m6_repair.OnlineRetention(lambda item: item["valid"])
    policy.offer(_candidate(1, "a", False))
    chosen = policy.offer(_candidate(2, "b", False))
    assert chosen["guard"] == "b"
