import json
from pathlib import Path

from mace import diagnose


def _run(tmp_path, name, *, fixture="f", mode="mace", guard_source="qwen",
         guard=None, relations=None, tokens=100):
    run_dir = tmp_path / name
    run_dir.mkdir()
    report = {
        "relations": relations or [],
        "guard": guard or {"status": "BOUNDED", "unsound": 0, "incomplete": 0},
        "composition": {"derived_guard": {"status": "BOUNDED"}},
        "witnesses": [],
    }
    data = {"fixture": fixture, "mode": mode, "model": "m", "status": "OK",
            "guard_source": guard_source, "rounds_used": 1,
            "final_report": report, "exchanges": [{"report": report}],
            "usage": {"prompt_tokens": tokens, "completion_tokens": 10,
                      "wall_seconds": 1.5}}
    (run_dir / f"{mode}_seed0.json").write_text(json.dumps(data), encoding="utf-8")
    return run_dir


def _rel(ident, kind, status, condition="True"):
    return {"id": ident, "kind": kind, "expr": "True", "condition": condition,
            "status": status, "reason": None}


def test_classify_handles_the_appended_scope_note():
    reason = ("unknown variable: xs_post. mask_guard is evaluated on the entry "
              "arguments only; <name>_post exists only inside target_effects")
    assert diagnose.classify_invalid(reason) == "post_reference"
    assert diagnose.classify_invalid("unknown variable: value. upstream relations "
                                     "are evaluated on the entry arguments only") == "local_out_of_scope"
    assert diagnose.classify_invalid("unknown variable: foo") == "unknown_name"
    assert diagnose.classify_invalid("expected bool, got int") == "sort"
    # only the first unknown name is in the error; the expression decides
    assert diagnose.classify_invalid(
        "unknown variable: a", "a == b_post and b == a_post") == "post_reference"


def test_post_reference_is_separated_from_semantic_error(tmp_path):
    a = _run(tmp_path, "a", guard={
        "status": "INVALID", "reason": "unknown variable: xs_post", "expr": "xs_post"})
    b = _run(tmp_path, "b", guard={
        "status": "REFUTED", "unsound": 2, "incomplete": 1, "expr": "pre"})
    rows = diagnose.collect([a, b])
    props = diagnose.proportions(rows)
    assert props["cells"] == 2
    assert props["guard_typecheck_fail"] == 1
    assert props["guard_typecheck_fail_post"] == 1
    assert props["guard_typecheck_fail_other"] == 0
    assert props["semantic_bad_among_typed"] == 1
    assert props["guard_correct_among_typed"] == 0


def test_first_bad_stage_skips_absent_kinds(tmp_path):
    run = _run(tmp_path, "c", relations=[
        _rel("T1", "target_effect", "BOUNDED"),
        _rel("U1", "upstream", "REFUTED"),
        _rel("O0", "observer", "BOUNDED")])
    (row,) = diagnose.collect([run])
    assert row["first_bad"] == "upstream"
    assert row["stages_final"]["target_effect"] == "BOUNDED"
    assert row["stages_final"]["observer"] == "BOUNDED"


def test_all_good_has_no_bad_stage(tmp_path):
    run = _run(tmp_path, "d", relations=[
        _rel("T1", "target_effect", "BOUNDED"),
        _rel("O0", "observer", "BOUNDED")])
    (row,) = diagnose.collect([run])
    assert row["first_bad"] == "none"


def test_vacuous_observer_counts_as_a_failure(tmp_path):
    run = _run(tmp_path, "e", relations=[
        _rel("T1", "target_effect", "BOUNDED"),
        _rel("O0", "observer", "VACUOUS")])
    (row,) = diagnose.collect([run])
    assert row["first_bad"] == "observer"


def test_old_runs_default_to_qwen_guard_source(tmp_path):
    run_dir = tmp_path / "old"
    run_dir.mkdir()
    data = {"fixture": "f", "mode": "mace", "model": "m", "status": "OK",
            "final_report": {"relations": [], "guard": {"status": "BOUNDED"}},
            "exchanges": [], "usage": {}}
    (run_dir / "mace_seed0.json").write_text(json.dumps(data), encoding="utf-8")
    (row,) = diagnose.collect([run_dir])
    assert row["guard_source"] == "qwen"
    assert row["diagnostic_only"] is False
