"""Build the source-derived inventory CSV and statistics JSON.

Reads only the per-case task packages (task.json / reference.json /
provenance.json), the acceptance reports and the V4 accepted registry.
"""
from __future__ import annotations

import csv
import json
from collections import Counter
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
DS = KIT / "benchmark_v4_dataset"
SD = DS / "source_derived"
TASKS = SD / "tasks"
RESULTS = DS / "results"
AS_OF = "2026-11-04"


def load(path: Path):
    return json.loads(path.read_text("utf-8"))


def main() -> int:
    RESULTS.mkdir(parents=True, exist_ok=True)
    packages = sorted(p for p in TASKS.iterdir() if p.is_dir())

    rows = []
    failures = []
    for pkg in packages:
        task = load(pkg / "task.json")
        ref = load(pkg / "reference.json")
        prov = load(pkg / "provenance.json")
        acc = load(pkg / "acceptance.json")

        msms_sizes = sorted({len(s) for v in ref["inputs"].values()
                             if v["role"] == "masking" for s in v["msms"]})
        coop = any(len(s) >= 2 for v in ref["inputs"].values()
                   for s in v["msms"])
        alt_paths = sum(1 for v in ref["inputs"].values()
                        if v["role"] == "masking" and len(v["msms"]) >= 2)
        u_nec_all = all(v["u_necessary"] for v in ref["inputs"].values()
                        if v["role"] == "masking")

        row = {
            "case_id": task["task_id"],
            "track": task["track"],
            "mechanism": task["mechanism"],
            "project": task["project"],
            "version": task["version"],
            "split": task["split"],
            "researcher_constructed": task["researcher_constructed"],
            "file": task["target_operation"]["file"],
            "function": task["target_operation"]["function"],
            "A_line": task["target_operation"]["line"],
            "A_code": task["target_operation"]["code"],
            "U_size": len(ref["candidate_universe"]),
            "masking_inputs": sum(1 for v in ref["inputs"].values()
                                  if v["role"] == "masking"),
            "exposing_inputs": sum(1 for v in ref["inputs"].values()
                                   if v["role"] == "exposing"),
            "control_inputs": sum(1 for v in ref["inputs"].values()
                                  if v["role"] == "control"),
            "msms_sizes": "|".join(str(x) for x in msms_sizes),
            "cooperative": coop,
            "alternative_paths": alt_paths,
            "u_necessary_all_masking": u_nec_all,
            "original_tests": "|".join(task["original_tests"]),
            "original_test_passed": prov["original_test_suite"].get("passed"),
            "acceptance_all_checks_pass": acc["all_checks_pass"],
            "failed_checks": "|".join(k for k, v in acc["checks"].items() if not v),
            "source_file_sha256": prov["source_file_sha256"],
            "evidence_dir": f"source_derived/evidence/{task['task_id']}",
        }
        rows.append(row)
        if not acc["all_checks_pass"]:
            failures.append({
                "case_id": task["task_id"],
                "failed_checks": [k for k, v in acc["checks"].items() if not v],
            })

    fields = list(rows[0]) if rows else []
    with (RESULTS / "MACE_source_derived_inventory.csv").open(
            "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    accepted_natural = load(DS / "registry" / "accepted.json")["accepted_count"]

    stats = {
        "schema": "mace_source_derived_statistics/1",
        "as_of": AS_OF,
        "count_axes_note": (
            "Tasks counted per track.  Natural tasks satisfy AC1-AC12 with "
            "unmodified source and tests.  Source-derived tasks are "
            "RESEARCHER_CONSTRUCTED and satisfy the track-C acceptance: "
            "real upstream file, recorded patch, declared U, exact masking "
            "enumerations and an independent acceptance report."),
        "source_derived": {
            "attempted": len(rows),
            "qualified": sum(1 for r in rows
                             if r["acceptance_all_checks_pass"]),
            "failed": len(failures),
            "failures": failures,
            "cooperative_tasks": sum(1 for r in rows if r["cooperative"]),
            "alternative_path_tasks": sum(1 for r in rows
                                          if r["alternative_paths"] >= 1),
            "all_u_necessary": sum(1 for r in rows
                                   if r["u_necessary_all_masking"]),
            "by_mechanism": dict(sorted(Counter(
                r["mechanism"] for r in rows).items())),
            "by_project": dict(sorted(Counter(
                r["project"] for r in rows).items())),
            "by_split": dict(sorted(Counter(r["split"] for r in rows).items())),
            "total_unique_A_statements": len(
                {(r["file"], r["A_line"], r["A_code"]) for r in rows}),
        },
        "natural": {
            "accepted_v4_dev": accepted_natural,
            "v3_frozen_reference": 5,
            "note": ("The five V3 tasks and HIDDEN data are frozen and were "
                     "re-read only; they are not re-counted as V4 tasks."),
        },
        "source_preserving": {
            "attempted_this_round": 0,
            "note": ("No source-preserving (track B) candidate reached the "
                     "acceptance criteria in this round; the designs examined "
                     "either had no legal exposing input or could not "
                     "demonstrate a genuine compensation relation."),
        },
        "totals": {
            "natural_accepted_v4_dev": accepted_natural,
            "source_preserving_accepted": 0,
            "source_derived_qualified": sum(
                1 for r in rows if r["acceptance_all_checks_pass"]),
        },
    }
    (RESULTS / "MACE_source_derived_statistics.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n", "utf-8")

    registry = {
        "schema": "mace_source_derived_accepted/1",
        "as_of": AS_OF,
        "track": "SOURCE_DERIVED_CONTROLLED",
        "researcher_constructed": True,
        "note": ("Track-C tasks are registered separately from "
                 "registry/accepted.json, which counts only natural "
                 "AC1-AC12 tasks.  None of these may be reported as a "
                 "naturally occurring upstream defect."),
        "accepted_count": sum(1 for r in rows if r["acceptance_all_checks_pass"]),
        "tasks": [
            {k: r[k] for k in ("case_id", "project", "version", "split",
                               "mechanism", "file", "A_line", "U_size",
                               "cooperative", "acceptance_all_checks_pass")}
            | {"task_dir": f"source_derived/tasks/{r['case_id']}",
               "evidence_dir": r["evidence_dir"]}
            for r in rows],
    }
    (DS / "registry" / "source_derived_accepted.json").write_text(
        json.dumps(registry, ensure_ascii=False, indent=2) + "\n", "utf-8")
    print(json.dumps(stats["source_derived"], ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
