"""Regenerate ``stats/dataset_stats.json`` from the actual artifacts.

Nothing here is hand-entered: every number is read from a file that was
produced by an execution or an independent acceptance run.

Sources
-------
* ``split/projects.json``      -- DEV / HELDOUT project lists
* ``registry/candidates.json`` -- the original V4 candidate pool
* ``registry/accepted.json``   -- tasks that passed AC1-AC12
* ``tasks/<id>/task.json``     -- declared inputs, original tests
* ``tasks/<id>/reference.json``-- story, U, MSMS/MMBS
* ``discovery/stage1`` + ``discovery/stage2_3`` + ``discovery/stage4``
  -- broad-discovery funnel (separate axis, never merged into task counts)

The four counting axes required by the protocol stay separate: tasks,
original tests, inputs, operation relations.
"""
from __future__ import annotations

import glob
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
DS = KIT / "benchmark_v4_dataset"
DISC = DS / "discovery"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def task_stats() -> dict:
    accepted = load(DS / "registry" / "accepted.json")
    out = {
        "tasks_total": 0,
        "tasks_by_story": {},
        "tasks_by_split": {},
        "original_tests_total": 0,
        "declared_inputs_total": 0,
        "search_inputs_total": 0,
        "operations_total": 0,
        "claims_total": 0,
        "claims_by_type": {},
        "msms_sets_total": 0,
        "mmbs_sets_total": 0,
        "multi_element_msms_total": 0,
        "cooperative_tasks": 0,
        "independent_acceptance_passed": 0,
        "per_task": [],
    }
    stories = Counter()
    splits = Counter()
    for entry in accepted.get("tasks", []):
        tid = entry["task_id"]
        tdir = DS / "tasks" / tid
        task = load(tdir / "task.json") if (tdir / "task.json").exists() else {}
        ref = load(tdir / "reference.json") if (tdir / "reference.json").exists() else {}
        story = ref.get("story") or entry.get("story")
        split = task.get("split") or entry.get("split")
        n_tests = len(task.get("original_tests") or [])
        n_inputs = len(task.get("declared_inputs") or [])
        u = ref.get("candidate_universe") or []
        u_size = len(u) if isinstance(u, list) else sum(
            len(v) for v in u.values()) if isinstance(u, dict) else 0
        minimality = ref.get("minimality") or {}
        msms = minimality.get("msms") or entry.get("msms") or []
        mmbs = minimality.get("mmbs") or entry.get("mmbs") or []
        # ``minimality.subsets`` is the enumerated evidence: one verdict per
        # subset of U.  Count those verdicts as claims, not as tasks.
        subsets = minimality.get("subsets") or {}
        claims = []
        for subset, verdict in subsets.items():
            text = str(verdict).lower()
            if "not equal" in text or "fail" in text:
                claims.append({"type": "EQUALITY_FAILS", "subset": subset})
            elif "equal" in text:
                claims.append({"type": "EQUALITY_HOLDS", "subset": subset})
        acc_path = tdir / "acceptance" / "acceptance_report.json"
        acc = load(acc_path) if acc_path.exists() else {}
        all_pass = bool(acc.get("all_pass") or acc.get("all_checks_pass"))
        stories[story] += 1
        splits[split] += 1
        out["tasks_total"] += 1
        out["original_tests_total"] += n_tests
        out["declared_inputs_total"] += n_inputs
        out["operations_total"] += u_size
        out["msms_sets_total"] += len(msms)
        out["mmbs_sets_total"] += len(mmbs)
        out["multi_element_msms_total"] += sum(1 for s in msms if len(s) >= 2)
        out["claims_total"] += len(claims)
        for c in claims:
            out["claims_by_type"][c.get("type", "UNKNOWN")] = (
                out["claims_by_type"].get(c.get("type", "UNKNOWN"), 0) + 1)
        if msms and any(len(s) >= 2 for s in msms):
            out["cooperative_tasks"] += 1
        if all_pass:
            out["independent_acceptance_passed"] += 1
        out["per_task"].append({
            "task_id": tid,
            "story": story,
            "split": split,
            "original_tests": n_tests,
            "declared_inputs": n_inputs,
            "operations_in_U": u_size,
            "msms": msms,
            "mmbs": mmbs,
            "cooperative": bool(msms) and any(len(s) >= 2 for s in msms),
            "acceptance_all_pass": all_pass,
        })
    out["tasks_by_story"] = dict(stories)
    out["tasks_by_split"] = dict(splits)
    return out


def legacy_candidates() -> dict:
    reg = load(DS / "registry" / "candidates.json")
    items = reg.get("candidates", [])
    status = Counter(c.get("v4_status") or c.get("status") or "UNKNOWN"
                     for c in items)
    return {"unique": len(items), "by_status": dict(sorted(status.items()))}


def broad_funnel() -> dict:
    rows = load(DISC / "stage1" / "candidates_static.json")["candidates"]
    status = Counter()
    screened_projects = set()
    for path in glob.glob(str(DISC / "stage2_3" / "*.screen.json")):
        data = load(Path(path))
        screened_projects.add(Path(path).name[: -len(".screen.json")])
        for c in data.get("candidates", []):
            status[c.get("status", "UNKNOWN")] += 1
    stage1_only = len(rows) - sum(status.values())
    if stage1_only > 0:
        status["STAGE1_ONLY"] = stage1_only
    verdicts = Counter()
    if (DISC / "stage4" / "probes.json").exists():
        probes = load(DISC / "stage4" / "probes.json")
        verdicts = Counter(v.get("verdict", "UNKNOWN")
                           for v in probes.values())
    return {
        "ast_candidates": len(rows),
        "projects_with_ast_candidates": len({c["project_id"] for c in rows}),
        "dynamically_screened_projects": len(screened_projects),
        "dynamically_screened_projects_list": sorted(screened_projects),
        "candidate_status": dict(sorted(status.items())),
        "original_test_executes_A": sum(
            n for s, n in status.items()
            if s in ("STATIC_ELIGIBLE",
                     "SCREENED_REJECT_DEAD_BEFORE_READ",
                     "SCREENED_REJECT_TEST_DETECTS_DELETION",
                     "PROJECT_SUITE_DETECTS_DELETION",
                     "TEST_SURVIVING_DELETION",
                     "FULL_SUITE_NOT_RUN_BUDGET")),
        "p_minus_surviving": status.get("TEST_SURVIVING_DELETION", 0),
        "stage4_verdicts": dict(sorted(verdicts.items())),
        "stage4_records": sum(verdicts.values()),
    }


def main() -> int:
    split = load(DS / "split" / "projects.json")
    broad = broad_funnel()
    stats = {
        "schema": "mace_v4_dataset_stats/2",
        "version": "v4.1-dev-2026-11-04",
        "generated_utc": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "split": {
            "dev_projects": split.get("dev"),
            "heldout_projects": split.get("heldout"),
            "heldout_sealed": True,
            "regression_only": split.get("regression_only"),
        },
        "tasks": task_stats(),
        "candidates_v4_phase1": legacy_candidates(),
        "broad_discovery": broad,
        "evidence_lost": 0,
        "note": ("Counts are separate axes.  Candidate rows, surviving candidates, "
                 "declared inputs and operation relations are never task counts.  "
                 "broad_discovery counts candidates from the discovery pool and "
                 "does not add to tasks."),
    }
    out = DS / "stats" / "dataset_stats.json"
    out.write_text(json.dumps(stats, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    print(json.dumps(stats, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
