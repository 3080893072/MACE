"""Execute frozen T_task and assemble protocol-v2 qualification records.

Daily benchmark scoring calls :func:`run_task_scope` with the frozen
selection.  It never runs T_project.  Project qualification is assembled from
a cache keyed by source tree, environment, test scope and P+/P- variants.
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

KIT = Path(__file__).resolve().parents[2]
QUALIFICATION_DIR = KIT / "benchmark_real_pilot" / "qualification"
PLUGIN_DIR = QUALIFICATION_DIR
PROJECTS_ROOT = Path("<local-path>")
WORK_ROOT = Path("<local-path>")
OUT_ROOT = Path("<local-path>")
PROTOCOL_DIR = KIT / "benchmark_real_pilot" / "protocol_v2"
UPSTREAM_RUNS = QUALIFICATION_DIR / "out" / "upstream_runs.json"
QUALIFICATION_JSON = QUALIFICATION_DIR / "out" / "three_task_qualification.json"
RESULTS_JSON = KIT / "benchmark_real_pilot" / "results" / "results.json"
UPDATE_PY = QUALIFICATION_DIR / "run_upstream.py"

# Reuse the isolated-copy helpers, but not its full-suite main().
sys.path.insert(0, str(QUALIFICATION_DIR))
from run_upstream import copy_project, delete_line, package_version, sha256  # noqa: E402
from benchmark_real_pilot.specs import TASKS as SPEC_TASKS  # noqa: E402

COPY_IGNORE = None  # copy_project already applies the project ignore list.


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def source_tree_sha256(root: Path) -> str:
    """Deterministic hash of the package source tree (not tests or caches)."""
    digest = hashlib.sha256()
    for path in sorted((root / "src").rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def environment_fingerprint(task: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "python_executable": task["test_python"],
        "python_version": platform.python_version(),
        "pytest_version": task["test_pytest"],
        "platform": platform.platform(),
        "PYTHONHASHSEED": "0",
    }


def cache_key(
    *,
    project_id: str,
    source_tree_hash: str,
    environment: Dict[str, Any],
    test_scope: Dict[str, Any],
    variant: str,
) -> str:
    payload = {
        "project_id": project_id,
        "source_tree_sha256": source_tree_hash,
        "environment": environment,
        "test_scope": test_scope,
        "variant": variant,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        .encode("utf-8")
    ).hexdigest()


def _run_pytest(
    *,
    project_copy: Path,
    task: Dict[str, Any],
    nodeids: Iterable[str],
    output_name: str,
    extra_args: List[str] | None = None,
    timeout: int = 900,
) -> Dict[str, Any]:
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    trace_path = OUT_ROOT / f"{output_name}.json"
    log_path = OUT_ROOT / f"{output_name}.log"
    if trace_path.exists():
        trace_path.unlink()

    target_path = (project_copy / task["source_file"]).resolve()
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(PLUGIN_DIR), str((project_copy / "src").resolve())]
    )
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env["REALBENCH_TRACE_TARGETS"] = (
        f"{task['trace_label']}|{task['target_upstream_line']}|{target_path}"
    )
    env["REALBENCH_TRACE_OUT"] = str(trace_path.resolve())
    env.pop("PYTEST_ADDOPTS", None)

    command = [
        task["test_python"],
        "-m",
        "pytest",
        *list(nodeids),
        "-q",
        "--disable-warnings",
        *(extra_args or []),
        "-p",
        "pytest_trace_plugin",
    ]
    started = datetime.now(timezone.utc)
    try:
        completed = subprocess.run(
            command,
            cwd=project_copy,
            env=env,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        timed_out = False
        stdout, stderr, returncode = completed.stdout, completed.stderr, completed.returncode
    except subprocess.TimeoutExpired as exc:
        timed_out = True
        stdout = exc.stdout or ""
        stderr = exc.stderr or ""
        returncode = None

    log_path.write_text(
        "$ " + " ".join(command) + "\n\n--- stdout ---\n" + stdout
        + "\n--- stderr ---\n" + stderr,
        encoding="utf-8",
    )
    trace = json.loads(trace_path.read_text(encoding="utf-8")) if trace_path.exists() else None
    reports = (trace or {}).get("reports") or {}
    hits = (trace or {}).get("hits") or {}
    per_test = {}
    for nodeid in nodeids:
        report = reports.get(nodeid)
        per_test[nodeid] = {
            "outcome": report.get("outcome") if report else "not_run",
            "phases": report.get("phases") if report else {},
            "target_hit_count": int((hits.get(nodeid) or {}).get(task["trace_label"], 0)),
        }
    counts = {"passed": 0, "failed": 0, "error": 0, "not_run": 0}
    for row in per_test.values():
        outcome = row["outcome"]
        if outcome in counts:
            counts[outcome] += 1
        else:
            counts["not_run"] += 1
    return {
        "variant": output_name,
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "started_utc": started.isoformat(),
        "duration_seconds": (
            datetime.now(timezone.utc) - started
        ).total_seconds(),
        "stdout_tail": stdout[-4000:],
        "stderr_tail": stderr[-4000:],
        "log": str(log_path),
        "trace_json": str(trace_path),
        "reports_count": len(reports),
        "collection_error": bool(returncode not in (0, 1) and not reports),
        "per_test": per_test,
        "counts": counts,
        "all_pass": (
            not timed_out
            and returncode == 0
            and all(row["outcome"] == "passed" for row in per_test.values())
            and bool(per_test)
        ),
    }


def run_task_scope(
    task: Dict[str, Any],
    selection: Dict[str, Any],
    *,
    refresh: bool = False,
) -> Dict[str, Any]:
    """Run exactly the frozen T_task under P+ and P-, nothing else."""
    source = PROJECTS_ROOT / task["project_id"]
    if not source.exists():
        raise FileNotFoundError(f"missing upstream source tree: {source}")

    WORK_ROOT.mkdir(parents=True, exist_ok=True)
    plus_dir = WORK_ROOT / f"{task['task_id']}_t_task_plus"
    minus_dir = WORK_ROOT / f"{task['task_id']}_t_task_minus"

    if refresh or not plus_dir.exists():
        copy_project(source, plus_dir)
    if refresh or not minus_dir.exists():
        copy_project(source, minus_dir)
        delete_line(
            minus_dir,
            {
                "file": task["source_file"],
                "line": task["target_upstream_line"],
                "expected": task["target_expected"],
            },
        )

    nodeids = list(selection["original_test_ids"])
    plus = _run_pytest(
        project_copy=plus_dir,
        task=task,
        nodeids=nodeids,
        output_name=f"{task['task_id']}_t_task_plus",
    )
    minus = _run_pytest(
        project_copy=minus_dir,
        task=task,
        nodeids=nodeids,
        output_name=f"{task['task_id']}_t_task_minus",
    )

    target_hits = {
        nodeid: plus["per_test"][nodeid]["target_hit_count"] for nodeid in nodeids
    }
    return {
        "task_id": task["task_id"],
        "selection_hash": selection["selection_hash"],
        "original_test_ids": nodeids,
        "original_test_source": selection["original_test_source"],
        "target_A_hit": {
            "all_selected_tests_hit": all(count > 0 for count in target_hits.values()),
            "per_test_hit_count": target_hits,
            "trace_variant": "p_plus",
        },
        "p_plus": plus,
        "p_minus": minus,
        "task_tests_survive": minus["all_pass"],
        "task_tests_detect": not minus["all_pass"],
    }


def _load_upstream() -> Dict[str, Any]:
    return json.loads(UPSTREAM_RUNS.read_text(encoding="utf-8"))


def _project_run(upstream: Dict[str, Any], project_id: str, key: str) -> Dict[str, Any]:
    project = upstream["projects"][project_id]
    # Cache keys are tagged with the project id so an entry cannot be reused
    # for another source version.  Strip that tag before indexing the
    # upstream evidence file.
    tag = f"{project_id}:"
    if key.startswith(tag):
        key = key[len(tag):]
    if key == "plus":
        return project["plus"]
    if not key.startswith("minus_"):
        raise KeyError(f"unrecognised project-suite cache key: {key}")
    return project["targets"][key[len("minus_"):]]["minus"]


def _suite_summary(run: Dict[str, Any], variant: str) -> Dict[str, Any]:
    reports = (run.get("trace") or {}).get("reports") or {}
    tail = (run.get("stdout_tail") or "").strip().splitlines()
    counts = {"passed": 0, "failed": 0, "error": 0}
    for report in reports.values():
        outcome = report.get("outcome")
        if outcome in counts:
            counts[outcome] += 1
    complete = bool(reports) and not run.get("timed_out")
    return {
        "variant": variant,
        "command": run.get("command"),
        "returncode": run.get("returncode"),
        "timed_out": run.get("timed_out"),
        "duration_seconds": run.get("duration_seconds"),
        "result_line": tail[-1] if tail else None,
        "reports_count": len(reports),
        "counts": counts,
        "complete": complete,
        "collection_aborted": bool(not reports and run.get("returncode") not in (0, None)),
        "log": run.get("trace_json", "").replace(".json", ".log"),
        "stdout_tail": run.get("stdout_tail"),
        "stderr_tail": run.get("stderr_tail"),
    }


def project_suite_record(
    task: Dict[str, Any],
    source_tree_hash: str,
) -> Dict[str, Any]:
    """Load the cached applicable suite; do not run it during daily scoring."""
    upstream = _load_upstream()
    project = task["project_suite"]
    plus_raw = _project_run(upstream, task["project_id"], project["cached_plus_key"])
    minus_raw = _project_run(upstream, task["project_id"], project["cached_minus_key"])
    plus = _suite_summary(plus_raw, "p_plus")
    minus = _suite_summary(minus_raw, "p_minus")

    env = environment_fingerprint(task)
    scope = {
        "label": project["label"],
        "tests": project["tests"],
        "extra_args": project["extra_args"],
        "filter_note": project["filter_note"],
        "deselected_by_project": project["deselected_by_project"],
        "deselected_by_protocol": project["deselected_by_protocol"],
    }
    plus_key = cache_key(
        project_id=task["project_id"],
        source_tree_hash=source_tree_hash,
        environment=env,
        test_scope=scope,
        variant="p_plus",
    )
    minus_key = cache_key(
        project_id=task["project_id"],
        source_tree_hash=source_tree_hash,
        environment=env,
        test_scope=scope,
        variant=(
            f"p_minus:{task['source_file']}:{task['target_upstream_line']}:"
            f"{task['target_expected']}"
        ),
    )

    survives = bool(minus["complete"] and minus["returncode"] == 0
                    and minus["counts"]["failed"] == 0
                    and minus["counts"]["error"] == 0)
    detects = bool(
        minus["returncode"] != 0
        or minus["collection_aborted"]
        or minus["counts"]["failed"] > 0
        or minus["counts"]["error"] > 0
    )
    return {
        "scope": scope,
        "source_tree_sha256": source_tree_hash,
        "environment": env,
        "cache": {
            "p_plus_key": plus_key,
            "p_minus_key": minus_key,
            "reused_existing_evidence": str(UPSTREAM_RUNS),
            "fully_executed": {
                "p_plus": plus["complete"],
                "p_minus": minus["complete"],
            },
        },
        "p_plus": plus,
        "p_minus": minus,
        "full_unfiltered_suite_note": project["full_unfiltered_suite_note"],
        "project_suite_survives": survives,
        "project_suite_detects": detects,
        "project_suite_not_fully_run": not (plus["complete"] and minus["complete"]),
        "environment_blocked": False,
    }


def local_effect_record(task_id: str) -> Dict[str, Any]:
    data = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    for row in data["tasks"]:
        if row["task_id"] == task_id:
            value = bool(row["checks"]["target_has_local_effect"])
            return {
                "observed": value,
                "evidence": str(RESULTS_JSON),
                "evidence_field": "checks.target_has_local_effect",
                "note": (
                    "Binding-level local effect.  It does not by itself assert "
                    "a defined-to-defined value-change exposure."
                ),
            }
    raise KeyError(f"no local-effect record for {task_id}")


def build_task_manifest(
    task: Dict[str, Any],
    selection: Dict[str, Any],
    task_run: Dict[str, Any],
    source_tree_hash: str,
) -> Dict[str, Any]:
    project = project_suite_record(task, source_tree_hash)
    local_effect = local_effect_record(task["task_id"])
    labels = {
        "TASK_TESTS_SURVIVE": bool(task_run["task_tests_survive"]),
        "PROJECT_SUITE_SURVIVES": bool(project["project_suite_survives"]),
        "PROJECT_SUITE_DETECTS": bool(project["project_suite_detects"]),
        "PROJECT_SUITE_NOT_FULLY_RUN": bool(project["project_suite_not_fully_run"]),
        "ENVIRONMENT_BLOCKED": bool(project["environment_blocked"]),
    }
    return {
        "task_id": task["task_id"],
        "project": task["project"],
        "version": task["version"],
        "source_file": task["source_file"],
        "source_symbol": task["source_symbol"],
        "target_A": {
            "upstream_line": task["target_upstream_line"],
            "code": task["target_expected"],
        },
        "selection_hash": selection["selection_hash"],
        "selection_basis": [
            "source_association",
            "original_test_structure",
            "p_plus_coverage",
        ],
        "p_minus_consulted_for_selection": False,
        "original_test_ids": task_run["original_test_ids"],
        "original_test_source": task_run["original_test_source"],
        "target_A_hit": task_run["target_A_hit"],
        "local_effect_observed": local_effect,
        "p_plus_result": {
            "counts": task_run["p_plus"]["counts"],
            "all_pass": task_run["p_plus"]["all_pass"],
            "result_line": (
                task_run["p_plus"]["stdout_tail"].strip().splitlines()[-1]
                if task_run["p_plus"]["stdout_tail"].strip() else None
            ),
            "duration_seconds": task_run["p_plus"]["duration_seconds"],
            "log": task_run["p_plus"]["log"],
        },
        "p_minus_result": {
            "counts": task_run["p_minus"]["counts"],
            "all_pass": task_run["p_minus"]["all_pass"],
            "result_line": (
                task_run["p_minus"]["stdout_tail"].strip().splitlines()[-1]
                if task_run["p_minus"]["stdout_tail"].strip() else None
            ),
            "duration_seconds": task_run["p_minus"]["duration_seconds"],
            "failures": {
                nodeid: row
                for nodeid, row in task_run["p_minus"]["per_test"].items()
                if row["outcome"] != "passed"
            },
            "log": task_run["p_minus"]["log"],
        },
        "selection_reason": selection["selection_reason"],
        "test_scope": {
            "T_task": {
                "count": len(task_run["original_test_ids"]),
                "tests": task_run["original_test_ids"],
                "note": selection["test_scope_note"],
            },
            "T_project": project["scope"],
            "T_project_result": {
                "p_plus": project["p_plus"],
                "p_minus": project["p_minus"],
            },
            "full_unfiltered_suite_note": project["full_unfiltered_suite_note"],
        },
        "qualification_labels": labels,
        "hidden_validation": hidden_validation_policy(
            task["task_id"], task_run["original_test_ids"]
        ),
        "project_suite_cache": {
            **project["cache"],
            "source_tree_sha256": project["source_tree_sha256"],
            "environment": project["environment"],
            "test_scope": project["scope"],
        },
        "evidence_limits": _evidence_limits(task, labels),
    }


def _evidence_limits(task: Dict[str, Any], labels: Dict[str, bool]) -> List[str]:
    limits = [
        "T_task is a finite original-test set, not a proof of all possible "
        "project behavior.",
    ]
    if labels["TASK_TESTS_SURVIVE"] and not labels["PROJECT_SUITE_SURVIVES"]:
        limits.append(
            "The frozen T_task passes under P- but the applicable project "
            "suite does not; do not generalize T_task survival to the project."
        )
    if not labels["PROJECT_SUITE_SURVIVES"]:
        limits.append(
            "Project-suite survival is not established.  This task cannot be "
            "used to claim that existing project tests miss the deletion."
        )
    if labels["PROJECT_SUITE_NOT_FULLY_RUN"]:
        limits.append(
            "At least one declared suite variant did not execute completely; "
            "the non-execution reason is recorded, and the conclusion is not "
            "reported as a complete-suite pass."
        )
    if labels["ENVIRONMENT_BLOCKED"]:
        limits.append(
            "The declared qualification is environment-blocked and must not "
            "be read as a task failure or pass."
        )
    if task["project"] == "Werkzeug":
        limits.append(
            "The declared T_project excludes dev_server tests.  No claim is "
            "made about the whole unfiltered Werkzeug suite."
        )
    return limits


def load_existing_task_run(task_id: str) -> Dict[str, Any] | None:
    path = PROTOCOL_DIR / "task_runs" / f"{task_id}.json"
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_task_run(task_id: str, run: Dict[str, Any]) -> Path:
    path = PROTOCOL_DIR / "task_runs" / f"{task_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(run, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return path


def hidden_validation_policy(task_id: str, original_test_ids: List[str]) -> Dict[str, Any]:
    """Describe hidden inputs without copying B/C/D/E positions into T_task.

    The hidden case IDs and their roles already live in ``specs.py`` and the
    verifier evidence.  They are scorer/human-only and are never placed in the
    public task prompt or in T_task.
    """
    cases = SPEC_TASKS[task_id]["cases"]
    masking = [
        c["id"] for c in cases
        if c["id"].startswith("mask_") or c["role"] == "mask_witness"
    ]
    exposing = [
        c["id"] for c in cases
        if c["id"].startswith("expose_") or c["role"] == "expose_witness"
    ]
    boundary = [
        c["id"] for c in cases
        if c["id"] not in masking and c["id"] not in exposing
    ]
    return {
        "visibility": "scorer_and_human_only",
        "not_in_public_task_prompt": True,
        "not_in_T_task": True,
        "case_ids_are_not_test_ids": True,
        "T_task_overlap": sorted(set(boundary + masking + exposing) & set(original_test_ids)),
        "masking_inputs": masking,
        "deletion_risk_exposing_inputs": exposing,
        "legal_boundary_and_ordinary_inputs": boundary,
        "operation_intervention_combinations": {
            "base": True,
            "verified_operation_subset_checks": True,
            "evidence": "benchmark_real_pilot/qualification/out/verifier_v2_real_tasks.json",
        },
        "relation_types_present_in_this_real_task": ["independent"],
        "relation_types_not_claimed_for_this_task": ["cooperative", "coexisting"],
        "cooperative_coexisting_coverage": (
            "Existing controlled fixtures ctrl_02/ctrl_03 only.  They are "
            "relation-checker validation, not new real tasks and not evidence "
            "for this task."
        ),
        "operation_labels_location": (
            "Scorer-only verifier/specs evidence; no B/C/D/E label is included "
            "in T_task, the public prompt, or a model-visible answer file."
        ),
    }


def build_all_manifests(
    tasks: Dict[str, Dict[str, Any]],
    selection: Dict[str, Any],
    *,
    refresh_tasks: bool = False,
) -> Dict[str, Any]:
    task_manifests = {}
    for task_id, task in tasks.items():
        frozen = selection["tasks"][task_id]
        run = None if refresh_tasks else load_existing_task_run(task_id)
        if run is None or run.get("selection_hash") != frozen["selection_hash"]:
            run = run_task_scope(task, frozen, refresh=refresh_tasks)
            write_task_run(task_id, run)
        tree_hash = source_tree_sha256(PROJECTS_ROOT / task["project_id"])
        task_manifests[task_id] = build_task_manifest(
            task, frozen, run, tree_hash
        )
    cache_entries = {}
    for task_id, row in task_manifests.items():
        cache = row["project_suite_cache"]
        project_result = row["test_scope"]["T_project_result"]
        for key, variant, result in (
            (cache["p_plus_key"], "p_plus", project_result["p_plus"]),
            (cache["p_minus_key"], "p_minus", project_result["p_minus"]),
        ):
            cache_entries[key] = {
                "task_id": task_id,
                "project_id": row["project"] + " " + row["version"],
                "source_tree_sha256": cache["source_tree_sha256"],
                "environment": cache["environment"],
                "test_scope": cache["test_scope"],
                "variant": variant,
                "result": result,
                "fully_executed": result["complete"],
            }
    return {
        "protocol_version": "2",
        "generated_utc": _now(),
        "selection_file": str(PROTOCOL_DIR / "task_selection.json"),
        "selection_frozen_before_p_minus": True,
        "tasks": task_manifests,
        "hidden_validation_scope": {
            "real_tasks_independent_only": [
                tid for tid, row in task_manifests.items()
                if row["hidden_validation"][
                    "relation_types_present_in_this_real_task"
                ] == ["independent"]
            ],
            "real_tasks_cooperative": [
                tid for tid, row in task_manifests.items()
                if "cooperative" in row["hidden_validation"][
                    "relation_types_present_in_this_real_task"
                ]
            ],
            "real_tasks_coexisting": [
                tid for tid, row in task_manifests.items()
                if "coexisting" in row["hidden_validation"][
                    "relation_types_present_in_this_real_task"
                ]
            ],
            "relation_checker_fixtures": {
                "cooperative": ["ctrl_02"],
                "coexisting": ["ctrl_03"],
            },
            "new_tasks_created": False,
            "note": (
                "The three real tasks have only an independently verified "
                "relation.  Cooperative/coexisting coverage comes from the "
                "pre-existing controlled fixtures and is not presented as "
                "evidence about a real task."
            ),
        },
        "project_suite_cache_entries": cache_entries,
        "summary": {
            "task_count": len(task_manifests),
            "t_task_counts": {
                tid: len(row["original_test_ids"])
                for tid, row in task_manifests.items()
            },
            "labels": {
                tid: row["qualification_labels"]
                for tid, row in task_manifests.items()
            },
        },
    }
