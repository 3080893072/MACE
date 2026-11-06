"""Re-derive budget metrics from the stored traces (no re-execution).

The first full run used a version of ``summarize_input`` that reported a
first-confirmation probe count even when the confirmation index fell beyond
the budget prefix.  The raw traces in ``tasks/<task>/result.json`` are
unaffected; this script recomputes every derived field with the corrected
rule and verifies that nothing except ``first_*_probes`` changed.

Usage::

    python -m scripts.recompute_budget_summary
"""
from __future__ import annotations

import json
from pathlib import Path

from scripts.run_budget_experiment import FRACTIONS, _aggregate, derive

KIT = Path(__file__).resolve().parents[1]
RUN = KIT / "runs" / "v3_graph_budget"


def main() -> int:
    old_path = RUN / "summary.json"
    old = json.loads(old_path.read_text(encoding="utf-8"))
    (RUN / "summary.pre_fix.json").write_text(
        json.dumps(old, ensure_ascii=False, indent=2), encoding="utf-8")
    tasks = list(old["tasks"])
    summary = {"tasks": {}, "totals": {}, "recomputed_from": "tasks/*/result.json"}
    changed = 0
    for task_id in tasks:
        per_task = json.loads(
            (RUN / "tasks" / task_id / "result.json").read_text(
                encoding="utf-8"))
        for panel, block in per_task.items():
            for mode, mode_block in block["modes"].items():
                for row in mode_block["inputs"]:
                    if not row.get("searched"):
                        continue
                    before = json.dumps(row.get("budget"),
                                        sort_keys=True, ensure_ascii=False)
                    row["budget"] = derive(row, FRACTIONS)
                    after = json.dumps(row["budget"], sort_keys=True,
                                       ensure_ascii=False)
                    if before != after:
                        changed += 1
                mode_block["budget_summary"] = [
                    _aggregate(mode_block["inputs"], fraction)
                    for fraction in FRACTIONS]
        summary["tasks"][task_id] = per_task
    for panel in ("U_graph", "U_c"):
        summary["totals"][panel] = {}
        for mode in ("exhaustive", "graph"):
            rows = []
            for fraction in FRACTIONS:
                entries = [entry for task in summary["tasks"].values()
                           if panel in task and mode in task[panel]["modes"]
                           for row in task[panel]["modes"][mode]["inputs"]
                           for entry in row.get("budget", [])
                           if abs(entry["fraction"] - fraction) < 1e-9]
                if not entries:
                    continue
                rows.append({
                    "fraction": fraction,
                    "confirmed_msms": sum(e["confirmed_msms"] for e in entries),
                    "confirmed_mmbs": sum(e["confirmed_mmbs"] for e in entries),
                    "undecided_msms": sum(e["undecided_msms"] for e in entries),
                    "undecided_mmbs": sum(e["undecided_mmbs"] for e in entries),
                    "unknown_msms": sum(e["unknown_msms"] for e in entries),
                    "unknown_mmbs": sum(e["unknown_mmbs"] for e in entries),
                    "probes": sum(e["probes"] for e in entries),
                    "wall_seconds": round(
                        sum(e["wall_seconds"] for e in entries), 3),
                    "complete_inputs": sum(1 for e in entries if e["complete"]),
                    "inputs": len(entries),
                })
            summary["totals"][panel][mode] = rows
    (RUN / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"inputs_with_changed_derived_row": changed,
                      "tasks": tasks}, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
