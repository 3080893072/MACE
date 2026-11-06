"""Merge per-task budget results into one summary (no re-execution).

The first full run aborted on a console encoding error while printing a
non-ASCII input for ``werkzeug_secure_filename_ascii_filter``; the four
finished tasks had already written ``tasks/<task>/result.json``.  The secure
task was then run alone into ``runs/v3_graph_budget_secure``.  This script
copies that result into the main run tree and rebuilds ``summary.json`` from
the stored traces with the corrected first-confirmation rule.

Usage::

    python -m scripts.merge_budget_results
"""
from __future__ import annotations

import hashlib
import json
import shutil
from pathlib import Path

from scripts.run_budget_experiment import FRACTIONS, _aggregate, derive

KIT = Path(__file__).resolve().parents[1]
RUN = KIT / "runs" / "v3_graph_budget"
SECURE_RUN = KIT / "runs" / "v3_graph_budget_secure"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


SECURE = SECURE_RUN / "tasks" / \
    "werkzeug_secure_filename_ascii_filter" / "result.json"
TASK_ORDER = [
    "jinja2_bytecode_cache_read",
    "werkzeug_bind_server_name_lower",
    "werkzeug_filestorage_stream_name",
    "werkzeug_get_host_default_empty",
    "werkzeug_secure_filename_ascii_filter",
]


def main() -> int:
    target = RUN / "tasks" / "werkzeug_secure_filename_ascii_filter"
    if SECURE.exists():
        target.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(SECURE, target / "result.json")
    summary = {"tasks": {}, "totals": {}}
    for task_id in TASK_ORDER:
        path = RUN / "tasks" / task_id / "result.json"
        if not path.exists():
            raise SystemExit(f"missing {path}")
        per_task = json.loads(path.read_text(encoding="utf-8"))
        for panel, block in per_task.items():
            for mode, mode_block in block["modes"].items():
                for row in mode_block["inputs"]:
                    if row.get("searched"):
                        row["budget"] = derive(row, FRACTIONS)
                mode_block["budget_summary"] = [
                    _aggregate(mode_block["inputs"], fraction)
                    for fraction in FRACTIONS]
        summary["tasks"][task_id] = per_task
    for panel in ("U_graph", "U_c"):
        summary["totals"][panel] = {}
        for mode in ("exhaustive", "graph"):
            rows = []
            for fraction in FRACTIONS:
                entries = [entry
                           for task in summary["tasks"].values()
                           if panel in task and mode in task[panel]["modes"]
                           for row in task[panel]["modes"][mode]["inputs"]
                           for entry in row.get("budget", [])
                           if abs(entry["fraction"] - fraction) < 1e-9]
                if not entries:
                    continue
                first_ms = [e["first_msms_probes"] for e in entries
                            if e["first_msms_probes"] is not None]
                first_mm = [e["first_mmbs_probes"] for e in entries
                            if e["first_mmbs_probes"] is not None]
                rows.append({
                    "fraction": fraction,
                    "first_msms_probes_mean": (
                        round(sum(first_ms) / len(first_ms), 2)
                        if first_ms else None),
                    "first_mmbs_probes_mean": (
                        round(sum(first_mm) / len(first_mm), 2)
                        if first_mm else None),
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
    main_config = json.loads((RUN / "config.json").read_text(encoding="utf-8"))
    secure_config = json.loads(
        (SECURE_RUN / "config.json").read_text(encoding="utf-8"))
    summary["provenance"] = {
        "merged_from": [f"tasks/{task}/result.json" for task in TASK_ORDER],
        "secure_run_root": "runs/v3_graph_budget_secure",
        "first_run_abort": (
            "UnicodeEncodeError on a GBK console while printing an input; "
            "no probe or search result was affected, and the per-task result "
            "files above were written before the abort."),
        "derivation_fix": (
            "A first-confirmation probe count is reported only when the "
            "confirmation index lies inside the budget prefix."),
        "code_sha256_recorded": {
            "main_run_config": main_config["code_sha256"],
            "secure_rerun_config": secure_config["code_sha256"],
            "delta": (
                "scripts/run_budget_experiment.py differs between the main "
                "run and the secure rerun only by the stdout/stderr "
                "reconfigure guard added after the abort; the three search "
                "modules are byte-identical."),
            "merge_script_sha256": sha256_file(Path(__file__)),
        },
    }
    (RUN / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"tasks": TASK_ORDER, "totals": summary["totals"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
