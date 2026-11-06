"""Per-test story qualification for v4 survivors.

For one surviving static candidate this builds P+, P- (A deleted) and P- with
each subset of the candidate's later same-name assignments deleted, runs the
original tests that execute A under the tracing plugin, and classifies each
test as NOT_EXECUTED / NO_LOCAL_EFFECT / MASKED_EFFECT / ASSERTION_GAP /
INCONCLUSIVE.  The local observation is the final value of the target
variable in A's enclosing function.

This is a qualification aid, not a benchmark task definition.  A candidate is
promoted only after a legal input probe is added and an exposing input is
found (see manual notes in the report).

Usage::

    python -m benchmark_real_v4.qualify <candidate_id>
    python -m benchmark_real_v4.qualify --list
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import itertools
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from benchmark_real_v3.config import KIT
from benchmark_real_v3.run_suite import _kill_tree
from benchmark_real_v3 import variant_lab
from benchmark_real_v4.config import CANDIDATES, EVIDENCE, PROJECTS, WORK_ROOT

# The variant builder resolves projects from its own module globals.  Point it
# at the v4 expansion projects for this process only.
variant_lab.PROJECTS = PROJECTS
variant_lab.WORK_ROOT = WORK_ROOT
variant_lab.VARIANT_ROOT = WORK_ROOT / "variants"
build_variant = variant_lab.build_variant

FUNNEL = Path(os.environ.get(
    "MACE_QUALIFY_FUNNEL", str(EVIDENCE / "screening_funnel.json")))
ROWS_DIR = Path(os.environ.get(
    "MACE_QUALIFY_ROWS", str(EVIDENCE / "screening_rows")))
OUT_ROOT = EVIDENCE / "qualification"
RUN_ROOT = OUT_ROOT / "runs"
MAX_TESTS = 25
MAX_U = 4


def _write(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2,
                               sort_keys=True) + "\n", encoding="utf-8")


def _slug(candidate_id: str) -> str:
    return (candidate_id.replace(":", "_").replace("/", "_")
            .replace("\\", "_").replace(".", "_"))[:120]


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _same(left: Any, right: Any) -> bool:
    return _canon(left) == _canon(right)


def load_rows() -> List[Dict[str, Any]]:
    """Full funnel when written, otherwise the completed checkpoint rows."""
    if FUNNEL.exists():
        return json.loads(FUNNEL.read_text(encoding="utf-8"))["candidates"]
    loaded = [json.loads(path.read_text(encoding="utf-8"))
              for path in sorted(ROWS_DIR.glob("*.json"))] \
        if ROWS_DIR.exists() else []
    rows = [row for row in loaded if isinstance(row, dict)
            and "candidate_id" in row]
    if not rows:
        raise SystemExit(f"missing {FUNNEL}; run screening first")
    return rows


def find_row(candidate_id: str) -> Dict[str, Any]:
    for row in load_rows():
        if row["candidate_id"] == candidate_id:
            return row
    # Hand-picked candidates outside the reviewed funnel still have a static
    # record.  They carry no original hit tests; a qualification of one must
    # supply a designed test set.
    for source in sorted(CANDIDATES.glob("*.json")):
        data = json.loads(source.read_text(encoding="utf-8"))
        for row in data.get("candidates", []):
            if row.get("candidate_id") == candidate_id:
                row = dict(row)
                row.setdefault("p_plus_hit_tests", [])
                return row
    raise SystemExit(f"unknown candidate: {candidate_id}")


def _enclosing(tree: ast.Module, line: int) -> Dict[str, Any]:
    found = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.lineno <= line <= (node.end_lineno or node.lineno):
                if found is None or node.lineno >= found.lineno:
                    found = node
    if found is None:
        return {"co_name": None, "class_name": None}
    class_name = None
    for node in ast.walk(tree):
        if isinstance(node, ast.ClassDef) and node.lineno <= found.lineno \
                <= (node.end_lineno or node.lineno):
            class_name = node.name
    return {"co_name": found.name, "class_name": class_name}


def build_spec(row: Dict[str, Any]) -> Dict[str, Any]:
    cfg = PROJECTS[row["project_id"]]
    source = (cfg["root"] / row["file"]).read_text(encoding="utf-8")
    tree = ast.parse(source)
    line = int(row["target_A"]["line"])
    enclosing = _enclosing(tree, line)
    later = sorted(row["later_assignments"], key=lambda item: item["line"])
    cross_function = row.get("mechanism") in ("cross_function", "cross_method")
    chosen = []
    for item in later:
        if not cross_function and item["line"] <= line:
            continue
        if len(chosen) >= MAX_U:
            break
        chosen.append(item)
    ops = []
    for index, item in enumerate(chosen):
        ops.append({
            "id": f"L{item['line']}",
            "file": row["file"],
            "line": int(item["line"]),
            "first_line": int(item["line"]),
            "last_line": int(item["line"]),
            "code": item["code"],
            "kind": item["kind"],
            "key_kind": row.get("key_kind", "name"),
            "key_obj": item.get("key_obj", ""),
            "key_index": item.get("key_index"),
        })
    observation = {
        "file": row["file"],
        **enclosing,
        "kind": "local_var",
        "var": row["variable"],
    }
    key_kind = row.get("key_kind", "name")
    if key_kind == "attr":
        observation.update({
            "kind": "attribute",
            "obj_var": row.get("key_obj", "self"),
            "attr": row["variable"],
        })
    elif key_kind == "sub":
        if row.get("key_index") is not None:
            observation.update({
                "kind": "item",
                "obj_var": row.get("key_obj", ""),
                "index": row["key_index"],
            })
        else:
            observation.update({
                "kind": "item_all",
                "obj_var": row.get("key_obj", ""),
            })
    return {
        "candidate_id": row["candidate_id"],
        "project_id": row["project_id"],
        "target_operation": {
            "file": row["file"], "line": line,
            "code": row["target_A"]["code"], "var": row["variable"],
            "key_kind": key_kind,
            "key_obj": row.get("key_obj", ""),
            "key_index": row.get("key_index"),
        },
        "candidate_universe": ops,
        "observation": observation,
        "tests": row["p_plus_hit_tests"][:MAX_TESTS],
        "all_hit_tests": len(row["p_plus_hit_tests"]),
    }


def _variant_name(spec: Dict[str, Any], kind: str, key: str = "") -> str:
    base = f"v4q_{_slug(spec['candidate_id'])}_{kind}"
    return base + ("_" + key.replace("+", "_") if key else "")


def build_variants(spec: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    project_id = spec["project_id"]
    target = spec["target_operation"]
    universe = list(spec["candidate_universe"])
    variants: Dict[str, Dict[str, Any]] = {}
    plus = build_variant(project_id, _variant_name(spec, "plus"))
    variants["plus"] = {"kind": "plus", "disabled": [], "variant": plus}
    for size in range(len(universe) + 1):
        for subset in itertools.combinations(universe, size):
            key = "+".join(op["id"] for op in subset) or "EMPTY"
            statements = [(target["file"], int(target["line"]))]
            for op in subset:
                statements.append((op["file"], op["line"]))
            variant = build_variant(
                project_id, _variant_name(spec, "minus", key),
                statement_deletions=statements)
            variants[key] = {
                "kind": "minus",
                "disabled": [op["id"] for op in subset],
                "variant": variant,
            }
    return variants


def _config(spec: Dict[str, Any], meta: Dict[str, Any]) -> Dict[str, Any]:
    disabled = set(meta["disabled"])
    return {
        "task_id": spec["candidate_id"],
        "variant": "plus" if meta["kind"] == "plus" else "minus",
        "root": meta["variant"]["root"],
        "target": (spec["target_operation"]
                   if meta["kind"] == "plus" else None),
        "u_operations": [
            {
                "id": op["id"], "file": op["file"],
                "first_line": int(op["first_line"]),
                "last_line": int(op["last_line"]),
                "var": spec["target_operation"]["var"],
                "key_kind": op.get("key_kind", "name"),
                "key_obj": op.get("key_obj", ""),
                "key_index": op.get("key_index"),
            }
            for op in spec["candidate_universe"]
            if op["id"] not in disabled
        ],
        "observations": [dict(spec["observation"])],
    }


def run_variant(spec: Dict[str, Any], key: str,
                meta: Dict[str, Any]) -> Dict[str, Any]:
    cfg = PROJECTS[spec["project_id"]]
    root = Path(meta["variant"]["root"])
    run_dir = RUN_ROOT / _slug(spec["candidate_id"]) / key.replace("+", "_")
    run_dir.mkdir(parents=True, exist_ok=True)
    config_path = run_dir / "trace_config.json"
    out_path = run_dir / "trace.json"
    select_path = run_dir / "select.txt"
    log_path = run_dir / "pytest.log"
    _write(config_path, _config(spec, meta))
    nodeids = spec["tests"]
    select_path.write_text("\n".join(sorted(nodeids)) + "\n", encoding="utf-8")
    test_args = sorted({nodeid.split("::", 1)[0] for nodeid in nodeids})
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join([
        str(KIT), str((root / cfg["source_dir"]).resolve())])
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
        "-p", "benchmark_real_v4.story_plugin",
        *cfg["extra_args"],
    ]
    process = subprocess.Popen(
        command, cwd=str(root), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
        encoding="utf-8", errors="replace")
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
        "$ " + " ".join(command) + "\n\n--- stdout ---\n" + stdout
        + "\n--- stderr ---\n" + stderr, encoding="utf-8")
    trace = None
    if out_path.exists():
        trace = json.loads(out_path.read_text(encoding="utf-8"))
    return {
        "key": key,
        "returncode": returncode,
        "timed_out": timed_out,
        "tests": (trace or {}).get("tests", {}),
        "log": str(log_path),
        "trace": str(out_path),
        "stdout_tail": stdout[-1500:],
        "stderr_tail": stderr[-1500:],
    }


def _obs(run: Dict[str, Any], nodeid: str) -> List[Dict[str, Any]]:
    return list((run["tests"].get(nodeid) or {}).get("observations") or [])


def _outcome(run: Dict[str, Any], nodeid: str) -> str:
    row = run["tests"].get(nodeid) or {}
    return ((row.get("reports") or {}).get("outcome") or "missing")


def _minimal(universe: Sequence[Dict[str, Any]], predicate) -> List[List[str]]:
    valid = []
    for size in range(1, len(universe) + 1):
        for subset in itertools.combinations(universe, size):
            ids = set(op["id"] for op in subset)
            if predicate(ids) and not any(
                    set(op["id"] for op in existing) < ids
                    for existing in valid):
                valid.append(list(subset))
    return [sorted(op["id"] for op in subset) for subset in valid]


def relations(spec: Dict[str, Any],
              runs: Dict[str, Dict[str, Any]],
              nodeid: str) -> Dict[str, Any]:
    universe = list(spec["candidate_universe"])
    plus_obs = _obs(runs["plus"], nodeid)
    by_disabled = {key: _obs(run, nodeid)
                   for key, run in runs.items() if key != "plus"}
    empty = by_disabled.get("EMPTY")
    masked = empty is not None and _same(empty, plus_obs)
    executed = {rec.get("id") for rec in
                ((runs["plus"]["tests"].get(nodeid) or {})
                 .get("u_executions") or [])}
    if not plus_obs or not masked:
        return {"masked_at_empty": bool(masked), "msms": [], "mmbs": [],
                "u_executed": sorted(x for x in executed if x)}

    def key_for(ids: set) -> str:
        return "+".join(sorted(ids)) or "EMPTY"

    def sufficient(ids: set) -> bool:
        # ``ids`` is the set of U operations kept; everything else in U is
        # deleted together with A.  Keeping the whole of U reduces to the
        # empty-complement variant, which is accepted only when at least one
        # subset deletion also exposes (checked below).
        if not ids:
            return False
        complement = {op["id"] for op in universe} - ids
        key = key_for(complement)
        return key in by_disabled and _same(by_disabled[key], plus_obs)

    def breaking(ids: set) -> bool:
        if not ids:
            return False
        key = key_for(ids)
        return key in by_disabled and not _same(by_disabled[key], plus_obs)

    msms = _minimal(universe, sufficient)
    mmbs = _minimal(universe, breaking)
    # A masking story needs at least one U subset whose deletion exposes.
    # Without it the equality is supplied by something outside U (as in the
    # earlier L1650 false positive) and no masking relation is established.
    if not mmbs:
        msms = []
    return {
        "masked_at_empty": True,
        "msms": msms,
        "mmbs": mmbs,
        "u_executed": sorted(x for x in executed if x),
    }


def classify(spec: Dict[str, Any], runs: Dict[str, Dict[str, Any]],
             nodeid: str) -> Dict[str, Any]:
    plus = runs["plus"]
    minus = runs["EMPTY"]
    plus_row = plus["tests"].get(nodeid) or {}
    a_exec = list(plus_row.get("a_executions") or [])
    local = [rec for rec in a_exec if rec.get("changed")]
    plus_obs = _obs(plus, nodeid)
    minus_obs = _obs(minus, nodeid)
    rel = relations(spec, runs, nodeid)
    plus_out = _outcome(plus, nodeid)
    minus_out = _outcome(minus, nodeid)
    if not a_exec:
        label, reason = "NOT_EXECUTED", "A did not execute in P+."
    elif not local:
        label, reason = ("NO_LOCAL_EFFECT",
                         "A executed but its variable value did not change.")
    elif not plus_obs or not minus_obs:
        label, reason = "INCONCLUSIVE", "no final observation captured."
    elif plus_out != "passed" or minus_out != "passed":
        label, reason = ("INCONCLUSIVE",
                         f"test did not pass on both sides "
                         f"(plus={plus_out}, minus={minus_out}).")
    elif not _same(plus_obs, minus_obs):
        label, reason = ("ASSERTION_GAP",
                         "P+ and P- final observations differ while both pass.")
    elif rel["msms"]:
        label, reason = ("MASKED_EFFECT",
                         "local effect; P+ equals P-; a nonempty U subset is "
                         "sufficient and the complement exposes.")
    else:
        label, reason = ("INCONCLUSIVE",
                         "P+ equals P-, but no nonempty U subset was sufficient.")
    return {
        "nodeid": nodeid,
        "classification": label,
        "reason": reason,
        "a_executions": len(a_exec),
        "local_effect_instances": len(local),
        "a_records": a_exec,
        "plus_observation": plus_obs,
        "minus_observation": minus_obs,
        "plus_outcome": plus_out,
        "minus_outcome": minus_out,
        "relations": rel,
        "u_executions": list(plus_row.get("u_executions") or []),
        "funcargs": plus_row.get("funcargs"),
        "params": plus_row.get("params"),
        "location": plus_row.get("location"),
    }


def qualify(candidate_id: str, require_survivor: bool = True) -> Dict[str, Any]:
    row = find_row(candidate_id)
    if require_survivor and row["screening_status"] != "TEST_SURVIVING_DELETION":
        raise SystemExit(
            f"{candidate_id} is {row['screening_status']}, not a survivor")
    spec = build_spec(row)
    if not spec["tests"]:
        raise SystemExit(f"{candidate_id} has no hit tests")
    variants = build_variants(spec)
    runs = {key: run_variant(spec, key, meta)
            for key, meta in variants.items()}
    tests = [classify(spec, runs, nodeid) for nodeid in spec["tests"]]
    counts: Dict[str, int] = {}
    for test in tests:
        counts[test["classification"]] = counts.get(
            test["classification"], 0) + 1
    payload = {
        "candidate_id": candidate_id,
        "project": row["project"],
        "version": row["version"],
        "file": row["file"],
        "function": row["function"],
        "target_A": row["target_A"],
        "later_assignments": row["later_assignments"],
        "spec": spec,
        "counts": counts,
        "tests": tests,
        "variants": {
            key: {"returncode": run["returncode"],
                  "timed_out": run["timed_out"],
                  "log": run["log"], "trace": run["trace"]}
            for key, run in runs.items()
        },
        "exit": {key: run["returncode"] for key, run in runs.items()},
    }
    _write(OUT_ROOT / f"{_slug(candidate_id)}.json", payload)
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_id", nargs="?")
    parser.add_argument("--list", action="store_true")
    parser.add_argument("--all-survivors", action="store_true")
    parser.add_argument("--allow-detecting", action="store_true",
                        help="Also qualify candidates whose deletion breaks "
                             "some tests; per-test classification may still "
                             "find masked tests and exposing tests.")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()
    if args.list:
        for row in load_rows():
            if row["screening_status"] == "TEST_SURVIVING_DELETION":
                print(f"{row['candidate_id']}  tests={len(row['p_plus_hit_tests'])}"
                      f"  later={len(row['later_assignments'])}")
        return 0
    if args.all_survivors:
        rows = [row for row in load_rows()
                if row["screening_status"] == "TEST_SURVIVING_DELETION"]
        rows = [row for row in rows
                if len(row["p_plus_hit_tests"]) <= MAX_TESTS * 4]
        for row in rows[:args.limit]:
            payload = qualify(row["candidate_id"])
            print(json.dumps({
                "candidate": row["candidate_id"],
                "counts": payload["counts"],
                "u": [op["id"] for op in payload["spec"]["candidate_universe"]],
            }, ensure_ascii=False))
        return 0
    if not args.candidate_id:
        parser.print_help()
        return 2
    payload = qualify(args.candidate_id,
                      require_survivor=not args.allow_detecting)
    print(json.dumps({
        "candidate": payload["candidate_id"],
        "counts": payload["counts"],
        "u": [op["id"] for op in payload["spec"]["candidate_universe"]],
        "tests": [
            {"nodeid": t["nodeid"], "class": t["classification"],
             "local": t["local_effect_instances"],
             "msms": t["relations"]["msms"], "mmbs": t["relations"]["mmbs"]}
            for t in payload["tests"]
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
