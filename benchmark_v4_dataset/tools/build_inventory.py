"""Merge Stage 1/2/3 artefacts into the dataset inventory and statistics.

Outputs::

    results/MACE_v4_candidate_inventory.csv
    results/MACE_v4_project_statistics.json
    results/MACE_v4_stage_statistics.json

Candidate rows are discovery candidates, not tasks.  The statistics keep the
four count axes separate.
"""
from __future__ import annotations

import csv
import json
from collections import Counter, defaultdict
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
DS = KIT / "benchmark_v4_dataset"
DISC = DS / "discovery"
OUT = DS / "results"

SCREEN_STATUS = {
    "TEST_SURVIVING_DELETION",
    "PROJECT_SUITE_DETECTS_DELETION",
    "SCREENED_REJECT_TEST_DETECTS_DELETION",
    "SCREENED_REJECT_DEAD_BEFORE_READ",
    "SCREENED_REJECT_NO_A_EXECUTION",
}


def load(path: Path, default=None):
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def main() -> int:
    stage0 = load(DISC / "stage0" / "projects.json", {"projects": []})
    stage1 = load(DISC / "stage1" / "candidates_static.json",
                  {"candidates": [], "counts_by_project": {}})
    registry = load(DISC / "manifest" / "source_registry.json",
                    {"projects": []})
    reg = {p["slug"]: p for p in registry["projects"]}
    meta = {p["slug"]: p for p in stage0["projects"]}

    screens = {}
    for path in sorted((DISC / "stage2_3").glob("*.screen.json")):
        data = load(path)
        screens[data["slug"]] = data

    row_by_id = {}
    for cand in stage1["candidates"]:
        row_by_id[cand["candidate_id"]] = {
            "candidate_id": cand["candidate_id"],
            "project_id": cand["project_id"],
            "project": cand["project"],
            "version": cand["version"],
            "split": cand["split"],
            "file": cand["file"],
            "function": cand["function"],
            "mechanism": cand["mechanism"],
            "variable": cand["variable"],
            "A_line": cand["target_A"]["line"],
            "A_code": cand["target_A"]["code"],
            "in_loop": cand["static_shape"]["in_loop"],
            "in_if": cand["static_shape"]["in_if"],
            "in_try": cand["static_shape"]["in_try"],
            "read_before_later_write":
                cand["static_shape"]["read_before_later_write"],
            "later_reads_A": cand["static_shape"]["later_write_reads_A"],
            "later_count": cand["later_count"],
            "stage2_hit_tests": "",
            "stage2_hit_test_count": 0,
            "stage2": "NOT_RUN",
            "stage3": "NOT_RUN",
            "status": "STAGE1_ONLY",
            "targeted_returncode": "",
            "full_returncode": "",
        }

    for slug, data in screens.items():
        for cand in data["candidates"]:
            cid = cand["candidate_id"]
            row = row_by_id.get(cid)
            if row is None:
                continue
            row["stage2_hit_tests"] = ";".join(
                cand.get("p_plus_hit_tests", [])[:20])
            row["stage2_hit_test_count"] = cand.get(
                "p_plus_hit_test_count", 0)
            row["stage2"] = cand.get("stage2", "")
            row["stage3"] = cand.get("stage3", "")
            row["status"] = cand.get("status", row["status"])
            row["targeted_returncode"] = (
                (cand.get("targeted_minus") or {}).get("returncode"))
            row["full_returncode"] = (
                (cand.get("full_minus") or {}).get("returncode"))

    OUT.mkdir(parents=True, exist_ok=True)
    fields = list(next(iter(row_by_id.values())).keys())
    with (OUT / "MACE_v4_candidate_inventory.csv").open(
            "w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields)
        writer.writeheader()
        for cid in sorted(row_by_id):
            writer.writerow(row_by_id[cid])

    by_status = Counter(r["status"] for r in row_by_id.values())
    by_mech = Counter(r["mechanism"] for r in row_by_id.values())
    by_stage2 = Counter(r["stage2"] for r in row_by_id.values())

    projects = []
    for slug, m in meta.items():
        rows = [r for r in row_by_id.values() if r["project_id"] == slug]
        sc = screens.get(slug, {})
        projects.append({
            "slug": slug,
            "name": m["name"],
            "version": m["version"],
            "split": m["split"],
            "has_original_tests": m["has_original_tests"],
            "test_file_count": m["test_file_count"],
            "ast_candidates": len(rows),
            "stage2_attempted": slug in screens,
            "stage2_a_executed": sum(
                1 for r in rows if r["stage2"] == "A_EXECUTED_WITH_LOCAL_USE"),
            "stage3_targeted_runs": sum(
                1 for r in rows if r["targeted_returncode"] != ""),
            "p_minus_full_surviving": sum(
                1 for r in rows if r["status"] == "TEST_SURVIVING_DELETION"),
            "screen_counts": sc.get("counts", {}),
            "screen_budget": sc.get("budget", {}),
        })

    accepted = load(DS / "registry" / "accepted.json",
                    {"accepted_count": 0, "tasks": []})
    probes = load(DISC / "stage4" / "probes.json", {})
    probe_verdicts = Counter(v.get("verdict", "UNKNOWN")
                             for v in probes.values())
    stats = {
        "schema": "mace_v4_broad_mining_stats/1",
        "as_of": "2026-11-04",
        "count_axes_note": (
            "projects_scanned / ast_candidates / candidates_with_original_tests "
            "/ p_minus_survivors are discovery counts.  tasks_accepted counts "
            "only AC1-AC12 tasks and is zero in this round."),
        "projects": {
            "scanned_dev": len(meta),
            "with_original_tests": sum(
                1 for m in meta.values() if m["has_original_tests"]),
            "heldout_broad_sealed_not_scanned": 12,
        },
        "candidates": {
            "ast_total": len(row_by_id),
            "by_mechanism": dict(by_mech),
            "by_status": dict(by_status),
            "by_stage2": dict(by_stage2),
            "candidates_with_any_original_test_executing_A": sum(
                1 for r in row_by_id.values()
                if r["stage2_hit_test_count"] > 0),
            "candidates_with_local_use_and_execution": sum(
                1 for r in row_by_id.values()
                if r["stage2"] == "A_EXECUTED_WITH_LOCAL_USE"),
            "p_minus_survivors": by_status.get("TEST_SURVIVING_DELETION", 0),
        },
        "stage4": {
            "probes_recorded": len(probes),
            "verdicts": dict(probe_verdicts),
            "masking_input_confirmed": sum(
                1 for v in probes.values() if v.get("masking_witness")),
            "exposing_input_confirmed": sum(
                1 for v in probes.values() if v.get("exposing_witness")),
            "u_necessity_confirmed": sum(
                1 for v in probes.values() if v.get("u_necessity")),
        },
        "accepted": {
            "tasks_total": accepted.get("accepted_count", 0),
            "by_split": dict(Counter(t["split"] for t in accepted["tasks"])),
            "by_story": dict(Counter(t["story"] for t in accepted["tasks"])),
            "cooperative_masking_confirmed": sum(
                1 for t in accepted["tasks"] if t.get("cooperative")),
            "original_tests_total": sum(
                len(t.get("original_tests", [])) for t in accepted["tasks"]),
            "declared_inputs_total": sum(
                len(t.get("declared_inputs", [])) for t in accepted["tasks"]),
            "operations_total": sum(
                t.get("candidate_universe_size", 0)
                for t in accepted["tasks"]),
            "msms_sets_total": sum(len(t.get("msms", []))
                                   for t in accepted["tasks"]),
            "mmbs_sets_total": sum(len(t.get("mmbs", []))
                                   for t in accepted["tasks"]),
            "multi_element_msms_total": sum(
                1 for t in accepted["tasks"]
                for s in t.get("msms", []) if len(s) > 1),
            "independent_acceptance_passed": sum(
                1 for t in accepted["tasks"]
                if t.get("acceptance_all_pass")),
        },
        "tasks_accepted": accepted.get("accepted_count", 0),
        "cooperative_masking_confirmed": sum(
            1 for t in accepted["tasks"] if t.get("cooperative")),
        "projects": projects,
    }
    (OUT / "MACE_v4_stage_statistics.json").write_text(
        json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    (OUT / "MACE_v4_project_statistics.json").write_text(
        json.dumps({"schema": "mace_v4_project_statistics/1",
                    "as_of": "2026-11-04",
                    "projects": projects,
                    "totals": stats["candidates"]},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "rows": len(row_by_id),
        "by_status": dict(by_status),
        "screened_projects": len(screens),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
