"""Unit tests for the v3 baseline adapters (no model, no hidden data)."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from benchmark_v3_baselines import claims as claim_io
from benchmark_v3_baselines.ast_discovery import discover, target_variables
from benchmark_v3_baselines.config import TASK_IDS, experiment_config
from benchmark_v3_baselines.execution import _minimal_exposed, _minimal_masked
from benchmark_v3_baselines.public_io import load_task, validate_payload

KIT = Path(__file__).resolve().parents[1]


def test_public_task_sources_hash_match():
    for task_id in TASK_IDS:
        loaded = load_task(task_id)
        assert loaded["task"]["task_id"] == task_id
        assert loaded["source_text"]


def test_public_contract_rejects_unknown_field():
    loaded = load_task("werkzeug_get_host_default_empty")
    errors = validate_payload(loaded["task"], {"scheme": "http", "bogus": 1})
    assert any("unknown input field" in item for item in errors)


def test_public_contract_accepts_witness():
    loaded = load_task("werkzeug_get_host_default_empty")
    assert validate_payload(
        loaded["task"],
        {"scheme": "http", "host_header": None,
         "server": ["example.com", 8080]}) == []


def test_target_variables_get_host():
    loaded = load_task("werkzeug_get_host_default_empty")
    names = target_variables(loaded["source_text"],
                             loaded["task"]["target_operation"])
    assert "host" in names


def test_ast_discovery_finds_overwrites():
    loaded = load_task("werkzeug_get_host_default_empty")
    found = discover(loaded["task"], loaded["source_text"])
    lines = {op["first_line"] for op in found["candidate_ops"]}
    assert 85 in lines and 87 in lines
    assert all(op["id"] for op in found["candidate_ops"])


def test_ast_discovery_excludes_target_line():
    loaded = load_task("werkzeug_get_host_default_empty")
    found = discover(loaded["task"], loaded["source_text"])
    target_line = loaded["task"]["target_operation"]["line"]
    assert all(op["first_line"] != target_line for op in found["candidate_ops"])


def test_minimal_masked_definition():
    # Keys are disabled sets.  Keeping {A,B} deletes EMPTY, which masks; the
    # proper non-empty kept subsets {A} and {B} delete {B} and {A}, neither of
    # which masks.  So {A,B} is the minimal sufficient masking set.
    masked = {"EMPTY": True, "A": False, "B": False, "A+B": True}
    assert _minimal_masked(masked, ["A", "B"]) == [["A", "B"]]


def test_minimal_exposed_definition():
    exposed = {"EMPTY": False, "A": False, "B": True, "A+B": True}
    assert _minimal_exposed(exposed, ["A", "B"]) == [["B"]]


def test_claim_serialization_matches_submission_format():
    payload = {"scheme": "http", "host_header": None, "server": None}
    ref = {"file": "src/x.py", "first_line": 10, "last_line": 10, "code": "x = 1"}
    op = dict(ref)
    claim = claim_io.minimal_set("MSMS", payload, [op])
    assert claim["type"] == "MSMS"
    assert claim["operations"] == [{"file": "src/x.py", "line": 10, "code": "x = 1"}]


def test_config_is_deterministic_and_marks_hidden_out_of_scope():
    first = experiment_config()
    second = experiment_config()
    assert first["task_hashes"] == second["task_hashes"]
    assert first["hidden_data_in_scope"] is False
    assert first["model"]["model"] == "qwen2.5-coder:32b"


def test_verifier_accepts_indented_source_range():
    from benchmark_v3_baselines.verifier import _op_from_ref

    loaded = load_task("werkzeug_secure_filename_ascii_filter")
    op = _op_from_ref(
        {"file": loaded["task"]["source_file"], "line": 227, "end_line": 229},
        loaded)
    assert op["id"].endswith(":227-229")
    assert op["kind"] == "block"


def test_verifier_reads_inputs_list():
    from benchmark_v3_baselines.verifier import verify_claim

    loaded = load_task("werkzeug_get_host_default_empty")
    claim = {"type": "MSMS", "inputs": [{"bogus_field": 1}],
             "operations": [{"file": loaded["task"]["source_file"],
                             "line": 85}]}
    # An illegal entry in the list must be rejected, proving the verifier
    # reads `inputs` rather than only `input`.
    result = verify_claim(claim, loaded, executor=None, max_inputs=8)
    assert result["verdict"] == "REFUTED"
    assert "illegal input" in result["reason"]


def test_baseline_package_does_not_import_the_scorer():
    import sys

    import benchmark_v3_baselines.baseline_c  # noqa: F401
    import benchmark_v3_baselines.direct_qwen  # noqa: F401
    import benchmark_v3_baselines.verifier  # noqa: F401

    assert "benchmark_real_v3.scoring.engine" not in sys.modules
    package = KIT / "benchmark_v3_baselines"
    for path in package.glob("*.py"):
        text = path.read_text(encoding="utf-8")
        assert "from benchmark_real_v3.scoring" not in text
        assert "load_reference" not in text
