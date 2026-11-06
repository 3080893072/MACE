import json
from pathlib import Path

from mace import cells

ROOT = Path(__file__).resolve().parent.parent
REFERENCE = json.loads((ROOT / "experiments" / "hidden" / "sort_channel_reference.json")
                       .read_text(encoding="utf-8"))["bundle"]


def _run(tmp_path, name, bundle, *, mode="mace", tokens=1000):
    d = tmp_path / name
    d.mkdir()
    data = {"fixture": "sort_channel", "model": "fake", "mode": mode,
            "final_bundle": bundle, "rounds_used": 1,
            "usage": {"prompt_tokens": tokens, "completion_tokens": 10,
                      "wall_seconds": 2.0}}
    (d / f"{mode}_seed0.json").write_text(json.dumps(data), encoding="utf-8")
    return d


def test_cells_show_a_and_b_for_a_correct_contract(tmp_path):
    (row,) = cells.collect([_run(tmp_path, "a", REFERENCE)])
    assert row["cell"] == "A"
    assert row["guard_qwen"]["exact"] is True
    assert row["guard_derived"]["exact"] is True
    assert row["derived_compose_status"] == "COMPOSED"
    assert row["contract"]["verified"] is True
    assert row["attribution"]["relations_on_reference_lines"] > 0


def test_b_does_not_rescue_a_refuted_relation(tmp_path):
    broken = json.loads(json.dumps(REFERENCE))
    broken["observers"][0]["condition"] = "True"
    broken["mask_guard"]["expr"] = "True"
    (row,) = cells.collect([_run(tmp_path, "b", broken)])
    assert row["guard_qwen"]["exact"] is False
    assert row["contract"]["verified"] is False
    assert row["guard_derived"]["exact"] is False


def test_oracle_run_is_labelled_c(tmp_path):
    (row,) = cells.collect([_run(tmp_path, "c", REFERENCE, mode="oracle")])
    assert row["cell"] == "C"
    assert row["contract_source"] == "reviewed"


def test_guard_only_baseline_still_appears_in_the_table(tmp_path):
    # Baselines store only a checked guard, no contract bundle.  They must use
    # their own mode as the cell label instead of being dropped.
    d = tmp_path / "direct"
    d.mkdir()
    data = {"fixture": "sort_channel", "model": "fake", "mode": "direct",
            "final_report": {"guard": {"status": "BOUNDED", "expr": "True",
                                       "unsound": 0, "incomplete": 0,
                                       "source_lines": []}},
            "usage": {"prompt_tokens": 500, "wall_seconds": 1.0}}
    (d / "direct_seed0.json").write_text(json.dumps(data), encoding="utf-8")
    (row,) = cells.collect([d])
    assert row["cell"] == "direct"
    assert row["contract_source"] == "none"
    assert row["guard_qwen"]["typecheck_ok"] is True
    assert row["guard_derived"]["status"] == "ABSENT"
    assert "direct" in cells.markdown([row])
