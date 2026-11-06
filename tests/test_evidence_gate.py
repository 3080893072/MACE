import json
from pathlib import Path

from mace import evidence_gate as gate
from mace import loop
from mace.contracts import parse_bundle
from mace.fixture import load_fixture
from mace.qwen import Response

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = json.loads((ROOT / "experiments" / "hidden" / "sort_channel_reference.json")
                       .read_text(encoding="utf-8"))["bundle"]


class FakeClient:
    provider = "fake"
    model = "fake-model"

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, messages, purpose="", json_mode=True):
        content = self.responses.pop(0)
        stats = {"prompt_tokens": 100, "completion_tokens": 50, "wall_seconds": 0.01}
        self.calls.append({"purpose": purpose, "messages": messages,
                           "stats": stats, "response": content})
        return Response(content=content, stats=stats)


def _observer(**overrides):
    row = {"id": "O0", "kind": "observer", "channel": 0, "status": "BOUNDED",
           "checked": 10, "faithful_failures": 0, "faithful_minus_failures": 0,
           "invariance_checked": 10, "invariance_failures": 0, "evaluation_errors": 0}
    row.update(overrides)
    return row


def _relation(**overrides):
    row = {"id": "T1", "kind": "target_effect", "status": "BOUNDED",
           "checked": 10, "failures": 0}
    row.update(overrides)
    return row


def test_verified_observer_needs_a_witness():
    assert gate.classify(_observer())["evidence_status"] == gate.WITNESS_VERIFIED


def test_observer_with_no_invariance_witness_is_unverified():
    record = gate.classify(_observer(invariance_checked=0))
    assert record["evidence_status"] == gate.UNVERIFIED
    assert "no domain input" in record["gate_reason"]


def test_zero_checked_relation_is_unverified_not_verified():
    record = gate.classify(_relation(checked=0))
    assert record["evidence_status"] == gate.UNVERIFIED


def test_invalid_relation_is_unverified():
    record = gate.classify(_relation(status="INVALID", checked=0))
    assert record["evidence_status"] == gate.UNVERIFIED


def test_counterexample_is_refuted():
    record = gate.classify(_relation(status="REFUTED", checked=10, failures=2))
    assert record["evidence_status"] == gate.REFUTED


def test_fixed_point_without_implication_witness_is_unverified():
    record = gate.classify(_relation(kind="upstream", role="fixed_point",
                                     fixed_point_checked=0, fixed_point_failures=0))
    assert record["evidence_status"] == gate.UNVERIFIED


def test_fixed_point_with_failed_implication_is_refuted():
    record = gate.classify(_relation(kind="upstream", role="fixed_point",
                                     fixed_point_checked=5, fixed_point_failures=0,
                                     status="REFUTED", failures=0))
    assert record["evidence_status"] == gate.REFUTED


def test_gate_is_off_by_default_in_loop(tmp_path):
    client = FakeClient([json.dumps(REFERENCE)])
    fixture = load_fixture("sort_channel.json")
    result = loop.run_mode(fixture, client, "mace", rounds=1, seed=0, out_dir=tmp_path)
    assert result["evidence_gate"] is False
    assert "evidence_gate" not in (result["final_report"] or {})
    assert result["final_guard"] == REFERENCE["mask_guard"]["expr"]


def test_gated_derived_guard_is_witness_verified(tmp_path):
    client = FakeClient([json.dumps(REFERENCE)])
    fixture = load_fixture("sort_channel.json")
    result = loop.run_mode(fixture, client, "mace", rounds=1, seed=0, out_dir=tmp_path,
                           guard_source="derived", evidence_gate=True)
    assert result["evidence_gate"] is True
    assert result["status"] == "ALL_VERIFIED"
    gate_info = result["final_report"]["evidence_gate"]
    assert gate_info["counts"][gate.WITNESS_VERIFIED] > 0
    assert result["final_guard"] == result["final_report"]["guard"]["expr"]


def test_filtered_composition_drops_unverified_observer():
    fixture = load_fixture("parity_snap.json")
    bundle = parse_bundle(json.loads(
        (ROOT / "experiments" / "hidden" / "parity_snap_reference.json")
        .read_text(encoding="utf-8"))["bundle"])
    report = {"relations": [_observer(id="O0", channel=0, invariance_checked=0)]}
    ungated = gate.compose_ungated(bundle, report, fixture.channels)
    gated = gate.compose_gated(bundle, report, fixture.channels)
    assert ungated["status"] == "COMPOSED"
    assert gated["status"] == "UNKNOWN"
    assert gated["expr"] is None
