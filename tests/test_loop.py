import json
from pathlib import Path

import pytest

from mace import loop
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


def test_patch_only_revises_named_relation():
    previous = json.loads(json.dumps(REFERENCE))
    patch = {"revise": [{"id": "O0", "condition": "use_left"}],
             "mask_guard": {"id": "G", "expr": "use_left"}}
    merged, notes = loop.apply_patch(previous, patch)
    assert merged["observers"][0]["condition"] == "use_left"
    assert merged["observers"][0]["expr"] == previous["observers"][0]["expr"]
    assert merged["mask_guard"]["expr"] == "use_left"
    assert any("revised O0" in note for note in notes)


def test_patch_ignores_unknown_ids():
    merged, notes = loop.apply_patch(REFERENCE, {"revise": [{"id": "X9", "expr": "True"}]})
    assert merged == REFERENCE
    assert any("unknown id" in note for note in notes)


def test_mace_loop_repairs_with_counterexample(tmp_path):
    broken = json.loads(json.dumps(REFERENCE))
    broken["observers"][0]["condition"] = "True"      # refuted by a real execution
    broken["mask_guard"]["expr"] = "True"             # unsound
    patch = {
        "revise": [{"id": "O0", "condition": "use_left or xs[0] == min(xs)"}],
        "mask_guard": {"id": "G", "expr": REFERENCE["mask_guard"]["expr"]},
    }
    client = FakeClient([json.dumps(broken), json.dumps(patch)])
    fixture = load_fixture("sort_channel.json")
    result = loop.run_mode(fixture, client, "mace", rounds=3, seed=0, out_dir=tmp_path)
    assert result["status"] == "ALL_VERIFIED"
    assert result["rounds_used"] == 2
    assert result["final_report"]["all_relations_pass"] is True
    first, second = result["exchanges"]
    assert first["report"]["all_relations_pass"] is False
    assert any("revised O0" in note for note in second["patch_notes"])


def test_direct_baseline_accepts_verified_guard(tmp_path):
    client = FakeClient([json.dumps({"mask_guard": REFERENCE["mask_guard"]["expr"]})])
    fixture = load_fixture("sort_channel.json")
    result = loop.run_mode(fixture, client, "direct", rounds=2, seed=0, out_dir=tmp_path)
    assert result["status"] == "GUARD_VERIFIED"
    assert result["final_report"]["guard_ok"] is True


def test_patch_with_empty_mask_guard_keeps_previous_guard():
    merged, notes = loop.apply_patch(REFERENCE, {"mask_guard": {}})
    assert merged["mask_guard"]["expr"] == REFERENCE["mask_guard"]["expr"]
    assert any("ignored mask_guard" in note for note in notes)


def test_unchanged_patch_is_called_out(tmp_path):
    broken = json.loads(json.dumps(REFERENCE))
    broken["observers"][0]["condition"] = "True"
    broken["mask_guard"]["expr"] = "True"
    same = {"revise": [{"id": "O0", "condition": "True", "rationale": "already right"}],
            "mask_guard": {"id": "G", "expr": "True"}}
    client = FakeClient([json.dumps(broken), json.dumps(same), json.dumps(same)])
    fixture = load_fixture("sort_channel.json")
    loop.run_mode(fixture, client, "mace", rounds=3, seed=0, out_dir=tmp_path)
    third_request = client.calls[2]["messages"][-1]["content"]
    assert "left every expression and condition unchanged" in third_request


def test_repair_round_still_sees_the_program(tmp_path):
    """Regression: the feedback turn must not replace the original program prompt.

    An earlier version rebuilt the conversation from scratch after every round,
    so the model was asked to repair its contract without the source in context.
    """
    broken = json.loads(json.dumps(REFERENCE))
    broken["mask_guard"]["expr"] = "True"
    patch = {"mask_guard": {"id": "G", "expr": REFERENCE["mask_guard"]["expr"]}}
    client = FakeClient([json.dumps(broken), json.dumps(patch)])
    fixture = load_fixture("sort_channel.json")
    loop.run_mode(fixture, client, "mace", rounds=2, seed=0, out_dir=tmp_path)
    second_request = client.calls[1]["messages"]
    joined = "\n".join(m["content"] for m in second_request)
    assert "# TARGET_A" in joined                      # source is still in context
    assert second_request[0]["role"] == "system"
    assert second_request[-1]["role"] == "user"
    assert any(m["role"] == "assistant" for m in second_request)


def test_invalid_json_gets_feedback_and_retry(tmp_path):
    client = FakeClient(["not json at all",
                         json.dumps({"mask_guard": REFERENCE["mask_guard"]["expr"]})])
    fixture = load_fixture("sort_channel.json")
    result = loop.run_mode(fixture, client, "direct", rounds=2, seed=0, out_dir=tmp_path)
    assert result["status"] == "GUARD_VERIFIED"
    assert client.calls[0]["messages"] is not None


# ---- 2x2 cells -----------------------------------------------------------

def test_derived_guard_replaces_a_wrong_qwen_guard(tmp_path):
    """Cell B on a correct contract: the composer wins even if Qwen's guard is wrong."""
    contract = json.loads(json.dumps(REFERENCE))
    contract["mask_guard"]["expr"] = "True"
    client = FakeClient([json.dumps(contract)])
    fixture = load_fixture("sort_channel.json")
    result = loop.run_mode(fixture, client, "mace", rounds=2, seed=0,
                           out_dir=tmp_path, guard_source="derived")
    report = result["final_report"]
    assert report["guard_ok"] is True
    assert report["qwen_guard"]["status"] == "REFUTED"
    assert result["final_guard"] != "True"
    assert report["composition"]["derived_guard"]["equivalent_to_declared_guard_on_domain"] is True


def test_derived_guard_cannot_rescue_a_wrong_contract(tmp_path):
    """Cell B: with a refuted relation the composed guard is wrong too, and the
    feedback must stay about the relation, not about a guard the model cannot own."""
    broken = json.loads(json.dumps(REFERENCE))
    broken["observers"][0]["condition"] = "True"
    broken["mask_guard"]["expr"] = "True"
    patch = {"revise": [{"id": "O0", "condition": "use_left or xs[0] == min(xs)"}]}
    client = FakeClient([json.dumps(broken), json.dumps(patch)])
    fixture = load_fixture("sort_channel.json")
    result = loop.run_mode(fixture, client, "mace", rounds=2, seed=0,
                           out_dir=tmp_path, guard_source="derived")
    first_report = result["exchanges"][0]["report"]
    assert first_report["guard"]["unsound"] > 0          # composed from a false condition
    feedback = client.calls[1]["messages"][-1]["content"]
    assert "RELATION O0" in feedback
    assert "RELATION G" not in feedback
    assert result["final_report"]["guard_ok"] is True
    assert result["rounds_used"] == 2


def test_oracle_derived_needs_no_model_and_is_exact(tmp_path):
    """Cell D, the ceiling: reviewed contract + composer, zero tokens."""
    client = FakeClient([])
    fixture = load_fixture("sort_channel.json")
    result = loop.run_mode(fixture, client, "oracle", rounds=1, seed=0,
                           out_dir=tmp_path, guard_source="derived",
                           contract_override=REFERENCE)
    assert client.calls == []
    assert result["usage"]["prompt_tokens"] == 0
    assert result["diagnostic_only"] is True
    report = result["final_report"]
    assert report["guard_ok"] is True
    assert report["composition"]["derived_guard"]["equivalent_to_declared_guard_on_domain"] is True


def test_oracle_qwen_sees_the_reviewed_contract(tmp_path):
    """Cell C: reviewed relations in the prompt, model writes only the guard."""
    client = FakeClient([json.dumps({"mask_guard": REFERENCE["mask_guard"]["expr"]})])
    fixture = load_fixture("sort_channel.json")
    result = loop.run_mode(fixture, client, "oracle", rounds=1, seed=0,
                           out_dir=tmp_path, guard_source="qwen",
                           contract_override=REFERENCE)
    assert result["status"] == "GUARD_VERIFIED"
    prompt = client.calls[0]["messages"][-1]["content"]
    assert "human reviewer" in prompt
    assert "use_left or xs[0] == min(xs)" in prompt
