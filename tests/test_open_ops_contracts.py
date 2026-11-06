"""Regression tests for expanded operation discovery and contract hints.

These tests only use the frozen development fixtures and the three existing
real-source tasks.  They do not read private B/C/D/E attribution, do not call
a model, and do not create a new benchmark score.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from open_ops.contracts import contract_meta, load_default_contract  # noqa: E402
from open_ops.discover import (  # noqa: E402
    _condition_status,
    _relation_status,
    discover_expanded,
)
from open_ops import run_development as rd  # noqa: E402
from open_ops import to_submission  # noqa: E402
from check_open_interface import Verifier  # noqa: E402

TASKS_PATH = ROOT / "benchmark_pilot" / "tasks.json"
CLASSIFICATION_PATH = (
    ROOT / "benchmark_real_pilot" / "protocol_v2" /
    "real_case_classification.json")


@pytest.fixture(scope="module")
def tasks():
    if not TASKS_PATH.exists():
        pytest.skip("development tasks are not present")
    data = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    return {t["task_id"]: t for t in data["tasks"]}


def _relations(result):
    return {
        (rel.kind, tuple(op.line for op in rel.operations)): rel
        for rel in result.relations
    }


def test_control_state_keeps_c_as_prerequisite(tasks):
    task = rd._control_state_task()
    result = discover_expanded(task)

    assert result.status == "OK"
    assert [op.line for op in result.candidates] == [4, 5]
    rels = _relations(result)
    rel = rels[("independent", (5,))]
    assert rel.status == "VERIFIED"
    assert rel.condition_status == "EXACT"
    assert rel.condition == "(c < 1)"

    evidence = rel.evidence
    intervention = evidence["intervention"]
    # C (line 4) defines the condition B tests; it is a prerequisite, not an
    # alternative masker, so the sufficiency intervention keeps it enabled.
    assert intervention["disable_other_masking_candidates"]["kept_prerequisites"] \
        == ["op_L4_C4_assign"]
    assert intervention["disable_other_masking_candidates"]["disabled_keys"] == []
    assert intervention["disable_other_masking_candidates"]["masked"] is True
    # Disabling B itself exposes A; this is the intervention that establishes
    # B as the masking operation.
    assert intervention["disable_claimed_set"]["disabled_keys"] == ["op_L5_C4_if"]
    assert intervention["disable_claimed_set"]["exposes"] is True
    assert intervention["disable_claimed_set"]["p_plus"]["outcome"] == "return"
    assert intervention["disable_claimed_set"]["p_minus"]["outcome"] == "return"


def test_ctrl_03_covers_all_relation_kinds(tasks):
    result = discover_expanded(tasks["ctrl_03"])
    assert result.status == "OK"
    rels = _relations(result)

    assert rels[("independent", (4,))].status == "VERIFIED"
    assert rels[("independent", (6,))].status == "VERIFIED"
    assert rels[("cooperative", (8, 10))].status == "VERIFIED"
    assert rels[("coexisting", (4, 6))].status == "VERIFIED"
    # The cooperative pair must not also be reported as two independent
    # maskers: neither line 8 nor line 10 alone masks A.
    assert ("independent", (8,)) not in rels
    assert ("independent", (10,)) not in rels

    coop = rels[("cooperative", (8, 10))]
    # Neither operation alone may mask; every proper subset is checked.
    minimality = coop.evidence["minimality"]
    assert minimality["criterion"] == "proper_nonempty_subsets_do_not_mask"
    assert minimality["holds_on_witness"] is True
    assert all(not item["masks"] for item in minimality["results"].values())

    coexist = rels[("coexisting", (4, 6))]
    # Both backup paths must be disabled to expose A.
    assert coexist.checks["disabling_set_exposes"] is True
    assert all(coexist.checks["proper_subsets_do_not_expose"].values())
    assert coexist.evidence["minimality"]["criterion"] == \
        "proper_nonempty_subsets_do_not_expose"


def test_contract_arm_has_no_semantic_gain(tasks):
    for task_id in ("ctrl_01", "ctrl_02"):
        hint = load_default_contract(task_id, ROOT)
        assert hint.available is True
        assert hint.lines, "recorded MACE bundle should cite source lines"
        row = rd.run_task(tasks[task_id],
                          hint.path)
        comparison = row["comparison"]
        assert comparison["same_candidate_count"] is True
        assert comparison["same_subset_execution_budget"] is True
        assert comparison["contract_semantic_gain"] is False
        assert comparison["new_verified_relations_from_contract"] == []
        assert comparison["contract_only_candidates_used_by_verified_relation"] == []
        assert row["contract"]["confirmation"] == \
            "not_by_contract; execution_verifier_only"


def test_expanded_candidates_record_provenance():
    source = '''def program(x, c):
    v = x
    v = v + 1  # TARGET_A
    if c:
        if x > 0:
            v = 0
    else:
        if x > 0:
            v = 1
    return v
'''
    minus = source.replace("    v = v + 1  # TARGET_A",
                           "    pass  # P-: A deleted")
    result = discover_expanded({
        "task_id": "nested_provenance",
        "entry": "program",
        "program": {"source": source, "target_A": {"line": 3}},
        "deletion": {"p_minus_source": minus},
        "input_domain": {
            "args": [{"name": "x"}, {"name": "c"}],
            "cases": [{"x": x, "c": c} for x in (-1, 1) for c in (0, 1)],
        },
    })
    assert result.candidates, result.reason
    assert all("expanded_ast" in op.provenance for op in result.candidates)
    assert any("nested_control_body" in op.provenance
               for op in result.candidates)
    assert any("control_dependency" in op.provenance
               for op in result.candidates)


def test_real_url_unparse_finds_verified_witness_with_unknown_condition():
    task = rd._real_task("real_werkzeug_url_unparse")
    result = discover_expanded(task)

    assert result.status == "PARTIAL"
    assert result.unsupported == ()
    rels = _relations(result)
    rel = rels[("independent", (57,))]
    # The witness passes execution, but the finite input domain cannot express
    # the condition, so this is not claimed as an exact guard.
    assert rel.status == "WITNESS_ONLY"
    assert rel.condition is None
    assert rel.condition_status == "UNKNOWN"
    assert rel.condition_check["status"] == "ABSENT"
    assert "single_witness" in rel.evidence_scope

    evidence = rel.evidence
    assert evidence["witness_legal_under_p_plus"] is True
    assert evidence["p_minus"]["outcome"] == "return"
    assert evidence["intervention"]["disable_other_masking_candidates"]["masked"] \
        is True
    assert evidence["intervention"]["disable_claimed_set"]["exposes"] is True
    # Exposure happens through a P+ return vs a P- UnboundLocalError.
    assert evidence["intervention"]["disable_claimed_set"]["p_plus"]["outcome"] \
        == "return"
    assert evidence["intervention"]["disable_claimed_set"]["p_minus"]["outcome"] \
        == "raise"

    independent = rd._independent_verifier(task, result)
    assert independent["all_verified"] is True
    assert independent["relations"][0]["status"] == "VERIFIED"
    assert independent["relations"][0]["scope"] == "single_witness"


def test_real_unsupported_structures_are_reported():
    click = discover_expanded(rd._real_task("real_click_truncate_visible"))
    assert click.status == "UNSUPPORTED"
    assert any("line 29" in item for item in click.unsupported)
    assert click.relations == ()

    headers = discover_expanded(
        rd._real_task("real_werkzeug_headerset_update"))
    assert headers.status == "UNSUPPORTED"
    assert any("cross-function method effect" in item
               for item in headers.unsupported)
    assert headers.relations == ()


def test_ctrl_03_relations_are_runnable_and_scorable(tasks):
    attribution = json.loads(
        (ROOT / "benchmark_pilot" / "attribution.json")
        .read_text(encoding="utf-8"))["controlled"]["ctrl_03"]
    result = discover_expanded(tasks["ctrl_03"])
    submission = to_submission(result)
    assert len(submission["relations"]) == len(result.relations)

    verifier = Verifier(tasks["ctrl_03"], attribution)
    checks = [verifier.verify_relation(rel)
              for rel in submission["relations"]]
    assert all(check["status"] == "VERIFIED" for check in checks)
    assert {(rel["kind"], tuple(op["line"] for op in rel["operations"]))
            for rel in submission["relations"]} == {
        ("independent", (4,)),
        ("independent", (6,)),
        ("cooperative", (8, 10)),
        ("coexisting", (4, 6)),
    }


def test_status_taxonomy_keeps_witness_and_condition_separate():
    assert _relation_status({"status": "INVALID"}) == "INVALID"
    assert _relation_status({"status": "ABSENT"}) == "WITNESS_ONLY"
    assert _relation_status({"status": "VALID", "witness_value": None}) == \
        "UNVERIFIED"
    assert _relation_status({"status": "VALID", "witness_value": False}) == \
        "FALSE"
    assert _relation_status({"status": "VALID", "witness_value": True,
                             "exact": False}) == "WITNESS_ONLY"
    assert _relation_status({"status": "VALID", "witness_value": True,
                             "exact": True}) == "VERIFIED"

    assert _condition_status({"status": "ABSENT"}) == "UNKNOWN"
    assert _condition_status({"status": "INVALID"}) == "INVALID"
    assert _condition_status({"status": "VALID", "exact": True}) == "EXACT"
    assert _condition_status({"status": "VALID", "exact": False,
                              "sound": True}) == "SOUND_INCOMPLETE"
    assert _condition_status({"status": "VALID", "exact": False,
                              "sound": False}) == "UNSOUND"


def test_freeze_classification_keeps_two_uses_apart():
    data = json.loads(CLASSIFICATION_PATH.read_text(encoding="utf-8"))
    classes = data["classes"]
    surviving = {row["task_id"] for row in classes["TEST_SURVIVING_DELETION"]}
    masking_only = {row["task_id"] for row in classes["VERIFIED_MASKING_ONLY"]}
    assert surviving == {"real_click_truncate_visible"}
    assert masking_only == {
        "real_werkzeug_headerset_update",
        "real_werkzeug_url_unparse",
    }
    assert not surviving & masking_only
    assert "not_claimed" in data
