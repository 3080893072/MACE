"""Regression tests for the core-logic repair (audit A1-A2, B1-B6, C1-C9).

The tests below pin the defects that were confirmed in
``docs/MACE_logic_and_run_provenance_audit.md``.  They are intentionally
written against the explicit ``core_logic=True`` / ``core_logic="candidates"``
path so the historical default remains byte-compatible.
"""
import json
from pathlib import Path

import pytest

from mace.compose import compose_guard
from mace.contracts import parse_bundle
from mace.core_logic import (CandidatePool, classify_guard_report,
                             classify_relation_evidence)
from mace.domain import build_domain, input_sorts
from mace.program import build_callables, build_pair, run_pair
from mace.terms import signature_table
from mace.verify import verify_bundle

ROOT = Path(__file__).resolve().parent.parent


def _scene(fixture_id):
    config = json.loads((ROOT / "experiments" / f"{fixture_id}.json")
                        .read_text(encoding="utf-8"))
    source = (ROOT / "fixtures" / f"{fixture_id}.py").read_text(encoding="utf-8")
    reference = json.loads(
        (ROOT / "experiments" / "hidden" / f"{fixture_id}_reference.json")
        .read_text(encoding="utf-8"))["bundle"]
    pair = build_pair(source)
    domain = build_domain(config["domain"])
    rows = run_pair(pair, domain.cases)
    return config, reference, pair, rows


def _report(config, bundle, pair, rows, *, core_logic=False):
    return verify_bundle(
        rows, parse_bundle(bundle),
        input_sorts=input_sorts(config["domain"]),
        functions=signature_table(config["functions"]),
        callables=build_callables(pair),
        level="BOUNDED", channels=config.get("channels", 2),
        core_logic=core_logic)


# ---- C1: observer condition scope ---------------------------------------

def test_observer_condition_post_name_is_invalid_in_core_not_refuted_legacy():
    config, reference, pair, rows = _scene("clamp_absorb")
    bundle = json.loads(json.dumps(reference))
    bundle["observers"][0]["condition"] = "total > 0"
    legacy = _report(config, bundle, pair, rows, core_logic=False)
    core = _report(config, bundle, pair, rows, core_logic=True)
    legacy_o0 = next(r for r in legacy["relations"] if r["id"] == "O0")
    core_o0 = next(r for r in core["relations"] if r["id"] == "O0")
    assert legacy_o0["status"] == "REFUTED"          # old scope mismatch
    assert core_o0["status"] == "INVALID"            # new scope error
    assert "entry arguments" in core_o0["reason"]


# ---- C2: duplicate observers must not block soundness --------------------

def test_duplicate_observers_keep_soundness_in_core():
    config, reference, pair, rows = _scene("sort_channel")
    bundle = json.loads(json.dumps(reference))
    extra = dict(bundle["observers"][0])
    extra["id"] = "O9"
    bundle["observers"].append(extra)
    legacy = _report(config, bundle, pair, rows, core_logic=False)
    core = _report(config, bundle, pair, rows, core_logic=True)
    assert legacy["observer_soundness"]["status"] == "UNKNOWN"
    assert core["observer_soundness"]["status"] in ("BOUNDED", "TESTED")
    assert core["observer_soundness"]["checked"] > 0


# ---- C3 / A2: fixed-point aggregate must not be BOUNDED with checked=0 ---

def test_fixed_point_aggregate_reports_unknown_without_witness():
    config, reference, pair, rows = _scene("sort_channel")
    bundle = json.loads(json.dumps(reference))
    bundle["upstream"][0]["condition"] = "False"
    bundle["upstream"][0]["expr"] = "True"
    bundle["upstream"][0]["role"] = "fixed_point"
    legacy = _report(config, bundle, pair, rows, core_logic=False)
    core = _report(config, bundle, pair, rows, core_logic=True)
    assert legacy["composition"]["upstream_fixed_point"]["status"] == "BOUNDED"
    assert legacy["composition"]["upstream_fixed_point"]["checked"] == 0
    assert core["composition"]["upstream_fixed_point"]["status"] == "UNKNOWN"
    assert "witness" in core["composition"]["upstream_fixed_point"]["reason"]


# ---- A1 / C4: no-witness relations cannot enter Composer -----------------

def test_composer_excludes_no_witness_observer():
    config, reference, pair, rows = _scene("sort_channel")
    bundle = json.loads(json.dumps(reference))
    bundle["observers"][0]["condition"] = "False"
    report = _report(config, bundle, pair, rows, core_logic=True)
    composed = compose_guard(parse_bundle(bundle), report,
                             config.get("channels", 2), require_witness=True)
    assert "O0" not in composed["observer_relations"]
    assert composed["status"] == "INCOMPLETE"
    assert "O0" in [item["id"] for item in composed["unverified_relations"]]


def test_composer_states_it_is_only_a_sufficient_candidate():
    config, reference, pair, rows = _scene("sort_channel")
    report = _report(config, reference, pair, rows, core_logic=True)
    composed = compose_guard(parse_bundle(reference), report,
                             config.get("channels", 2), require_witness=True)
    assert composed["semantics"] == "sufficient_only"
    assert composed["necessary_conditions"] == []
    assert composed["exact_equivalence"] == "not_established"
    assert composed["complete"] is False


# ---- B4 / C: candidate retention ----------------------------------------

def test_candidate_pool_does_not_replace_exact_with_invalid():
    pool = CandidatePool(prefer="qwen")
    pool.offer({"expr": "good", "source": "qwen", "round": 1,
                "guard": {"status": "BOUNDED", "unsound": 0, "incomplete": 0,
                          "checked": 10, "evaluation_errors": 0}})
    pool.offer({"expr": "bad", "source": "qwen", "round": 2,
                "guard": {"status": "INVALID", "unsound": 0, "incomplete": 0,
                          "checked": 0, "evaluation_errors": 0}})
    chosen = pool.select()
    assert chosen["expr"] == "good"
    assert "invalid" in chosen["selection_reason"].lower()


def test_candidate_pool_revokes_an_exact_guard_on_new_counterexample():
    reports = {
        "good": {"status": "BOUNDED", "unsound": 0, "incomplete": 0,
                 "checked": 10, "evaluation_errors": 0},
        "better": {"status": "BOUNDED", "unsound": 0, "incomplete": 0,
                   "checked": 10, "evaluation_errors": 0},
    }
    pool = CandidatePool(prefer="qwen")
    pool.offer({"expr": "good", "source": "qwen", "round": 1, "guard": reports["good"]})
    reports["good"] = {"status": "REFUTED", "unsound": 1, "incomplete": 0,
                       "checked": 10, "evaluation_errors": 0}
    pool.offer({"expr": "better", "source": "derived", "round": 2, "guard": reports["better"]})
    pool.recheck(lambda expr: reports[expr])
    chosen = pool.select()
    assert chosen["expr"] == "better"


# ---- C: exact guard stops before unrelated auxiliary repair --------------

class FakeClient:
    provider = "fake"
    model = "fake-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, purpose="", json_mode=True):
        from mace.qwen import Response
        content = self.responses.pop(0)
        stats = {"prompt_tokens": 10, "completion_tokens": 5, "wall_seconds": 0.001}
        self.calls.append({"purpose": purpose, "messages": messages,
                           "stats": stats, "response": content})
        return Response(content=content, stats=stats)


def test_core_stops_when_guard_is_exact_even_if_auxiliary_relation_fails(tmp_path):
    from mace import loop
    from mace.fixture import load_fixture

    reference = json.loads(
        (ROOT / "experiments" / "hidden" / "sort_channel_reference.json")
        .read_text(encoding="utf-8"))["bundle"]
    broken = json.loads(json.dumps(reference))
    broken["observers"][0]["condition"] = "True"     # auxiliary relation fails
    never = json.dumps({"mask_guard": {"expr": "False"}})
    client = FakeClient([json.dumps(broken), never])
    fixture = load_fixture("sort_channel.json")
    result = loop.run_mode(fixture, client, "mace", rounds=2, seed=0,
                           out_dir=tmp_path, core_logic="candidates")
    assert result["rounds_used"] == 1
    assert result["status"] == "GUARD_VERIFIED"
    assert result["final_guard"] == reference["mask_guard"]["expr"]
    assert result["final_report"]["guard_ok"] is True
    assert result["final_report"]["all_relations_pass"] is False
    assert len(client.calls) == 1


# ---- feedback taxonomy ---------------------------------------------------

@pytest.mark.parametrize("guard,expected", [
    ({"status": "REFUTED", "unsound": 2, "incomplete": 0}, "FALSE_ACCEPT"),
    ({"status": "REFUTED", "unsound": 0, "incomplete": 2}, "FALSE_REJECT"),
    ({"status": "INVALID", "unsound": 0, "incomplete": 0}, "INVALID_CONTRACT"),
    ({"status": "REFUTED", "unsound": 0, "incomplete": 1,
      "evaluation_errors": 1}, "EVALUATION_ERROR"),
    ({"status": "UNKNOWN", "unsound": 0, "incomplete": 0}, "UNKNOWN"),
])
def test_guard_failure_taxonomy(guard, expected):
    assert classify_guard_report({"guard": guard}) == expected


def test_relation_without_witness_is_unverified_not_bounded():
    rel = {"id": "O0", "kind": "observer", "status": "BOUNDED",
           "checked": 10, "invariance_checked": 0,
           "faithful_failures": 0, "faithful_minus_failures": 0,
           "invariance_failures": 0, "evaluation_errors": 0}
    assert classify_relation_evidence(rel) == "UNVERIFIED_RELATION"


def test_core_rejects_unknown_level(tmp_path):
    from mace import loop
    from mace.fixture import load_fixture
    fixture = load_fixture("sort_channel.json")
    client = FakeClient([])
    with pytest.raises(ValueError, match="core_logic"):
        loop.run_mode(fixture, client, "mace", rounds=1, seed=0,
                      out_dir=tmp_path, core_logic="not-a-level")


# ---- C8: a missing channel is INCOMPLETE, not UNKNOWN ---------------------

def test_derived_guard_reports_incomplete_when_a_channel_has_no_witness():
    config, reference, pair, rows = _scene("sort_channel")
    bundle = json.loads(json.dumps(reference))
    bundle["observers"][0]["condition"] = "False"
    report = _report(config, bundle, pair, rows, core_logic=True)
    derived = report["composition"]["derived_guard"]
    assert derived["status"] == "INCOMPLETE"
    assert derived["compose_status"] == "INCOMPLETE"
    assert derived["missing_channels"]


# ---- C9: the gated adapter must not collapse INVALID into UNVERIFIED ------

def test_gated_report_preserves_invalid_and_refuted():
    from mace.evidence_gate import filtered_report
    report = {"relations": [
        {"id": "X", "kind": "observer", "status": "INVALID",
         "checked": 0, "faithful_failures": 0, "faithful_minus_failures": 0,
         "invariance_checked": 0, "invariance_failures": 0,
         "evaluation_errors": 0},
        {"id": "Y", "kind": "observer", "status": "REFUTED",
         "checked": 5, "faithful_failures": 1, "faithful_minus_failures": 0,
         "invariance_checked": 2, "invariance_failures": 0,
         "evaluation_errors": 0},
        {"id": "Z", "kind": "observer", "status": "BOUNDED",
         "checked": 5, "faithful_failures": 0, "faithful_minus_failures": 0,
         "invariance_checked": 0, "invariance_failures": 0,
         "evaluation_errors": 0},
    ]}
    out = {r["id"]: r["status"] for r in filtered_report(report)["relations"]}
    assert out == {"X": "INVALID", "Y": "REFUTED", "Z": "UNVERIFIED"}


# ---- C4/D: witness gating is the difference between candidates and full ---

def test_full_witness_gate_changes_composition_not_bugs_or_candidates():
    config, reference, pair, rows = _scene("sort_channel")
    bundle = json.loads(json.dumps(reference))
    bundle["observers"][0]["condition"] = "False"   # never true on the domain
    cand = _report(config, bundle, pair, rows, core_logic="candidates")
    full = _report(config, bundle, pair, rows, core_logic="full")
    cand_derived = cand["composition"]["derived_guard"]
    full_derived = full["composition"]["derived_guard"]
    assert cand_derived["expr"] is not None          # no-witness relation enters
    assert full_derived["expr"] is None              # full refuses to compose it
    assert full_derived["status"] == "INCOMPLETE"
    assert "O0" in [item["id"] for item in full_derived["unverified_relations"]]


# ---- C5: role/channel edits are real edits --------------------------------

def test_same_relations_detects_role_and_channel_changes():
    from mace.loop import _same_relations
    base = {"target_effects": [], "upstream": [], "observers": [
        {"id": "O0", "expr": "x", "condition": "True", "channel": 0}]}
    moved = json.loads(json.dumps(base))
    moved["observers"][0]["channel"] = 1
    upstream = json.loads(json.dumps(base))
    upstream["upstream"] = [{"id": "U1", "expr": "x", "condition": "True",
                             "role": "supporting"}]
    fp = json.loads(json.dumps(upstream))
    fp["upstream"][0]["role"] = "fixed_point"
    assert _same_relations(base, base)
    assert not _same_relations(base, moved)
    assert not _same_relations(upstream, fp)
