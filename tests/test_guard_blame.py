"""Localizing a wrong guard to the top-level subterm that caused it."""
import copy
import json
from pathlib import Path

from mace.fixture import load_fixture
from mace.loop import verify
from mace.prompts import repair_prompt

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = json.loads(
    (ROOT / "experiments" / "hidden" / "sort_channel_reference.json").read_text(encoding="utf-8")
)["bundle"]


def _verify_with_guard(expr):
    bundle = copy.deepcopy(REFERENCE)
    bundle["mask_guard"]["expr"] = expr
    return verify(load_fixture("sort_channel.json"), bundle)


def test_single_wrong_disjunct_is_named():
    report = _verify_with_guard("True")
    guard = report["guard"]
    assert guard["status"] == "REFUTED"
    assert guard["parts"] == ["True"]
    assert guard["blame"]["accepts_wrong"][0] > 0
    assert guard["blame"]["rejects_wrong"][0] == 0


def test_blame_falls_on_the_permissive_disjunct_not_the_correct_one():
    # The first disjunct is genuinely correct on the domain; the second accepts
    # every input, so every wrong verdict must be charged to subterm #1.
    report = _verify_with_guard("pre or True")
    guard = report["guard"]
    assert guard["shape"] == "or"
    assert guard["blame"]["accepts_wrong"][0] == 0
    assert guard["blame"]["accepts_wrong"][1] > 0
    example = next(e for e in guard["counterexamples"] if e["kind"] == "unsound")
    assert example["parts"] == [False, True]


def test_incomplete_guard_is_charged_to_the_false_disjuncts():
    report = _verify_with_guard("pre or (use_left and use_right)")
    guard = report["guard"]
    assert guard["unsound"] == 0 and guard["incomplete"] > 0
    assert guard["blame"]["rejects_wrong"][0] > 0
    assert guard["blame"]["rejects_wrong"][1] > 0


def test_blame_reaches_the_repair_prompt():
    report = _verify_with_guard("pre or True")
    failures = [{"id": "G", "kind": "mask_guard", "expr": "pre or True",
                 "condition": "True", **report["guard"]}]
    text = repair_prompt(previous={"mask_guard": {"expr": "x"}}, failures=failures,
                         check_summary="10912 paired executions (BOUNDED domain)")
    assert "subterm #1" in text
    assert "subterm #0" not in text


def test_unknown_post_name_explains_where_it_is_allowed():
    report = _verify_with_guard("pre or xs_post == sorted(xs)")
    assert report["guard"]["status"] == "INVALID"
    assert "target_effects" in report["guard"]["reason"]
