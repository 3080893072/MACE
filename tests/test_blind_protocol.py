"""Integrity checks for the frozen blind task (protocol v1).

These tests audit the artifact boundary, not the quality of any method.  They
must not be read as a benchmark score for MACE.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PUBLIC = ROOT / "benchmark_blind_v1" / "public" / "task_01_parse_header_links.json"
PRIVATE = ROOT / "benchmark_blind_v1" / "private" / "task_01_oracle.json"
FREEZE = ROOT / "benchmark_blind_v1" / "FREEZE.json"
RESULTS = ROOT / "benchmark_blind_v1" / "results"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_freeze_check_passes():
    proc = subprocess.run(
        [sys.executable, str(ROOT / "scripts" / "blind_build.py"), "--check"],
        cwd=ROOT, capture_output=True, text=True)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "FREEZE CHECK OK" in proc.stdout


def test_public_private_separation_and_binding():
    public_text = PUBLIC.read_text(encoding="utf-8")
    public = load(PUBLIC)
    private = load(PRIVATE)
    freeze = load(FREEZE)

    assert sha256_file(PUBLIC) == freeze["public_sha256"]
    assert sha256_file(PRIVATE) == freeze["private_sha256"]
    assert private["bindings"]["public_task_sha256"] == freeze["public_sha256"]

    # The correct Guard, hidden case IDs, labels and per-case observations are
    # private only.
    assert private["guard"]["expression"] not in public_text
    for case in private["eval_cases"]:
        assert f'"{case["case_id"]}"' not in public_text
    for forbidden in ["minimal_masking_sets", "observations_equal",
                      "a_has_local_effect", "intervention_equality"]:
        assert forbidden not in public_text
    assert public["hidden_data_notice"]


def test_public_deletion_reproduces_p_minus():
    from benchmark_pilot import engine
    public = load(PUBLIC)
    source = public["program"]["source"]
    assert engine.target_line(source) == public["program"]["target_A"]["line"]
    assert engine.replace_target_with_pass(source) == public["deletion"]["p_minus_source"]


def test_guard_matches_every_frozen_label():
    from benchmark_pilot import engine
    public = load(PUBLIC)
    private = load(PRIVATE)
    expr = private["guard"]["expression"]
    tree = engine.validate_guard(expr, ["nonempty", "all_special"])
    code = compile(tree, "<test-guard>", "eval")
    for case in private["eval_cases"]:
        value = case["args"]["value"]
        features = {
            "nonempty": len(value) > 0,
            "all_special": all(ch in " '\"" for ch in value),
        }
        predicted = eval(code, {"__builtins__": {}}, features)
        assert predicted == case["observations_equal"], case["case_id"]
    assert private["guard"]["status"] == "BOUNDED"
    assert "PROVEN" not in private["guard"]["status"]


def test_public_probes_are_inputs_only():
    public = load(PUBLIC)
    private = load(PRIVATE)
    probes = public["public_probes"]["probes"]
    labels = private["public_probe_labels"]
    assert [p["probe_id"] for p in probes] == [l["case_id"] for l in labels]
    for probe, label in zip(probes, labels):
        assert probe["value"] == label["args"]["value"]
        assert "minimal_masking_sets" not in probe
    assert "minimal_masking_sets" not in PUBLIC.read_text(encoding="utf-8")


def test_frozen_task_covers_all_three_local_effect_classes():
    private = load(PRIVATE)
    counts = private["counts"]
    assert counts["public_probes_total"] == 4
    assert counts["public_probe_masking_types"]["independent"] == 2
    assert counts["public_probe_masking_types"]["cooperative"] == 1
    assert counts["public_probe_masking_types"]["none"] == 1
    assert counts["masked_local_effect"] >= 1
    assert counts["exposed_local_effect"] >= 1
    assert counts["no_local_effect"] >= 1
    assert counts["masking_sets"]["op_1"] >= 1
    assert counts["masking_sets"]["op_3"] >= 1
    assert counts["masking_sets"]["op_1,op_3"] >= 1
    assert counts["masking_sets"]["op_2"] == 0  # documented decoy

    gaps = private["test_gap_summary"]
    assert gaps["all_original_tests_pass_on_p_plus"]
    assert gaps["all_original_tests_pass_on_p_minus"]
    assert gaps["unexercised"] >= 1
    assert gaps["masked_with_local_effect"] >= 1


def test_method_results_do_not_count_unanalysed_methods():
    summary = load(RESULTS / "comparison_summary.json")
    assert summary["answered_methods"] == 0
    assert summary["analyzed_methods"] == 0
    for row in summary["methods"]:
        assert row["counted_as_analyzed"] is False
        assert row["correctness"] is None
    blob = "\n".join(
        (RESULTS / name).read_text(encoding="utf-8")
        for name in ["task_01_direct_qwen.json", "task_01_full_mace.json",
                     "task_01_pure_symbolic.json", "comparison_summary.json"])
    assert "PROVEN" not in blob
    direct = load(RESULTS / "task_01_direct_qwen.json")
    assert direct["tokens"]["llm_calls"] == 0
    assert direct["status"] == "BLOCKED"
    full = load(RESULTS / "task_01_full_mace.json")
    assert full["front_end"]["problems"]
    symbolic = load(RESULTS / "task_01_pure_symbolic.json")
    assert symbolic["diagnostic_status"] == "UNKNOWN"
    assert symbolic["fixture_interface"]["supported"] is False
