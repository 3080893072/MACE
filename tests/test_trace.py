"""Difference propagation and level-3 attribution."""
import json
from pathlib import Path

import pytest

from mace import sandbox, trace
from mace.fixture import load_fixture
from mace.loop import verify

ROOT = Path(__file__).resolve().parent.parent


def _trace(case):
    fixture = load_fixture("sort_channel.json")
    out = sandbox.trace_cases(fixture.source, [case], arg_sorts=fixture.arg_sorts,
                              entry=fixture.entry, timeout=120)
    return out["traces"][0]


def test_fixed_point_input_shows_no_difference_at_all():
    item = _trace({"xs": [0, -1], "pre": True, "use_left": False, "use_right": False})
    assert item["diff"]["diff_lines"] == {}
    assert item["out_plus"] == item["out_minus"]


def test_masked_input_keeps_xs_difference_but_loses_it_downstream():
    item = _trace({"xs": [0, -1], "pre": False, "use_left": True, "use_right": True})
    diff = item["diff"]
    assert item["out_plus"] == item["out_minus"]
    assert diff["diff_lines"]["33"] == ["xs"]          # xs still differs after A
    absorbed = {(a["name"], a["computed_at"]) for a in diff["absorbed"]}
    assert ("first", 33) in absorbed                   # line 33 equalises channel 0
    assert ("last", 34) in absorbed                    # line 34 equalises channel 1


def test_partial_masking_is_visible_per_channel():
    """Channel 0 is masked on this input while channel 1 stays exposed."""
    item = _trace({"xs": [0, -1], "pre": False, "use_left": True, "use_right": False})
    diff = item["diff"]
    assert item["out_plus"] != item["out_minus"]
    assert diff["outputs_equal"] is False
    absorbed = {(a["name"], a["computed_at"]) for a in diff["absorbed"]}
    assert ("first", 33) in absorbed
    assert ("last", 34) not in absorbed


def test_diff_marks_control_divergence():
    plus = [{"line": 10, "locals": {"x": 1}}, {"line": 12, "locals": {"x": 2}}]
    minus = [{"line": 10, "locals": {"x": 1}}, {"line": 16, "locals": {"x": 2}}]
    diff = trace.diff_traces(plus, minus, outputs_equal=True)
    assert diff["control_divergence"] is True
    assert diff["lines_only_in_plus"] == [12]
    assert diff["lines_only_in_minus"] == [16]


def test_contrast_attribution_finds_the_branch_arguments():
    fixture = load_fixture("sort_channel.json")
    bundle = json.loads((ROOT / "experiments" / "hidden" / "sort_channel_reference.json")
                        .read_text(encoding="utf-8"))["bundle"]
    report = verify(fixture, bundle)
    contrast = report["attribution"]["contrast"]
    assert set(contrast["causally_relevant"]) == {"xs", "pre", "use_left", "use_right"}
    example = contrast["arguments"]["use_right"]["example"]
    assert example["same_args_except"] == "use_right"
    assert example["masked"]["out_plus"] == example["masked"]["out_minus"]
    assert example["exposed"]["out_plus"] != example["exposed"]["out_minus"]


def test_proof_dag_composes_relations_rather_than_enumerating():
    fixture = load_fixture("sort_channel.json")
    bundle = json.loads((ROOT / "experiments" / "hidden" / "sort_channel_reference.json")
                        .read_text(encoding="utf-8"))["bundle"]
    dag = verify(fixture, bundle)["attribution"]["proof_dag"]
    ops = {(e["from"], e["op"]) for e in dag["edges"]}
    assert ("U1", "or") in ops
    assert ("O0", "and") in ops and ("O1", "and") in ops
    assert dag["unsupported"] == []
