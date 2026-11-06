import json
from pathlib import Path

import pytest

from mace import sandbox
from mace.fixture import load_fixture

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = json.loads((ROOT / "experiments" / "hidden" / "sort_channel_reference.json")
                       .read_text(encoding="utf-8"))["bundle"]


def test_sandbox_verifies_reference_bundle():
    fixture = load_fixture("sort_channel.json")
    report = sandbox.analyze(
        fixture.source, fixture.domain.cases, REFERENCE,
        arg_sorts=fixture.arg_sorts, functions=fixture.functions,
        channels=fixture.channels, level="BOUNDED", timeout=120)
    assert report["status"] == "OK"
    assert report["all_relations_pass"] is True
    assert report["domain_size"] == 10912


def test_unsupported_program_returns_unknown_not_a_guess():
    source = ("import os\n\n"
              "def program(x):\n"
              "    y = x + 1  # TARGET_A\n"
              "    return y\n")
    report = sandbox.analyze(
        source, [{"x": 1}], {"target_effects": [], "upstream": [], "observers": [],
                             "mask_guard": {"id": "G", "expr": "True"}},
        arg_sorts={"x": "int"}, channels=1, timeout=30)
    assert report["status"] == "UNKNOWN"
    assert report["problems"]


def test_runaway_program_is_killed_by_timeout():
    source = ("def program(x):\n"
              "    y = x + 1  # TARGET_A\n"
              "    while True:\n"
              "        pass\n"
              "    return y\n")
    with pytest.raises(sandbox.SandboxError, match="killed"):
        sandbox.analyze(
            source, [{"x": 1}], {"target_effects": [], "upstream": [], "observers": [],
                                 "mask_guard": {"id": "G", "expr": "True"}},
            arg_sorts={"x": "int"}, channels=1, timeout=2)


def test_child_does_not_inherit_secret_environment(monkeypatch):
    # The child only receives PATH/TEMP/SYSTEMROOT; a planted secret must not
    # show up in the report even if the program tries to read it.
    monkeypatch.setenv("DASHSCOPE_API_KEY", "super-secret-value")
    source = ("def program(x):\n"
              "    import os  # not reachable, subset rejection happens first\n"
              "    y = x  # TARGET_A\n"
              "    return y\n")
    report = sandbox.analyze(
        source, [{"x": 1}], {"target_effects": [], "upstream": [], "observers": [],
                             "mask_guard": {"id": "G", "expr": "True"}},
        arg_sorts={"x": "int"}, channels=1, timeout=30)
    assert report["status"] == "UNKNOWN"
    assert "super-secret-value" not in json.dumps(report)
