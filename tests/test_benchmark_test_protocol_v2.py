"""Regression tests for the protocol-v2 test-selection split.

The central invariant: T_task selection is a function of source association
and P+ coverage only.  Changing any P- outcome must leave the selected IDs and
selection hash unchanged.
"""
from __future__ import annotations

import copy
import inspect
import json
from pathlib import Path

import pytest

from benchmark_real_pilot.protocol_v2 import config
from benchmark_real_pilot.protocol_v2.runner import cache_key
from benchmark_real_pilot.protocol_v2.selection import (
    SELECTION_BASIS,
    build_selection,
    compute_selection_hash,
    load_selection,
    select_task_tests,
)

ROOT = Path(__file__).resolve().parent.parent
PROTOCOL = ROOT / "benchmark_real_pilot" / "protocol_v2"
SELECTION = PROTOCOL / "task_selection.json"
MANIFEST = PROTOCOL / "task_manifest.json"


def _load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def _synthetic_coverage(selection: dict, minus_marker: str) -> dict:
    """Build a P+ trace identical to the frozen selection, plus fake P- noise."""
    projects = {}
    for task_id, row in selection["tasks"].items():
        project_id = row["project_id"]
        project = projects.setdefault(project_id, {"plus": {"trace": {"hits": {}}}})
        for nodeid in row["original_test_ids"]:
            hit = row["selected_tests"][
                row["original_test_ids"].index(nodeid)
            ]["plus_hit_count"]
            project["plus"]["trace"]["hits"].setdefault(nodeid, {})[
                row["trace_label"]
            ] = hit
    for project in projects.values():
        project["targets"] = {
            "fake": {
                "minus": {
                    "returncode": 0,
                    "trace": {"reports": {minus_marker: {"outcome": "passed"}}},
                }
            }
        }
        project["minus_fake"] = {"result": minus_marker}
    return {"projects": projects}


def test_selection_module_has_no_p_minus_input():
    sig = inspect.signature(select_task_tests)
    assert not any("minus" in name.lower() for name in sig.parameters)
    assert "p_minus_consulted" not in SELECTION_BASIS
    assert "p_minus_coverage" not in SELECTION_BASIS


def test_p_minus_outcomes_cannot_change_selection_ids_or_hash(tmp_path):
    frozen = _load(SELECTION)
    coverage_a = _synthetic_coverage(frozen, "passed")
    coverage_b = _synthetic_coverage(frozen, "failed")
    path_a = tmp_path / "coverage_a.json"
    path_b = tmp_path / "coverage_b.json"
    path_a.write_text(json.dumps(coverage_a), encoding="utf-8")
    path_b.write_text(json.dumps(coverage_b), encoding="utf-8")

    sel_a = build_selection(path_a)
    sel_b = build_selection(path_b)
    for task_id in config.TASKS:
        assert (
            sel_a["tasks"][task_id]["original_test_ids"]
            == sel_b["tasks"][task_id]["original_test_ids"]
        )
        assert (
            sel_a["tasks"][task_id]["selection_hash"]
            == sel_b["tasks"][task_id]["selection_hash"]
        )


def test_frozen_selection_is_self_consistent():
    frozen = load_selection(SELECTION)
    for task_id, row in frozen["tasks"].items():
        assert row["original_test_ids"]
        assert row["original_test_ids"] == sorted(row["original_test_ids"])
        expected = compute_selection_hash(task_id, row["original_test_ids"])
        assert row["selection_hash"] == expected
        for nodeid in row["original_test_ids"]:
            assert nodeid in row["original_test_source"]
            assert row["original_test_source"][nodeid].endswith(".py")


def test_manifest_uses_exact_frozen_ids_and_no_new_tests():
    frozen = load_selection(SELECTION)
    manifest = _load(MANIFEST)
    assert manifest["selection_frozen_before_p_minus"] is True
    for task_id, row in manifest["tasks"].items():
        assert row["selection_hash"] == frozen["tasks"][task_id]["selection_hash"]
        assert row["original_test_ids"] == frozen["tasks"][task_id]["original_test_ids"]
        assert row["p_minus_consulted_for_selection"] is False


def test_manifest_has_required_fields_and_all_tests_hit_a():
    manifest = _load(MANIFEST)
    required = {
        "original_test_ids",
        "original_test_source",
        "target_A_hit",
        "local_effect_observed",
        "p_plus_result",
        "p_minus_result",
        "selection_reason",
        "test_scope",
        "qualification_labels",
    }
    for task_id, row in manifest["tasks"].items():
        assert required <= set(row), task_id
        assert row["original_test_ids"]
        assert row["target_A_hit"]["all_selected_tests_hit"] is True
        assert set(row["target_A_hit"]["per_test_hit_count"]) == set(
            row["original_test_ids"]
        )
        assert row["p_plus_result"]["all_pass"] is True
        assert row["test_scope"]["T_task"]["count"] == len(row["original_test_ids"])


def test_t_task_counts_are_the_frozen_counts():
    manifest = _load(MANIFEST)
    counts = {
        task_id: len(row["original_test_ids"])
        for task_id, row in manifest["tasks"].items()
    }
    assert counts == {
        "real_click_truncate_visible": 1,
        "real_werkzeug_headerset_update": 3,
        "real_werkzeug_url_unparse": 18,
    }


def test_qualification_labels_do_not_overwrite_each_other():
    manifest = _load(MANIFEST)
    for task_id, row in manifest["tasks"].items():
        labels = row["qualification_labels"]
        assert set(labels) == set(config.QUALIFICATION_LABELS)
        assert all(isinstance(value, bool) for value in labels.values())

    click = manifest["tasks"]["real_click_truncate_visible"]["qualification_labels"]
    assert click["TASK_TESTS_SURVIVE"] is True
    assert click["PROJECT_SUITE_SURVIVES"] is True
    assert click["PROJECT_SUITE_DETECTS"] is False

    header = manifest["tasks"]["real_werkzeug_headerset_update"]["qualification_labels"]
    assert header["TASK_TESTS_SURVIVE"] is False
    assert header["PROJECT_SUITE_SURVIVES"] is False
    assert header["PROJECT_SUITE_DETECTS"] is True

    url = manifest["tasks"]["real_werkzeug_url_unparse"]["qualification_labels"]
    assert url["TASK_TESTS_SURVIVE"] is False
    assert url["PROJECT_SUITE_SURVIVES"] is False
    assert url["PROJECT_SUITE_DETECTS"] is True
    assert url["PROJECT_SUITE_NOT_FULLY_RUN"] is True


def test_project_suite_cache_key_binds_all_four_inputs():
    base = dict(
        project_id="p",
        source_tree_hash="source",
        environment={"python_executable": "py", "pytest_version": "7"},
        test_scope={"tests": ["tests"], "extra_args": []},
        variant="p_plus",
    )
    key = cache_key(**base)
    for field, replacement in [
        ("project_id", "p2"),
        ("source_tree_hash", "source2"),
        ("environment", {"python_executable": "py2", "pytest_version": "7"}),
        ("test_scope", {"tests": ["tests/test_x.py"], "extra_args": []}),
        ("variant", "p_minus"),
    ]:
        changed = dict(base)
        changed[field] = replacement
        assert cache_key(**changed) != key, field


def test_werkzeug_scope_never_claims_full_unfiltered_suite():
    manifest = _load(MANIFEST)
    for task_id in (
        "real_werkzeug_headerset_update",
        "real_werkzeug_url_unparse",
    ):
        row = manifest["tasks"][task_id]
        note = row["test_scope"]["full_unfiltered_suite_note"].lower()
        assert "not used" in note or "no claim" in note
        assert row["test_scope"]["T_project"]["extra_args"] == ["-m", "not dev_server"]
        assert row["test_scope"]["T_project"]["deselected_by_protocol"] == 24
