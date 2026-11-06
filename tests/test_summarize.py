"""The cross-run table must report the round-1 to final change, not just the end."""
import json

from mace import summarize


def _write(tmp_path, report_first, report_final):
    run = tmp_path / "run_x"
    run.mkdir()
    data = {
        "fixture": "sort_channel", "mode": "mace", "model": "qwen2.5-coder:7b",
        "status": "ROUNDS_EXHAUSTED", "rounds_used": 2,
        "final_guard": "G", "final_report": report_final,
        "exchanges": [{"round": 1, "report": report_first}, {"round": 2, "report": report_final}],
        "usage": {"prompt_tokens": 100, "completion_tokens": 10, "wall_seconds": 2.0},
    }
    (run / "mace_seed42.json").write_text(json.dumps(data), encoding="utf-8")
    return run


def test_guard_improvement_is_measured_across_rounds(tmp_path):
    first = {"guard": {"status": "REFUTED", "unsound": 40, "incomplete": 2},
             "relations": [{"kind": "upstream", "status": "REFUTED"}]}
    final = {"guard": {"status": "BOUNDED", "unsound": 0, "incomplete": 0},
             "relations": [{"kind": "upstream", "status": "BOUNDED"}],
             "composition": {"status": "BOUNDED"}}
    rows = summarize.collect([_write(tmp_path, first, final)])
    assert rows[0]["guard_improved"] is True
    assert rows[0]["first_guard_bad_rows"] == 42
    assert rows[0]["final_guard_bad_rows"] == 0
    assert rows[0]["relations"] == {"upstream:BOUNDED": 1}


def test_guard_ok_requires_the_report_flag(tmp_path):
    final = {"guard": {"status": "BOUNDED", "unsound": 0, "incomplete": 0},
             "guard_ok": True, "relations": []}
    rows = summarize.collect([_write(tmp_path, final, final)])
    assert rows[0]["guard_ok"] is True
    assert "| sort_channel |" in summarize.markdown(rows)
