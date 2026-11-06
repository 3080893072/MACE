import pytest

from mace.contracts import ContractError, parse_bundle

GOOD = {
    "target_effects": [{"id": "T1", "expr": "xs_post == sorted(xs)", "source_lines": [5]}],
    "upstream": [{"id": "U1", "expr": "fn_0(xs) == sorted(xs)", "condition": "pre"}],
    "observers": [{"id": "O0", "channel": 0, "expr": "xs[0]",
                   "condition": "xs[0] == min(xs)"}],
    "mask_guard": {"id": "G", "expr": "pre or xs[0] == min(xs)"},
    "uncertainty": "",
}


def test_valid_bundle_roundtrip():
    bundle = parse_bundle(GOOD)
    assert bundle.mask_guard.expr == "pre or xs[0] == min(xs)"
    assert bundle.to_dict()["observers"][0]["channel"] == 0


def test_missing_key():
    bad = dict(GOOD)
    del bad["upstream"]
    with pytest.raises(ContractError, match="missing"):
        parse_bundle(bad)


def test_duplicate_ids():
    bad = {**GOOD, "upstream": [{"id": "T1", "expr": "True"}]}
    with pytest.raises(ContractError, match="unique"):
        parse_bundle(bad)


def test_several_observers_per_channel_are_legal():
    """One observer per case must parse; the composer ORs verified conditions."""
    bundle = parse_bundle({**GOOD, "observers": [
        {"id": "O0", "channel": 0, "expr": "xs[0]", "condition": "True"},
        {"id": "O1", "channel": 0, "expr": "xs[0]", "condition": "pre"}]})
    assert [r.id for r in bundle.observers] == ["O0", "O1"]


def test_bad_syntax():
    bad = {**GOOD, "mask_guard": {"id": "G", "expr": "pre or"}}
    with pytest.raises(ContractError, match="not a parsable"):
        parse_bundle(bad)


def test_guard_only_requires_explicit_flag():
    guard_only = {"target_effects": [], "upstream": [], "observers": [],
                  "mask_guard": {"id": "G", "expr": "pre"}}
    with pytest.raises(ContractError, match="target_effect"):
        parse_bundle(guard_only)
    assert parse_bundle(guard_only, allow_guard_only=True).mask_guard.expr == "pre"
