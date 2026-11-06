"""Every declared fixture must have a reference bundle that the checker accepts.

This is the regression net for the engine itself: if the checker starts
rejecting a human-verified contract, the checker (not the fixture) is wrong.
"""
import json
from pathlib import Path

import pytest

from mace.fixture import load_fixture
from mace.loop import verify

ROOT = Path(__file__).resolve().parent.parent
FIXTURES = sorted(p.stem for p in (ROOT / "experiments").glob("*.json"))


@pytest.mark.parametrize("fixture_id", FIXTURES)
def test_reference_bundle_passes(fixture_id):
    fixture = load_fixture(f"{fixture_id}.json")
    reference = json.loads(
        (ROOT / "experiments" / "hidden" / f"{fixture_id}_reference.json")
        .read_text(encoding="utf-8"))["bundle"]
    report = verify(fixture, reference, timeout=120)
    assert report["status"] == "OK"
    assert report["guard_ok"] is True
    assert report["all_relations_pass"] is True, report.get("relations")


@pytest.mark.parametrize("fixture_id", FIXTURES)
def test_negated_guard_is_refuted(fixture_id):
    """Sanity check: the checker is not vacuously accepting everything."""
    fixture = load_fixture(f"{fixture_id}.json")
    reference = json.loads(
        (ROOT / "experiments" / "hidden" / f"{fixture_id}_reference.json")
        .read_text(encoding="utf-8"))["bundle"]
    reference["mask_guard"]["expr"] = "not (" + reference["mask_guard"]["expr"] + ")"
    report = verify(fixture, reference, timeout=120)
    assert report["guard_ok"] is False
