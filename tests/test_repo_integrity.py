"""Repository-level invariants that are cheap enough to run in the unit suite.

These tests do not execute probes or call a model.  They catch packaging
mistakes: a missing frozen config, a dataset directory that lost tasks, or a
path helper that resolves outside the repository.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from mace import paths

ROOT = Path(__file__).resolve().parents[1]
V21 = ROOT / "benchmark_v4_dataset" / "source_derived_v2_1"


def test_paths_resolve_to_repository() -> None:
    assert paths.KIT == ROOT
    assert (paths.KIT / "mace" / "cli.py").is_file()


def test_dataset_has_both_splits() -> None:
    dev = [p for p in (V21 / "tasks").iterdir() if p.is_dir()]
    assert len(dev) == 25
    if not (V21 / "heldout" / "tasks").is_dir():
        pytest.skip("HELDOUT split not shipped in this export")
    heldout = [p for p in (V21 / "heldout" / "tasks").iterdir() if p.is_dir()]
    assert len(heldout) == 25


def test_every_task_has_a_passing_acceptance() -> None:
    missing = []
    bases = [V21]
    if (V21 / "heldout" / "tasks").is_dir():
        bases.append(V21 / "heldout")
    for base in bases:
        for task in sorted((base / "tasks").iterdir()):
            if not task.is_dir():
                continue
            report = base / "acceptance" / f"{task.name}.json"
            if not report.is_file():
                missing.append(str(report))
                continue
            data = json.loads(report.read_text("utf-8"))
            assert data["all_checks_pass"], task.name
    assert not missing


def test_frozen_config_and_results_exist() -> None:
    frozen = json.loads(
        (ROOT / "results" / "MACE_v2_1_frozen_config.json").read_text("utf-8"))
    assert frozen["schema"] == "mace-cd-v2.1-frozen-config/1"
    assert frozen["final_numbers"]["dev_tasks_primary"] == 21
    for rel in (
        "results/MACE_v2_1_dev_final.json",
        "results/dev/MACE_v2_1_dev_per_task.csv",
    ):
        assert (ROOT / rel).is_file(), rel
    # Public exports omit the HELDOUT split unless it is released.
    for rel in (
        "results/MACE_HELDOUT_v2_1_official_scores.json",
        "results/heldout/MACE_HELDOUT_v2_1_per_input_scores.csv",
    ):
        if (ROOT / "benchmark_v4_dataset" / "source_derived_v2_1"
                / "heldout" / "tasks").is_dir():
            assert (ROOT / rel).is_file(), rel
