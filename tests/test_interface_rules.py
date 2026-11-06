"""The variable-scope rules of each contract field, as tests.

Phase 1 of the diagnosis fixed four vocabularies that had been implicit:

    target_effects   entry args (pre-A state, plain names used in the source)
                     + <name>_post (state right after A, P+ only)
    upstream         entry args only
    observers        entry args + the post-A state under its plain names
                     (the observer describes what the downstream code sees)
    mask_guard       entry args only  -- never a post-state name, never the
                     real output

The tests below pin each rule down, plus the two ways a guard could cheat:
mentioning a post-state name, or mentioning the checker's own output fields.
"""
import json
from pathlib import Path

import pytest

from mace.compose import compose_guard
from mace.contracts import parse_bundle
from mace.domain import build_domain, input_sorts
from mace.program import build_callables, build_pair, run_pair
from mace.terms import signature_table
from mace.verify import verify_bundle

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = sorted((ROOT / "experiments").glob("*.json"))


def _load(config_path):
    config = json.loads(config_path.read_text(encoding="utf-8"))
    fixture_id = config_path.stem
    source = (ROOT / "fixtures" / f"{fixture_id}.py").read_text(encoding="utf-8")
    reference = json.loads(
        (ROOT / "experiments" / "hidden" / f"{fixture_id}_reference.json")
        .read_text(encoding="utf-8"))["bundle"]
    pair = build_pair(source)
    domain = build_domain(config["domain"])
    rows = run_pair(pair, domain.cases)
    return config, reference, pair, rows


def _report(config, bundle, pair, rows):
    return verify_bundle(
        rows, parse_bundle(bundle),
        input_sorts=input_sorts(config["domain"]),
        functions=signature_table(config["functions"]),
        callables=build_callables(pair),
        level="BOUNDED", channels=config.get("channels", 2))


@pytest.mark.parametrize("config_path", FIXTURES, ids=lambda p: p.stem)
def test_reference_contract_compiles_in_every_field(config_path):
    """A correct contract must be type-correct in the vocabulary of its field."""
    config, reference, pair, rows = _load(config_path)
    report = _report(config, reference, pair, rows)
    invalid = [r["id"] for r in report["relations"] if r["status"] == "INVALID"]
    assert invalid == [], f"{config_path.stem}: reference relations rejected: {invalid}"
    assert report["guard"]["status"] != "INVALID", report["guard"].get("reason")
    assert report["all_relations_pass"] is True


@pytest.mark.parametrize("config_path", FIXTURES, ids=lambda p: p.stem)
def test_composer_reproduces_the_reference_guard_on_the_domain(config_path):
    """Given a correct contract, deterministic composition is exact (ceiling D)."""
    config, reference, pair, rows = _load(config_path)
    report = _report(config, reference, pair, rows)
    derived = report["composition"]["derived_guard"]
    assert derived["compose_status"] == "COMPOSED"
    assert derived["status"] in ("BOUNDED", "TESTED")
    assert derived["unsound"] == 0 and derived["incomplete"] == 0
    assert derived["equivalent_to_declared_guard_on_domain"] is True


@pytest.fixture(scope="module")
def sort_scene():
    return _load(ROOT / "experiments" / "sort_channel.json")


def test_guard_may_not_mention_a_post_state_name(sort_scene):
    config, reference, pair, rows = sort_scene
    bundle = json.loads(json.dumps(reference))
    bundle["mask_guard"]["expr"] = "pre or xs == xs_post"
    report = _report(config, bundle, pair, rows)
    assert report["guard"]["status"] == "INVALID"
    reason = report["guard"]["reason"]
    assert "xs_post" in reason
    assert "entry arguments only" in reason


@pytest.mark.parametrize("name", ["out_plus", "out_minus", "outputs_equal"])
def test_guard_may_not_use_checker_output_fields(sort_scene, name):
    config, reference, pair, rows = sort_scene
    bundle = json.loads(json.dumps(reference))
    bundle["mask_guard"]["expr"] = f"pre or {name}"
    report = _report(config, bundle, pair, rows)
    assert report["guard"]["status"] == "INVALID"
    assert "unknown variable" in report["guard"]["reason"]


def test_observer_condition_may_not_read_the_real_output(sort_scene):
    config, reference, pair, rows = sort_scene
    bundle = json.loads(json.dumps(reference))
    bundle["observers"][0]["condition"] = "out_minus == out_plus"
    report = _report(config, bundle, pair, rows)
    observer = next(r for r in report["relations"] if r["id"] == "O0")
    assert observer["status"] == "INVALID"
    assert "unknown variable" in observer["reason"]


def test_observer_must_be_faithful_in_both_versions(sort_scene):
    """An expression that only matches the P+ answer is refuted, not composed."""
    config, reference, pair, rows = sort_scene
    bundle = json.loads(json.dumps(reference))
    bundle["observers"][0]["expr"] = "2 if pre else 0"
    bundle["observers"][0]["condition"] = "True"
    report = _report(config, bundle, pair, rows)
    observer = next(r for r in report["relations"] if r["id"] == "O0")
    assert observer["status"] == "REFUTED"
    assert observer["faithful_minus_failures"] > 0
    composed = compose_guard(parse_bundle(bundle), report, config.get("channels", 2))
    assert "O0" not in composed["observer_relations"]
    assert "O1" in composed["observer_relations"]


def test_several_observers_may_describe_one_channel(sort_scene):
    """One observer per case is legal; only the verified ones enter the OR.

    This is how the model naturally writes a two-branch observation, and
    rejecting it threw away correct contracts (see docs/M5_diagnosis.md).
    """
    config, reference, pair, rows = sort_scene
    bundle = json.loads(json.dumps(reference))
    extra = dict(bundle["observers"][0])
    extra["id"] = "O9"
    bundle["observers"].append(extra)
    report = _report(config, bundle, pair, rows)
    assert report["guard"]["status"] != "INVALID"
    composed = compose_guard(parse_bundle(bundle), report, config.get("channels", 2))
    assert "O9" in composed["observer_relations"]
    assert composed["status"] == "COMPOSED"


def test_dead_store_contract_can_still_be_exact(tmp_path):
    """A's effect can be genuinely unobservable; then a guard `True` is right.

    This is why the checker may not reject an observer merely for not mentioning
    the variables A changes: a dead store has no such observer at all.
    """
    from mace.loop import verify
    from mace.fixture import load_fixture

    fixture = load_fixture("dead_flag.json")
    reference = json.loads(
        (ROOT / "experiments" / "hidden" / "dead_flag_reference.json")
        .read_text(encoding="utf-8"))["bundle"]
    report = verify(fixture, reference, timeout=120)
    assert report["all_relations_pass"] is True
    assert report["composition"]["derived_guard"]["compose_status"] == "COMPOSED"
    assert report["composition"]["derived_guard"]["status"] in ("BOUNDED", "TESTED")


def test_false_fixed_point_is_demoted_and_not_composed(sort_scene):
    """A relation that is true but does not make A a no-op may not enter the OR.

    This is the composition bug that turned a `True` upstream fact into an
    unsound `True` guard: the checker verified the expression but never checked
    the implication the composition relies on.
    """
    config, reference, pair, rows = sort_scene
    bundle = json.loads(json.dumps(reference))
    for rel in bundle["upstream"]:
        rel["expr"] = "True"
        rel["condition"] = "True"
        rel["role"] = "fixed_point"
    report = _report(config, bundle, pair, rows)
    upstream = next(r for r in report["relations"] if r["kind"] == "upstream")
    assert upstream["status"] == "REFUTED"
    assert "not a fixed point" in upstream["reason"]
    assert report["composition"]["upstream_fixed_point"]["status"] == "REFUTED"
    composed = compose_guard(parse_bundle(bundle), report, config.get("channels", 2))
    assert composed["fixed_point_relations"] == []


def test_target_effect_sees_both_states(sort_scene):
    config, reference, pair, rows = sort_scene
    bundle = json.loads(json.dumps(reference))
    # Only target_effects may say xs_post; the same text in the guard is illegal.
    assert any("_post" in r["expr"] for r in bundle["target_effects"])
    report = _report(config, bundle, pair, rows)
    assert next(r for r in report["relations"]
                if r["kind"] == "target_effect")["status"] in ("BOUNDED", "TESTED")
