"""Tests for the benchmark pilot builder and independent scorer."""
from __future__ import annotations

import copy
import importlib
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import pilot_evaluate as pe  # noqa: E402
from benchmark_pilot import engine  # noqa: E402

TASKS_PATH = ROOT / "benchmark_pilot" / "tasks.json"
ORACLE_PATH = ROOT / "benchmark_pilot" / "oracle.json"
ATTRIBUTION_PATH = ROOT / "benchmark_pilot" / "attribution.json"


@pytest.fixture(scope="module")
def docs():
    if not (TASKS_PATH.exists() and ORACLE_PATH.exists()
            and ATTRIBUTION_PATH.exists()):
        pytest.skip("run scripts/pilot_build.py first")
    return (json.loads(TASKS_PATH.read_text(encoding="utf-8")),
            json.loads(ORACLE_PATH.read_text(encoding="utf-8")),
            json.loads(ATTRIBUTION_PATH.read_text(encoding="utf-8")))


@pytest.fixture(scope="module")
def ground(docs):
    tasks, oracle, attribution = docs
    return pe.build_ground(tasks, oracle, attribution)


@pytest.fixture(scope="module")
def perfect(ground):
    return pe.perfect_submission(ground)


# ---------------------------------------------------------------------------
# Task structure and leakage
# ---------------------------------------------------------------------------

def test_five_tasks_three_controlled_two_real(docs):
    tasks, _, _ = docs
    ids = [t["task_id"] for t in tasks["tasks"]]
    assert ids == ["ctrl_01", "ctrl_02", "ctrl_03",
                   "real_formatdef", "real_setdiff"]
    assert [t["kind"] for t in tasks["tasks"]] == [
        "controlled", "controlled", "controlled", "real", "real"]


def test_public_tasks_do_not_leak_roles_or_labels(docs):
    tasks, _, _ = docs
    text = json.dumps(tasks["tasks"], ensure_ascii=False)
    assert "OP_" not in text
    assert "absorber" not in text.lower()
    assert "coexisting" not in text.lower()
    assert "oracle" not in text.lower()
    assert "attribution" not in text.lower()
    for task in tasks["tasks"]:
        assert "# TARGET_A" in task["program"]["source"]
        assert task["input_domain"]["cases"]
        assert task["deletion"]["p_minus_source"]
        assert task["observable_behavior"]["kind"] == "return_value"
        assert task["existing_tests"] is not None


def test_controlled_non_degenerate(docs):
    _, oracle, _ = docs
    for tid in ("ctrl_01", "ctrl_02", "ctrl_03"):
        row = oracle["tasks"][tid]
        assert row["masked_with_local_effect_count"] > 0
        assert row["masked_count"] > 0
        assert row["exposed_count"] > 0


def test_controlled_claims_match_design(docs):
    _, _, attribution = docs
    got = {tid: {
        "absorbers": {(tuple(c["ops"]), c["kind"])
                      for c in row["absorber_sets"]},
        "coexisting": {tuple(c["ops"]) for c in row["coexisting_sets"]},
    } for tid, row in attribution["controlled"].items()}
    assert got["ctrl_01"]["absorbers"] == {(("B",), "independent")}
    assert got["ctrl_01"]["coexisting"] == set()
    assert got["ctrl_02"]["absorbers"] == {(("C", "D"), "cooperative")}
    assert got["ctrl_02"]["coexisting"] == set()
    assert got["ctrl_03"]["absorbers"] == {
        (("B",), "independent"), (("E",), "independent"),
        (("C", "D"), "cooperative")}
    assert got["ctrl_03"]["coexisting"] == {("B", "E")}


def test_real_provenance_is_complete(docs):
    tasks, _, attribution = docs
    by_id = {t["task_id"]: t for t in tasks["tasks"]}
    fmt = by_id["real_formatdef"]["provenance"]
    assert fmt["commit"] == "0999f64a8c2ab7c7d968ab2e8c8849629a6d891c"
    assert fmt["parent_commit"] == "6011c43de0a1ba729e950f066a44ea8932cecb05"
    assert fmt["license"].startswith("MIT")
    assert "Remove redundant str()" in fmt["commit_message"]
    for path in fmt["existing_tests"]["logs"]:
        assert (ROOT / path).exists(), path
    setdiff = by_id["real_setdiff"]["provenance"]
    assert setdiff["commit"] == "98f1b58bf3650e529373dbcc203fcca9619637ec"
    assert setdiff["parent_commit"] == "656bc3d04d3b452d501cfd955c53c5e724a61bc5"
    assert "set-like operations" in setdiff["commit_message"]
    for path in setdiff["existing_tests"]["logs"]:
        assert (ROOT / path).exists(), path
    assert by_id["real_setdiff"]["existing_tests"] == []
    assert by_id["real_setdiff"]["existing_test_suite"]["result_parent"] == "79 passed"
    assert attribution["real"]["real_formatdef"]["masking"]["status"] == "unconfirmed"
    assert attribution["real"]["real_setdiff"]["masking"]["status"] == "no_masking_relation"


def test_oracle_is_bounded_and_guard_free(docs):
    _, oracle, _ = docs
    assert oracle["evidence_level"] == "BOUNDED"
    text = json.dumps(oracle, ensure_ascii=False).lower()
    assert "proven" not in text.replace("no proven claim", "")
    assert "guard" not in text
    for task in oracle["tasks"].values():
        for row in task["cases"]:
            assert isinstance(row["observable_equal"], bool)


# ---------------------------------------------------------------------------
# Ground truth re-execution and self-test
# ---------------------------------------------------------------------------

def test_ground_recomputes_without_drift(ground):
    assert set(ground) == {"ctrl_01", "ctrl_02", "ctrl_03",
                           "real_formatdef", "real_setdiff"}
    for g in ground.values():
        assert g["cases"]
        assert all(isinstance(v, bool) for v in g["masked"].values())


def test_oracle_observation_drift_is_rejected(docs):
    tasks, oracle, attribution = copy.deepcopy(docs)
    oracle["tasks"]["ctrl_01"]["cases"][0]["observation_plus"] = [
        "return", ["int", 999]]
    with pytest.raises(pe.ScorerError, match="oracle drift"):
        pe.build_ground(tasks, oracle, attribution)


def test_attribution_drift_is_rejected(docs):
    tasks, oracle, attribution = copy.deepcopy(docs)
    attribution["controlled"]["ctrl_01"]["per_case"][0]["absorber_sets"] = []
    with pytest.raises(pe.ScorerError, match="attribution drift"):
        pe.build_ground(tasks, oracle, attribution)


def test_test_execution_drift_is_rejected(docs):
    tasks, oracle, attribution = copy.deepcopy(docs)
    oracle["tasks"]["ctrl_01"]["existing_tests"]["t_mode0_x0"]["plus"][
        "passed"] = False
    with pytest.raises(pe.ScorerError, match="oracle drift in test execution"):
        pe.build_ground(tasks, oracle, attribution)


def test_real_local_effect_drift_is_rejected(docs):
    tasks, oracle, attribution = copy.deepcopy(docs)
    oracle["tasks"]["real_setdiff"]["cases"][0]["a_has_local_effect"] = True
    with pytest.raises(pe.ScorerError, match="local-effect"):
        pe.build_ground(tasks, oracle, attribution)


def test_real_test_verdict_drift_is_rejected(docs):
    tasks, oracle, attribution = copy.deepcopy(docs)
    oracle["tasks"]["real_formatdef"]["existing_tests"]["test_formatdef"][
        "gold_verdict"] = "assertion_gap"
    with pytest.raises(pe.ScorerError, match="gold verdict"):
        pe.build_ground(tasks, oracle, attribution)


def test_perfect_submission_scores_correct(ground, perfect):
    report = pe.evaluate(perfect, ground)
    for tid in ("ctrl_01", "ctrl_02", "ctrl_03"):
        row = report["tasks"][tid]
        assert row["score_A_guard"]["exact"] is True
        assert row["score_B_masking"]["all_sets_exact"] is True
        assert row["score_B_masking"]["evidence_accuracy"] == 1.0
        assert row["score_C_witness"]["verdict"] == "valid_witnesses_found"
        assert row["score_D_test_gap"]["global_agree"] is True
        assert row["score_D_test_gap"]["per_test_accuracy"] == 1.0
    for tid in ("real_formatdef", "real_setdiff"):
        row = report["tasks"][tid]
        assert row["score_A_guard"]["exact"] is True
        assert row["score_B_masking"]["applicable"] is False
        assert row["score_C_witness"]["verdict"] == "correctly_none_exists"
        assert row["score_D_test_gap"]["global_agree"] is True


def test_sabotaged_submission_is_detected(ground, perfect):
    bad = pe.sabotaged_submission(perfect)
    report = pe.evaluate(bad, ground)
    assert report["tasks"]["ctrl_01"]["score_A_guard"]["exact"] is not True
    assert report["tasks"]["ctrl_02"]["score_B_masking"]["absorber"]["recall"] == 0.0
    assert report["tasks"]["ctrl_03"]["score_B_masking"]["missed_coexisting_relations"]
    assert report["tasks"]["real_formatdef"]["score_A_guard"]["complete"] is False
    assert report["tasks"]["real_setdiff"]["score_C_witness"]["invalid_count"] == 1
    assert report["tasks"]["real_setdiff"]["score_C_witness"]["verdict"] in {
        "invalid_witnesses_only", "claimed_exists_without_valid_witness"}
    assert report["tasks"]["ctrl_01"]["score_D_test_gap"]["per_test_accuracy"] < 1.0


# ---------------------------------------------------------------------------
# Guard status handling
# ---------------------------------------------------------------------------

def _with_guard(doc, tid, guard):
    out = copy.deepcopy(doc)
    for row in out["submissions"]:
        if row["task_id"] == tid:
            row["guard"] = guard
            return out
    raise AssertionError(tid)


def test_proven_requires_assumptions_and_proof(ground, perfect):
    bad = _with_guard(perfect, "ctrl_01", {"expr": "mode == 0",
                                          "status": "PROVEN"})
    report = pe.evaluate(bad, ground)
    assert report["tasks"]["ctrl_01"]["score_A_guard"]["status_valid"] is False

    good = _with_guard(perfect, "ctrl_01", {
        "expr": "mode == 0", "status": "PROVEN",
        "assumptions": ["mode and x are integers"],
        "formal_proof": "case analysis on mode",
    })
    report = pe.evaluate(good, ground)
    row = report["tasks"]["ctrl_01"]["score_A_guard"]
    assert row["status_valid"] is True
    assert row["proof_machine_checked"] is False
    assert row["proof_review_required"] is True
    assert row["exact"] is True


def test_unknown_abstention_is_valid_without_guard(ground, perfect):
    doc = _with_guard(perfect, "ctrl_02", {"status": "UNKNOWN"})
    report = pe.evaluate(doc, ground)
    row = report["tasks"]["ctrl_02"]["score_A_guard"]
    assert row["valid"] is True
    assert row["abstained"] is True
    assert row["exact"] is None
    assert row["status_valid"] is True


def test_unknown_with_guard_is_inconsistent(ground, perfect):
    doc = _with_guard(perfect, "ctrl_02",
                      {"expr": "c == 0 and d == 0", "status": "UNKNOWN"})
    report = pe.evaluate(doc, ground)
    row = report["tasks"]["ctrl_02"]["score_A_guard"]
    assert row["status_valid"] is False
    assert row["exact"] is not True  # the expression is incomplete


# ---------------------------------------------------------------------------
# Attribution and witness evidence
# ---------------------------------------------------------------------------

def test_matching_set_with_bad_witness_loses_evidence(ground, perfect):
    doc = copy.deepcopy(perfect)
    for row in doc["submissions"]:
        if row["task_id"] == "ctrl_01":
            # case_0003 is mode=1, where A is exposed.
            row["masking"]["absorber_sets"][0]["witness"] = {"case_id": "case_0003"}
    report = pe.evaluate(doc, ground)
    b = report["tasks"]["ctrl_01"]["score_B_masking"]
    assert b["absorber"]["exact"] is True
    assert b["evidence_accuracy"] == 0.0
    assert b["absorber"]["claims"][0]["evidence"]["valid"] is False


def test_false_no_counterexample_claim_is_detected(ground, perfect):
    doc = copy.deepcopy(perfect)
    for row in doc["submissions"]:
        if row["task_id"] == "ctrl_01":
            row["witnesses"] = []
            row["witness_claim"] = "none_exists"
    report = pe.evaluate(doc, ground)
    c = report["tasks"]["ctrl_01"]["score_C_witness"]
    assert c["verdict"] == "wrong_none_exists_claim"
    assert c["correct"] is False


def test_unstated_no_counterexample_is_not_full_credit(ground, perfect):
    doc = copy.deepcopy(perfect)
    for row in doc["submissions"]:
        if row["task_id"] == "real_setdiff":
            row["witnesses"] = []
            row.pop("witness_claim", None)
    report = pe.evaluate(doc, ground)
    c = report["tasks"]["real_setdiff"]["score_C_witness"]
    assert c["verdict"] == "none_exists_not_stated"
    assert c["correct"] is False


def test_out_of_domain_witness_is_invalid(ground, perfect):
    doc = copy.deepcopy(perfect)
    for row in doc["submissions"]:
        if row["task_id"] == "ctrl_01":
            row["witnesses"] = [{"mode": 0, "x": 99}]
    report = pe.evaluate(doc, ground)
    c = report["tasks"]["ctrl_01"]["score_C_witness"]
    assert c["valid_count"] == 0
    assert c["invalid_count"] == 1
    assert c["verdict"] in {"invalid_witnesses_only",
                            "claimed_exists_without_valid_witness"}


def test_cooperative_single_operation_is_rejected(ground, perfect):
    doc = copy.deepcopy(perfect)
    for row in doc["submissions"]:
        if row["task_id"] == "ctrl_02":
            row["test_gap"]["tests"][0]["masking_ops"] = ["C"]
    report = pe.evaluate(doc, ground)
    d = report["tasks"]["ctrl_02"]["score_D_test_gap"]
    row = next(r for r in d["tests"] if r["name"] == "t_rounds_x3")
    assert row["named_ops_valid"] is False


def test_coexisting_union_is_accepted_when_each_masks(ground, perfect):
    doc = copy.deepcopy(perfect)
    for row in doc["submissions"]:
        if row["task_id"] == "ctrl_03":
            for test in row["test_gap"]["tests"]:
                if test["name"] == "t_both_overwrite":
                    test["masking_ops"] = ["B", "E"]
    report = pe.evaluate(doc, ground)
    d = report["tasks"]["ctrl_03"]["score_D_test_gap"]
    row = next(r for r in d["tests"] if r["name"] == "t_both_overwrite")
    assert row["named_ops_valid"] is True
    assert row["named_ops_minimal"] is False


def test_perfect_submission_names_minimal_sets(ground, perfect):
    report = pe.evaluate(perfect, ground)
    for tid in ("ctrl_01", "ctrl_02", "ctrl_03"):
        d = report["tasks"][tid]["score_D_test_gap"]
        assert d["named_ops_minimality_accuracy"] == 1.0


def test_nonminimal_coexisting_claim_loses_evidence(ground, perfect):
    doc = copy.deepcopy(perfect)
    for row in doc["submissions"]:
        if row["task_id"] == "ctrl_03":
            row["masking"]["coexisting"].append({
                "ops": ["B", "D", "E"], "kind": "coexisting",
                "witness": {"case_id": "case_0008"},
            })
    report = pe.evaluate(doc, ground)
    b = report["tasks"]["ctrl_03"]["score_B_masking"]
    claim = next(c for c in b["coexisting"]["claims"]
                 if c["ops"] == ["B", "D", "E"])
    # Disabling every one operation still masks, but disabling {B,E} does not,
    # so {B,D,E} is not a minimal coexisting set.
    assert claim["evidence"]["valid"] is False
    assert claim["evidence"]["disable_one_still_masks"] == {
        "B": True, "D": True, "E": True}
    assert claim["evidence"]["disable_proper_subset_still_masks"]["B+E"] is False


def test_irrelevant_operation_is_rejected(ground, perfect):
    doc = copy.deepcopy(perfect)
    for row in doc["submissions"]:
        if row["task_id"] == "ctrl_03":
            for test in row["test_gap"]["tests"]:
                if test["name"] == "t_both_overwrite":
                    test["masking_ops"] = ["B", "C"]
    report = pe.evaluate(doc, ground)
    d = report["tasks"]["ctrl_03"]["score_D_test_gap"]
    row = next(r for r in d["tests"] if r["name"] == "t_both_overwrite")
    assert row["named_ops_valid"] is False


def test_malformed_submission_does_not_crash(ground, perfect):
    doc = copy.deepcopy(perfect)
    for row in doc["submissions"]:
        if row["task_id"] == "ctrl_01":
            row["guard"] = "mode == 0"
            row["masking"] = "not-a-dict"
            row["test_gap"] = "not-a-dict"
    report = pe.evaluate(doc, ground)
    assert report["tasks"]["ctrl_01"]["score_A_guard"]["valid"] is False
    assert report["tasks"]["ctrl_01"]["score_D_test_gap"]["global_agree"] is False


def test_guard_arithmetic_errors_do_not_crash(ground, perfect):
    doc = copy.deepcopy(perfect)
    for bad in (123, "1 // 0", "x % 0"):
        for row in doc["submissions"]:
            if row["task_id"] == "ctrl_01":
                row["guard"] = {"expr": bad, "status": "BOUNDED"}
        report = pe.evaluate(doc, ground)
        guard = report["tasks"]["ctrl_01"]["score_A_guard"]
        assert guard["valid"] is False
        assert "rejected" in guard["reason"] or "raised" in guard["reason"]


def test_missing_task_is_reported(ground, perfect):
    doc = copy.deepcopy(perfect)
    doc["submissions"] = [r for r in doc["submissions"]
                          if r["task_id"] != "real_setdiff"]
    report = pe.evaluate(doc, ground)
    assert "real_setdiff" in report["missing_tasks"]
    assert report["tasks"]["real_setdiff"]["score_A_guard"]["valid"] is False


def test_missing_controlled_task_zeroes_all_scores(ground, perfect):
    doc = copy.deepcopy(perfect)
    doc["submissions"] = [r for r in doc["submissions"]
                          if r["task_id"] != "ctrl_02"]
    report = pe.evaluate(doc, ground)
    row = report["tasks"]["ctrl_02"]
    assert row["score_A_guard"]["valid"] is False
    assert row["score_B_masking"]["all_sets_exact"] is False
    assert row["score_C_witness"]["correct"] is False
    assert row["score_D_test_gap"]["global_agree"] is False


def test_none_found_is_not_none_exists(ground, perfect):
    doc = copy.deepcopy(perfect)
    for row in doc["submissions"]:
        if row["task_id"] == "ctrl_01":
            row["witnesses"] = []
            row["witness_claim"] = "none_found"
    report = pe.evaluate(doc, ground)
    c = report["tasks"]["ctrl_01"]["score_C_witness"]
    assert c["verdict"] == "none_found_but_exists"
    assert c["correct"] is False


def test_wrong_bucket_is_penalized(ground, perfect):
    doc = copy.deepcopy(perfect)
    for row in doc["submissions"]:
        if row["task_id"] == "ctrl_01":
            row["masking"]["coexisting"] = row["masking"]["absorber_sets"]
            row["masking"]["absorber_sets"] = []
    report = pe.evaluate(doc, ground)
    b = report["tasks"]["ctrl_01"]["score_B_masking"]
    assert b["absorber"]["exact"] is False
    assert b["coexisting"]["exact"] is False
    assert b["coexisting"]["claims"][0]["evidence"]["valid"] is False


# ---------------------------------------------------------------------------
# Engine primitives
# ---------------------------------------------------------------------------

def test_op_comments_stripped_without_moving_lines(docs):
    tasks, _, _ = docs
    source = tasks["tasks"][0]["program"]["source"]
    assert source.count("# TARGET_A") == 1
    assert engine.target_line(source) == 3
    assert "OP_" not in source


def test_disable_if_changes_semantics():
    source = "def program(x):\n    v = x\n    if x == 0:\n        v = 42\n    return v\n"
    plus = engine.compile_source(source).call("program", {"x": 0})["observation"]
    disabled = engine.compile_source(
        engine.variant_source(source, {3})).call(
            "program", {"x": 0})["observation"]
    assert plus != disabled


def test_guard_rejects_calls_and_unknown_names():
    with pytest.raises(engine.GuardError):
        engine.eval_guard("len(x) > 0", ["x"], {"x": 1})
    with pytest.raises(engine.GuardError):
        engine.eval_guard("y == 1", ["x"], {"x": 1})
