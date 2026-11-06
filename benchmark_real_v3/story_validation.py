"""Connect original T_task tests to operation-level masking evidence.

For every frozen task this builds P+, P- and P- variants with each subset of U
disabled, runs the exact frozen T_task node ids under a tracing plugin, and
classifies each test as NOT_EXECUTED / NO_LOCAL_EFFECT / MASKED_EFFECT /
ASSERTION_GAP / INCONCLUSIVE.  No hidden answer or frozen evidence is modified.

Usage::

    python -m benchmark_real_v3.story_validation
    python -m benchmark_real_v3.story_validation --task <task_id>
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from benchmark_real_v3.config import EVIDENCE, PROJECTS, V3, WORK_ROOT
from benchmark_real_v3.variant_lab import build_variant
from benchmark_real_v3.run_suite import _kill_tree

TASKS = V3 / "tasks"
QUALIFIED = TASKS / "qualified_tasks.json"
OUT_ROOT = EVIDENCE / "story_validation"
RUN_ROOT = OUT_ROOT / "runs"
KIT = Path(__file__).resolve().parents[1]

OBSERVATIONS = {
    "jinja2_bytecode_cache_read": [{
        "file": "src/jinja2/environment.py",
        "co_name": "render",
        "class_name": "Template",
        "kind": "value",
    }],
    "werkzeug_bind_server_name_lower": [{
        "file": "src/werkzeug/routing/map.py",
        "co_name": "bind_to_environ",
        "class_name": "Map",
        "kind": "adapter",
    }],
    "werkzeug_filestorage_stream_name": [{
        "file": "src/werkzeug/datastructures.py",
        "co_name": "__init__",
        "class_name": "FileStorage",
        "kind": "self_filename",
    }],
    "werkzeug_get_host_default_empty": [{
        "file": "src/werkzeug/sansio/utils.py",
        "co_name": "get_host",
        "kind": "value",
    }],
    "werkzeug_secure_filename_ascii_filter": [{
        "file": "src/werkzeug/utils.py",
        "co_name": "secure_filename",
        "kind": "value",
    }],
}


def _sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _target_var(op: Dict[str, Any]) -> str:
    """The assigned local variable of a simple assignment operation."""
    if op.get("var"):
        return str(op["var"])
    left = str(op.get("code", "")).split("=", 1)[0].strip()
    if not left:
        raise ValueError(f"cannot derive variable from operation: {op}")
    return left


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _same(left: Any, right: Any) -> bool:
    return _canon(left) == _canon(right)


def _subset_key(ops: Iterable[Dict[str, Any]]) -> str:
    return "+".join(sorted(op["id"] for op in ops)) or "EMPTY"


def _subsets(ops: Sequence[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], ...]]:
    out = []
    for size in range(len(ops) + 1):
        out.extend(itertools.combinations(ops, size))
    return out


def _variant_name(task_id: str, kind: str, key: str = "") -> str:
    name = f"story_{task_id}_{kind}"
    if key:
        name += "_" + key.replace("+", "_")
    return name


def _build_task_variants(spec: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    task_id = spec["task_id"]
    project_id = spec["project_id"]
    target = spec["target_operation"]
    universe = list(spec["candidate_universe"])
    variants: Dict[str, Dict[str, Any]] = {}
    plus = build_variant(project_id, _variant_name(task_id, "plus"))
    variants["plus"] = {"kind": "plus", "disabled": [], "variant": plus}

    for subset in _subsets(universe):
        key = _subset_key(subset)
        statements = [(target["file"], target["line"])]
        blocks = []
        for op in subset:
            if op.get("kind") == "block":
                blocks.append((op["file"], op["first_line"], op["last_line"]))
            else:
                statements.append((op["file"], op["line"]))
        variant = build_variant(
            project_id,
            _variant_name(task_id, "minus", key),
            statement_deletions=statements,
            block_deletions=blocks,
        )
        variants[key] = {
            "kind": "minus",
            "disabled": [op["id"] for op in subset],
            "variant": variant,
        }
    return variants


def _config(
    spec: Dict[str, Any], meta: Dict[str, Any], variant_key: str
) -> Dict[str, Any]:
    disabled = set(meta["disabled"])
    return {
        "task_id": spec["task_id"],
        "variant": variant_key,
        "root": meta["variant"]["root"],
        # In a P- variant the target line is a `pass` placeholder; do not
        # report that placeholder as an execution of A.
        "target": ({
            "file": spec["target_operation"]["file"],
            "line": int(spec["target_operation"]["line"]),
            "var": _target_var(spec["target_operation"]),
        } if meta["kind"] == "plus" else None),
        # Disabled operations are absent from this variant; a `pass` left at
        # their old line must not be recorded as an executed U operation.
        "u_operations": [
            {
                "id": op["id"],
                "file": op["file"],
                "first_line": int(op.get("first_line", op.get("line"))),
                "last_line": int(op.get("last_line", op.get("line"))),
                "var": _target_var(op),
            }
            for op in spec["candidate_universe"]
            if op["id"] not in disabled
        ],
        "observations": OBSERVATIONS[spec["task_id"]],
    }


def _run_variant(
    spec: Dict[str, Any],
    variant_key: str,
    meta: Dict[str, Any],
    nodeids: Sequence[str],
) -> Dict[str, Any]:
    task_id = spec["task_id"]
    cfg = PROJECTS[spec["project_id"]]
    root = Path(meta["variant"]["root"])
    run_dir = RUN_ROOT / task_id / variant_key.replace("+", "_")
    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = run_dir / "trace_config.json"
    out_path = run_dir / "trace.json"
    select_path = run_dir / "select.txt"
    log_path = run_dir / "pytest.log"
    _write(config_path, _config(spec, meta, variant_key))
    select_path.write_text("\n".join(sorted(nodeids)) + "\n", encoding="utf-8")
    test_args = sorted({nodeid.split("::", 1)[0] for nodeid in nodeids})
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([
        str(KIT), str((root / cfg["source_dir"]).resolve())
    ])
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env.pop("PYTEST_ADDOPTS", None)
    env["MACE_STORY_CONFIG"] = str(config_path.resolve())
    env["MACE_STORY_OUT"] = str(out_path.resolve())
    env["V3_SELECT_FILE"] = str(select_path.resolve())
    command = [
        cfg["python"], "-m", "pytest", *test_args,
        "-q", "--disable-warnings",
        "-p", "benchmark_real_v3.select_plugin",
        "-p", "benchmark_real_v3.story_trace_plugin",
        *cfg["extra_args"],
    ]
    process = subprocess.Popen(
        command, cwd=str(root), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace",
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=900)
        returncode = process.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(process.pid)
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        returncode = None
        stdout = stdout or ""
        stderr = stderr or ""
    log_path.write_text(
        "$ " + " ".join(command)
        + "\n\n--- stdout ---\n" + stdout
        + "\n--- stderr ---\n" + stderr,
        encoding="utf-8",
    )
    trace = None
    if out_path.exists():
        trace = json.loads(out_path.read_text(encoding="utf-8"))
    tests = (trace or {}).get("tests", {})
    outcomes: Dict[str, int] = {}
    for row in tests.values():
        outcome = (row.get("reports") or {}).get("outcome") or "missing"
        outcomes[outcome] = outcomes.get(outcome, 0) + 1
    return {
        "task_id": task_id,
        "variant_key": variant_key,
        "variant_name": root.name,
        "disabled": meta["disabled"],
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "outcomes": outcomes,
        "log": str(log_path),
        "trace": str(out_path),
        "stdout_tail": stdout[-2000:],
        "stderr_tail": stderr[-2000:],
        "tests": tests,
    }


def _test_source(project_root: Path, location: Dict[str, Any]) -> Dict[str, Any]:
    path = project_root / location.get("file", "")
    if not path.exists():
        return {"file": location.get("file"), "excerpt": None}
    lines = path.read_text(encoding="utf-8").splitlines()
    start = max(1, int(location.get("line") or 1))
    end = min(len(lines), start + 24)
    return {
        "file": location.get("file"),
        "line": start,
        "excerpt": "\n".join(lines[start - 1:end]),
        "sha256": _sha(path),
    }


def _observation_list(run: Dict[str, Any], nodeid: str) -> List[Dict[str, Any]]:
    row = run["tests"].get(nodeid) or {}
    return list(row.get("observations") or [])


def _a_executions(run: Dict[str, Any], nodeid: str) -> List[Dict[str, Any]]:
    row = run["tests"].get(nodeid) or {}
    return list(row.get("a_executions") or [])


def _u_executions(run: Dict[str, Any], nodeid: str) -> List[Dict[str, Any]]:
    row = run["tests"].get(nodeid) or {}
    return list(row.get("u_executions") or [])


def _outcome(run: Dict[str, Any], nodeid: str) -> str:
    row = run["tests"].get(nodeid) or {}
    return ((row.get("reports") or {}).get("outcome") or "missing")


def _minimal_sets(
    universe: Sequence[Dict[str, Any]],
    predicate,
) -> List[List[str]]:
    valid = []
    for size in range(1, len(universe) + 1):
        for subset in itertools.combinations(universe, size):
            if predicate(set(op["id"] for op in subset)):
                if not any(
                    set(op["id"] for op in existing) < set(op["id"] for op in subset)
                    for existing in valid
                ):
                    valid.append(list(subset))
    return [
        sorted(op["id"] for op in subset)
        for subset in valid
    ]


def _relations(
    spec: Dict[str, Any],
    runs: Dict[str, Dict[str, Any]],
    nodeid: str,
) -> Dict[str, Any]:
    universe = list(spec["candidate_universe"])
    plus_obs = _observation_list(runs["plus"], nodeid)
    by_disabled: Dict[str, Any] = {}
    for key, run in runs.items():
        if key == "plus":
            continue
        by_disabled[key] = _observation_list(run, nodeid)
    empty_obs = by_disabled.get("EMPTY")
    masked = empty_obs is not None and _same(empty_obs, plus_obs)
    if not plus_obs or not masked:
        return {"masked_at_empty": bool(masked), "msms": [], "mmbs": []}

    def disabled_key(ids: set[str]) -> str:
        return "+".join(sorted(ids)) or "EMPTY"

    def sufficient(ids: set[str]) -> bool:
        complement = {op["id"] for op in universe} - ids
        key = disabled_key(complement)
        return key in by_disabled and _same(by_disabled[key], plus_obs)

    def breaking(ids: set[str]) -> bool:
        key = disabled_key(ids)
        return key in by_disabled and not _same(by_disabled[key], plus_obs)

    msms = _minimal_sets(universe, sufficient)
    mmbs = _minimal_sets(universe, breaking)
    return {"masked_at_empty": True, "msms": msms, "mmbs": mmbs}


def _classify(
    nodeid: str,
    plus_a: List[Dict[str, Any]],
    plus_obs: List[Dict[str, Any]],
    minus_obs: List[Dict[str, Any]],
    plus_outcome: str,
    minus_outcome: str,
    relations: Dict[str, Any],
) -> Tuple[str, str]:
    if not plus_a:
        return "NOT_EXECUTED", "A did not execute in P+ under this test."
    local_effects = [rec for rec in plus_a if rec.get("changed")]
    if not local_effects:
        return (
            "NO_LOCAL_EFFECT",
            "A executed but its target variable was unchanged at A in every execution.",
        )
    if not plus_obs or not minus_obs:
        return (
            "INCONCLUSIVE",
            "A had a local effect but no target-return observation was captured.",
        )
    if minus_outcome != "passed" or plus_outcome != "passed":
        return (
            "INCONCLUSIVE",
            f"test did not pass on both P+ and P- (plus={plus_outcome}, minus={minus_outcome}).",
        )
    if not _same(plus_obs, minus_obs):
        return (
            "ASSERTION_GAP",
            "P+ and P- final observations differ while the original test passes on both.",
        )
    if relations.get("msms"):
        return (
            "MASKED_EFFECT",
            "A had a local effect; P+ equals P-; a nonempty subset of U is sufficient "
            "when restored, and disabling the complement exposes the difference.",
        )
    return (
        "INCONCLUSIVE",
        "P+ and P- observations agree, but no nonempty U subset was sufficient "
        "in the intervention matrix.",
    )


def _test_record(
    spec: Dict[str, Any],
    runs: Dict[str, Dict[str, Any]],
    nodeid: str,
) -> Dict[str, Any]:
    plus_run = runs["plus"]
    minus_run = runs["EMPTY"]
    plus_a = _a_executions(plus_run, nodeid)
    minus_a = _a_executions(minus_run, nodeid)
    plus_u = _u_executions(plus_run, nodeid)
    minus_u = _u_executions(minus_run, nodeid)
    plus_obs = _observation_list(plus_run, nodeid)
    minus_obs = _observation_list(minus_run, nodeid)
    relations = _relations(spec, runs, nodeid)
    plus_outcome = _outcome(plus_run, nodeid)
    minus_outcome = _outcome(minus_run, nodeid)
    classification, reason = _classify(
        nodeid, plus_a, plus_obs, minus_obs,
        plus_outcome, minus_outcome, relations)
    row = plus_run["tests"].get(nodeid) or {}
    location = row.get("location") or {}
    disabled_obs = {
        key: _observation_list(run, nodeid)
        for key, run in runs.items()
        if key != "plus"
    }
    outcomes = {
        key: _outcome(run, nodeid)
        for key, run in runs.items()
    }
    return {
        "task_id": spec["task_id"],
        "nodeid": nodeid,
        "test_file": location.get("file") or nodeid.split("::", 1)[0],
        "test_line": location.get("line"),
        "test_source": _test_source(PROJECTS[spec["project_id"]]["root"], location),
        "param_id": row.get("param_id"),
        "params": row.get("params") or {},
        "funcargs": row.get("funcargs") or {},
        "a": {
            "file": spec["target_operation"]["file"],
            "line": int(spec["target_operation"]["line"]),
            "var": _target_var(spec["target_operation"]),
            "plus_execution_count": len(plus_a),
            "minus_execution_count": len(minus_a),
            "plus_executions": plus_a,
            "minus_executions": minus_a,
            "local_effect_instances": sum(1 for rec in plus_a if rec.get("changed")),
        },
        "u": {
            op["id"]: {
                "file": op["file"],
                "first_line": int(op.get("first_line", op.get("line"))),
                "last_line": int(op.get("last_line", op.get("line"))),
                "plus_execution_count": sum(
                    1 for rec in plus_u if rec["id"] == op["id"]),
                "minus_execution_count": sum(
                    1 for rec in minus_u if rec["id"] == op["id"]),
                "plus_executions": [
                    rec for rec in plus_u if rec["id"] == op["id"]],
                "minus_executions": [
                    rec for rec in minus_u if rec["id"] == op["id"]],
            }
            for op in spec["candidate_universe"]
        },
        "observations": {
            "plus": plus_obs,
            "minus": minus_obs,
            "by_disabled_subset": disabled_obs,
        },
        "outcomes": outcomes,
        "observed_relations": relations,
        "classification": classification,
        "reason": reason,
        "scope": (
            "One original T_task execution with the test's own inputs; U is "
            "the declared hidden universe; no claim beyond this finite "
            "execution and U."),
    }


def _task_report(
    spec: Dict[str, Any],
    qualified: Dict[str, Any],
    matrix: Dict[str, Any],
    tests: List[Dict[str, Any]],
) -> Dict[str, Any]:
    by_class: Dict[str, List[str]] = {}
    for test in tests:
        by_class.setdefault(test["classification"], []).append(test["nodeid"])
    masked = [t for t in tests if t["classification"] == "MASKED_EFFECT"]
    assertion = [t for t in tests if t["classification"] == "ASSERTION_GAP"]
    no_local = [t for t in tests if t["classification"] == "NO_LOCAL_EFFECT"]
    not_exec = [t for t in tests if t["classification"] == "NOT_EXECUTED"]
    inconclusive = [t for t in tests if t["classification"] == "INCONCLUSIVE"]

    exposing = [
        item for item in matrix["inputs"].values()
        if item["role"] == "exposing"
    ]
    masking = [
        item for item in matrix["inputs"].values()
        if item["role"] == "masking"
    ]
    if masked:
        story = "FULL_MASKING_STORY"
    elif assertion:
        story = "ASSERTION_GAP_STORY"
    elif exposing and not inconclusive:
        story = "TEST_SURVIVES_BUT_MASK_NOT_ESTABLISHED"
    else:
        story = "INCONCLUSIVE"

    representative = None
    if masked:
        chosen = masked[0]
        representative = {
            "nodeid": chosen["nodeid"],
            "classification": chosen["classification"],
            "a": chosen["a"],
            "u": chosen["u"],
            "observations": chosen["observations"],
            "outcomes": chosen["outcomes"],
            "observed_relations": chosen["observed_relations"],
            "reason": chosen["reason"],
        }
    return {
        "task_id": spec["task_id"],
        "project": spec["source_version"],
        "label": story,
        "classification": story,
        "test_count": len(tests),
        "counts": {
            key: len(value) for key, value in sorted(by_class.items())
        },
        "masked_effect_tests": by_class.get("MASKED_EFFECT", []),
        "assertion_gap_tests": by_class.get("ASSERTION_GAP", []),
        "no_local_effect_tests": by_class.get("NO_LOCAL_EFFECT", []),
        "not_executed_tests": by_class.get("NOT_EXECUTED", []),
        "inconclusive_tests": by_class.get("INCONCLUSIVE", []),
        "exposing_counterexample": {
            "witness": exposing[0] if exposing else None,
            "purpose": "Existing hidden exposing witness for this task.",
        },
        "reference_masking_witness": {
            "witness": masking[0] if masking else None,
            "existing_msms": masking[0]["msms"] if masking else [],
            "existing_mmbs": masking[0]["mmbs"] if masking else [],
            "note": (
                "This is the prior declared witness.  Original-test relations "
                "above are recomputed from the tests' own inputs and are not "
                "copied from this witness."),
        },
        "representative_masked_test": representative,
        "scope": (
            f"All {len(tests)} frozen T_task node ids were executed on P+, P- "
            "and every U-disabled P- variant.  Relations are exact only for "
            "these test executions and the declared U; no claim over the "
            "whole legal input domain or operations outside U."),
    }


def evaluate(task_id: str) -> Dict[str, Any]:
    qualified_payload = json.loads(QUALIFIED.read_text(encoding="utf-8"))
    qualified = {
        item["task_id"]: item
        for item in qualified_payload["tasks"]
    }[task_id]
    spec = json.loads(
        (TASKS / task_id / "spec.json").read_text(encoding="utf-8"))
    matrix = json.loads(
        (EVIDENCE / f"{task_id}_matrix.json").read_text(encoding="utf-8"))
    nodeids = qualified["t_task"]
    variants = _build_task_variants(spec)
    runs: Dict[str, Dict[str, Any]] = {}
    for key, meta in variants.items():
        runs[key] = _run_variant(spec, key, meta, nodeids)
    tests = [_test_record(spec, runs, nodeid) for nodeid in nodeids]
    report = _task_report(spec, qualified, matrix, tests)
    report["variant_runs"] = {
        key: {
            "disabled": run["disabled"],
            "returncode": run["returncode"],
            "outcomes": run["outcomes"],
            "log": run["log"],
            "trace": run["trace"],
        }
        for key, run in runs.items()
    }
    _write(OUT_ROOT / f"{task_id}_tests.json", tests)
    _write(OUT_ROOT / f"{task_id}_story.json", report)
    return report


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--task", action="append", default=None)
    parser.add_argument(
        "--aggregate", action="store_true",
        help="Rebuild the top-level report from existing per-task reports.")
    args = parser.parse_args()
    payload = json.loads(QUALIFIED.read_text(encoding="utf-8"))
    task_ids = args.task or [item["task_id"] for item in payload["tasks"]]
    if args.aggregate:
        reports = [
            json.loads((OUT_ROOT / f"{task_id}_story.json").read_text(
                encoding="utf-8"))
            for task_id in task_ids
        ]
    else:
        reports = [evaluate(task_id) for task_id in task_ids]
    _write(OUT_ROOT / "story_validation.json", {
        "schema": "mace_benchmark_story_validation",
        "version": "v3.0-dev-pilot-2026-11-02",
        "task_count": len(reports),
        "tasks": reports,
    })
    print(json.dumps({
        "tasks": [
            {
                "task_id": report["task_id"],
                "label": report["label"],
                "counts": report["counts"],
            }
            for report in reports
        ],
        "report": str(OUT_ROOT / "story_validation.json"),
    }, ensure_ascii=False, indent=2))
    return 0 if all(report["test_count"] for report in reports) else 1


if __name__ == "__main__":
    raise SystemExit(main())
