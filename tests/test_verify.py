import json
from pathlib import Path

import pytest

from mace.contracts import parse_bundle
from mace.domain import build_domain, input_sorts
from mace.program import AnalysisError, build_callables, build_pair, run_pair
from mace.terms import signature_table
from mace.verify import verify_bundle

ROOT = Path(__file__).resolve().parent.parent
SOURCE = (ROOT / "fixtures" / "sort_channel.py").read_text(encoding="utf-8")
CONFIG = json.loads((ROOT / "experiments" / "sort_channel.json").read_text(encoding="utf-8"))
REFERENCE = json.loads((ROOT / "experiments" / "hidden" / "sort_channel_reference.json")
                       .read_text(encoding="utf-8"))["bundle"]


@pytest.fixture(scope="module")
def rows_and_pair():
    pair = build_pair(SOURCE)
    domain = build_domain(CONFIG["domain"])
    rows = run_pair(pair, domain.cases)
    return rows, pair, domain


def report_for(rows, pair, bundle_raw):
    return verify_bundle(
        rows, parse_bundle(bundle_raw),
        input_sorts=input_sorts(CONFIG["domain"]),
        functions=signature_table(CONFIG["functions"]),
        callables=build_callables(pair),
        level="BOUNDED", channels=2)


def test_reference_bundle_is_fully_verified(rows_and_pair):
    rows, pair, _ = rows_and_pair
    report = report_for(rows, pair, REFERENCE)
    assert report["all_relations_pass"] is True
    assert report["guard_ok"] is True
    statuses = {r["id"]: r["status"] for r in report["relations"]}
    assert statuses == {"T1": "BOUNDED", "U1": "BOUNDED", "O0": "BOUNDED", "O1": "BOUNDED"}
    assert report["observer_soundness"]["status"] == "BOUNDED"
    assert report["behaviour"] == {"local_inactive": 5956, "active_masked": 2090,
                                   "active_exposed": 2866}


def test_guard_without_upstream_condition_is_incomplete(rows_and_pair):
    rows, pair, _ = rows_and_pair
    bundle = json.loads(json.dumps(REFERENCE))
    bundle["mask_guard"]["expr"] = ("(use_left or xs[0] == min(xs)) and "
                                    "(use_right or xs[-1] == max(xs))")
    report = report_for(rows, pair, bundle)
    assert report["guard"]["incomplete"] > 0
    assert report["guard"]["unsound"] == 0


def test_trivially_true_guard_is_unsound(rows_and_pair):
    rows, pair, _ = rows_and_pair
    bundle = json.loads(json.dumps(REFERENCE))
    bundle["mask_guard"]["expr"] = "True"
    report = report_for(rows, pair, bundle)
    assert report["guard"]["unsound"] > 0


def test_weak_observer_condition_is_refuted_locally(rows_and_pair):
    rows, pair, _ = rows_and_pair
    bundle = json.loads(json.dumps(REFERENCE))
    bundle["observers"][0]["condition"] = "True"
    report = report_for(rows, pair, bundle)
    o0 = next(r for r in report["relations"] if r["id"] == "O0")
    assert o0["status"] == "REFUTED"
    assert o0["invariance_failures"] > 0
    assert o0["counterexamples"][0]["diagnostic"]["A_changed_local_state"] is True


def test_wrong_observer_expression_breaks_faithfulness(rows_and_pair):
    rows, pair, _ = rows_and_pair
    bundle = json.loads(json.dumps(REFERENCE))
    bundle["observers"][1]["expr"] = "xs[0]"
    report = report_for(rows, pair, bundle)
    o1 = next(r for r in report["relations"] if r["id"] == "O1")
    assert o1["status"] == "REFUTED"
    assert o1["faithful_failures"] > 0


def test_unsupported_program_is_rejected_statically():
    bad = "import os\n\ndef program(x):\n    y = 1  # TARGET_A\n    return x\n"
    pair = build_pair(bad)
    assert pair.supported is False
    assert any("import" in p or "Import" in p for p in pair.problems)


def test_target_inside_loop_is_rejected():
    src = ("def program(xs):\n"
           "    total = 0\n"
           "    for x in xs:\n"
           "        total = total + x  # TARGET_A\n"
           "    return total\n")
    pair = build_pair(src)
    assert pair.supported is False
    assert any("loop" in p for p in pair.problems)


def test_target_must_be_assignment():
    src = "def program(xs):\n    xs.sort()  # TARGET_A\n    return xs[0]\n"
    with pytest.raises(AnalysisError):
        build_pair(src)
