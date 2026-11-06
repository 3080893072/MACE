"""Independent M1 collaborative-masking screening over the frozen candidate set.

This tool does not re-select projects, candidates or hash order.  It consumes
``runs/v3_m1_screening/static_candidates.json`` (2500 reviewed functions) and
the pinned project trees, derives operation-level targets inside each reviewed
function, and tests the frozen M1 definition:

* target A executes on an original test input and has a local effect;
* deleting A leaves every selected original test passing (the masking
  phenomenon exists in the complete program);
* a non-empty kept set S with ``|S| >= 2`` is sufficient, every non-empty
  proper subset of S is not sufficient, and at least one member of S is
  individually inert (disabling it alone changes no plus/minus observation).

Stages::

    python -m scripts.m1_screen plan
    python -m scripts.m1_screen coverage --projects requests ...
    python -m scripts.m1_screen select
    python -m scripts.m1_screen probe
    python -m scripts.m1_screen matrix
    python -m scripts.m1_screen finalize
    python -m scripts.m1_screen status

All artifacts live under ``runs/v3_m1_screening/screen`` (gitignored for bulk
work trees and coverage databases; JSON evidence is kept).
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
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from benchmark_v3_baselines.ast_discovery import (  # noqa: E402
    _plain_lhs_names,
    _span,
    _statement_ops,
    reachable_functions,
)

OUT = KIT / "runs" / "v3_m1_screening"
PROJECTS = OUT / "projects"
VENVS = OUT / "venvs"
SCREEN = OUT / "screen"
WORK = SCREEN / "work"
COVERAGE = SCREEN / "coverage"
RUNS = SCREEN / "runs"
QUAL = KIT / "benchmark_real_pilot" / "qualification"
TARGETED_PM_BUDGET = 800
FULL_SUITE_PM_BUDGET = 150
MATRIX_EXEC_BUDGET = 250
MATRIX_WALL_BUDGET = 1200.0
MAX_U = 6

COPY_IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "*.pyo", ".pytest_cache", ".git", ".tox",
    ".venv", "venv", "build", "dist")


# --------------------------------------------------------------------------
# frozen inputs
# --------------------------------------------------------------------------
def load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")


def releases() -> Dict[str, Any]:
    return load_json(OUT / "releases.json")


def funnel() -> Dict[str, Any]:
    return load_json(OUT / "funnel_ledger.json")


def project_root(project: str, rel: Dict[str, Any]) -> Path:
    return PROJECTS / f"{project}-{rel[project]['version']}"


def package_dir(project: str) -> Path:
    return OUT / funnel()["per_project"][project]["package_root"]


def tests_dir(root: Path) -> Optional[str]:
    for name in ("tests", "test"):
        if (root / name).is_dir():
            return name
    return None


def source_root(root: Path) -> Path:
    for name in ("src", "lib"):
        if (root / name).is_dir():
            return root / name
    return root


def venv_python(project: str) -> Path:
    return VENVS / project / "Scripts" / "python.exe"


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


# --------------------------------------------------------------------------
# operation-level target derivation (no outcomes consulted)
# --------------------------------------------------------------------------
def _function_node(tree: ast.AST, candidate: Dict[str, Any]) -> Optional[ast.AST]:
    fallback = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if node.name != candidate["function"]:
                continue
            if int(node.lineno) == int(candidate["line"]):
                return node
            if fallback is None and int(node.lineno) <= int(candidate["line"]) \
                    <= int(getattr(node, "end_lineno", node.lineno)):
                fallback = node
    return fallback


def _direct_assignments(function: ast.AST) -> List[ast.AST]:
    """Assignments in the reviewed function's own body (nested defs excluded)."""
    found: List[ast.AST] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.ClassDef, ast.Lambda)):
                continue
            if isinstance(child, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                if _plain_lhs_names(child):
                    found.append(child)
            visit(child)

    visit(function)
    return sorted(found, key=lambda node: (int(node.lineno),
                                           int(getattr(node, "end_lineno",
                                                       node.lineno))))


def _embedded_one_liner(lines: Sequence[str], node: ast.stmt) -> bool:
    first, last = _span(node)
    if first != last:
        return False
    prefix = lines[first - 1][: int(node.col_offset)]
    return bool(prefix.strip())


def build_targets() -> Dict[str, Any]:
    rel = releases()
    candidates = load_json(OUT / "static_candidates.json")
    by_id = {c["candidate_id"]: c for c in candidates["candidates"]}
    targets: List[Dict[str, Any]] = []
    cache: Dict[Path, Tuple[str, ast.AST]] = {}
    skipped: Dict[str, int] = {}
    for cid in candidates["review_order"]:
        cand = by_id[cid]
        project = cand["project"]
        try:
            root = project_root(project, rel)
            pkg = package_dir(project)
        except KeyError:
            skipped["project_metadata"] = skipped.get("project_metadata", 0) + 1
            continue
        path = pkg / cand["file"]
        if not path.exists():
            skipped["file_missing"] = skipped.get("file_missing", 0) + 1
            continue
        if path not in cache:
            text = path.read_text(encoding="utf-8", errors="replace")
            cache[path] = (text, ast.parse(text))
        text, tree = cache[path]
        function = _function_node(tree, cand)
        if function is None:
            skipped["function_not_found"] = skipped.get(
                "function_not_found", 0) + 1
            continue
        lines = text.splitlines()
        for node in _direct_assignments(function):
            lhs = sorted(_plain_lhs_names(node))
            if not lhs:
                continue
            if _embedded_one_liner(lines, node):
                skipped["embedded_target"] = skipped.get(
                    "embedded_target", 0) + 1
                continue
            first, last = _span(node)
            functions = reachable_functions(
                tree, {"line": int(node.lineno)})
            if not functions:
                skipped["no_reachable_root"] = skipped.get(
                    "no_reachable_root", 0) + 1
                continue
            ops = _statement_ops(lines, cand["file"], functions[0],
                                 functions, set(lhs), int(node.lineno))
            # operations that are one-line embedded statements are not
            # independently deletable without also deleting their header.
            safe_ops = []
            for op in ops:
                op_node = None
                for candidate_node in ast.walk(tree):
                    if isinstance(candidate_node, ast.stmt) and \
                            int(candidate_node.lineno) == op["first_line"] and \
                            int(getattr(candidate_node, "end_lineno",
                                        candidate_node.lineno)) == \
                            op["last_line"]:
                        op_node = candidate_node
                        break
                if op_node is not None and _embedded_one_liner(lines, op_node):
                    skipped["embedded_operation"] = skipped.get(
                        "embedded_operation", 0) + 1
                    continue
                if op_node is not None and op["first_line"] != op["last_line"] \
                        and bool(lines[op["first_line"] - 1][
                            : int(op_node.col_offset)].strip()):
                    skipped["embedded_multiline_operation"] = skipped.get(
                        "embedded_multiline_operation", 0) + 1
                    continue
                safe_ops.append(op)
            target_id = (f"{cid}@{first}-{last}:"
                         f"{'+'.join(lhs)}")
            targets.append({
                "target_id": target_id,
                "candidate_id": cid,
                "project": project,
                "file": cand["file"],
                "function": cand["function"],
                "function_firstlineno": int(function.lineno),
                "function_code_firstlineno": min(
                    [int(function.lineno)] +
                    [int(d.lineno) for d in function.decorator_list]),
                "function_end": int(getattr(function, "end_lineno",
                                            function.lineno)),
                "a_first": first,
                "a_last": last,
                "a_lhs": lhs,
                "a_var": lhs[0],
                "a_code": "\n".join(lines[first - 1:last]),
                "u": safe_ops,
                "u_size": len(safe_ops),
                "u_dropped_embedded": len(ops) - len(safe_ops),
                "eligible": len(safe_ops) >= 2,
            })
    order_index = {cid: i for i, cid in enumerate(candidates["review_order"])}
    targets.sort(key=lambda t: (order_index[t["candidate_id"]],
                                t["a_first"], t["a_last"]))
    payload = {
        "stage": "m1_operation_targets",
        "source": "runs/v3_m1_screening/static_candidates.json",
        "rules": [
            "A is a plain-variable assignment in the reviewed function's own "
            "body; nested function/class bodies are excluded because they are "
            "separate scopes.",
            "U is the benchmark_v3_baselines.ast_discovery rule: other "
            "assignments to the same plain variable, after A in the same "
            "function or in reachable same-file helpers, plus qualifying "
            "'if' blocks.",
            "Targets and U are derived before any test outcome is observed.",
        ],
        "counts": {
            "reviewed_candidates": len(candidates["review_order"]),
            "targets": len(targets),
            "eligible_u_ge_2": sum(1 for t in targets if t["eligible"]),
            "targets_with_u": sum(1 for t in targets if t["u"]),
            "skipped": skipped,
            "by_project": {
                project: sum(1 for t in targets if t["project"] == project)
                for project in rel},
        },
        "targets": targets,
    }
    write_json(SCREEN / "targets.json", payload)
    print(json.dumps(payload["counts"], ensure_ascii=False, indent=2))
    return payload


# --------------------------------------------------------------------------
# coverage: which original tests execute A (P+ execution only)
# --------------------------------------------------------------------------
def coverage_targets() -> Dict[str, Any]:
    rel = releases()
    targets = load_json(SCREEN / "targets.json")["targets"]
    out: Dict[str, Any] = {}
    for target in targets:
        if not target["eligible"]:
            continue
        project = target["project"]
        pkg = package_dir(project)
        path = (pkg / target["file"]).resolve()
        entry = out.setdefault(project, {})
        entry.setdefault(str(path), {}).setdefault(
            str(target["a_first"]), []).append(target["target_id"])
    write_json(SCREEN / "coverage_targets.json", {
        "projects": out,
        "counts": {p: {"files": len(files),
                       "lines": sum(len(v) for v in files.values())}
                   for p, files in out.items()},
    })
    print(json.dumps({p: {"files": len(f), "lines": sum(len(v) for v in f.values())}
                      for p, f in out.items()}, indent=2))
    return out


def prepare_work(project: str, rel: Dict[str, Any]) -> Path:
    destination = WORK / project
    if destination.exists():
        return destination
    source = project_root(project, rel)
    shutil.copytree(source, destination, ignore=COPY_IGNORE)
    return destination


def run_coverage(project: str) -> Dict[str, Any]:
    rel = releases()
    root = project_root(project, rel)
    tests = tests_dir(root)
    if tests is None:
        return {"project": project, "status": "NO_TESTS"}
    work = prepare_work(project, rel)
    py = venv_python(project)
    pkg_name = package_dir(project).name
    COVERAGE.mkdir(parents=True, exist_ok=True)
    data_file = (COVERAGE / f"{project}.coverage").resolve()
    for stale in (data_file,):
        if stale.exists():
            stale.unlink()
    empty_ini = SCREEN / "empty_coveragerc"
    empty_ini.write_text("[run]\nbranch = False\n", encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root(work))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env["COVERAGE_FILE"] = str(data_file)
    env.pop("PYTEST_ADDOPTS", None)
    command = [str(py), "-m", "pytest", tests, "-q", "--disable-warnings",
               "--rootdir", str(work), "-p", "no:cacheprovider",
               "--cov", pkg_name, "--cov-context=test", "--cov-report="]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command, cwd=str(work), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=7200)
        returncode = completed.returncode
        stdout_tail = completed.stdout.strip().splitlines()[-25:]
        stderr_tail = completed.stderr.strip().splitlines()[-10:]
        timed_out = False
    except subprocess.TimeoutExpired:
        returncode, stdout_tail, stderr_tail = None, [], []
        timed_out = True
    wall = round(time.perf_counter() - started, 1)
    dumped = {"files": 0, "lines": 0}
    status = "COVERAGE_TIMEOUT" if timed_out else "COVERED"
    if data_file.exists():
        dump = subprocess.run(
            [str(py), str(KIT / "scripts" / "dump_coverage_contexts.py"),
             str(data_file), str(work), str(COVERAGE / f"{project}.json")],
            cwd=str(work), capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=1800)
        if dump.returncode != 0:
            status = "DUMP_FAILED"
            stderr_tail = stderr_tail + dump.stderr.strip().splitlines()[-10:]
        else:
            try:
                dumped = json.loads(
                    (COVERAGE / f"{project}.json").read_text(
                        encoding="utf-8"))
                dumped = {"files": len(dumped),
                          "lines": sum(len(row) for row in dumped.values()
                                       if isinstance(row, dict))}
            except Exception:  # noqa: BLE001
                dumped = {"files": 0, "lines": 0}
    else:
        status = "NO_COVERAGE_DATA"
    record = {
        "project": project,
        "status": status,
        "returncode": returncode,
        "timed_out": timed_out,
        "wall_seconds": wall,
        "command": command,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "coverage": dumped,
        "data_sha256": sha256_file(data_file) if data_file.exists() else None,
    }
    write_json(COVERAGE / f"{project}.run.json", record)
    print(f"[coverage] {project}: {status} rc={returncode} "
          f"wall={wall}s files={dumped['files']} lines={dumped['lines']}",
          flush=True)
    return record


# --------------------------------------------------------------------------
# line-coordinate mapping and patching
# --------------------------------------------------------------------------
def build_mapping(n_lines: int, spans: Iterable[Tuple[int, int]]) -> List[int]:
    """physical index (1-based) -> original line number."""
    deleted = set()
    for first, last in spans:
        deleted.update(range(first, last + 1))
    mapping: List[int] = []
    for line in range(1, n_lines + 1):
        if line not in deleted:
            mapping.append(line)
        elif line - 1 not in deleted:
            mapping.append(line)
    return mapping


def to_physical(value: int, mapping: Sequence[int]) -> Optional[int]:
    for index, original in enumerate(mapping, start=1):
        if original == value:
            return index
    return None


def to_original(physical: int, mapping: Sequence[int]) -> Optional[int]:
    if 1 <= physical <= len(mapping):
        return mapping[physical - 1]
    return None


def apply_deletions(work: Path, rel_file: str,
                    spans: Sequence[Tuple[int, int]]) -> Dict[str, str]:
    """Delete statement spans, returning original file text for restoration."""
    path = work / rel_file
    original = path.read_text(encoding="utf-8")
    lines = original.splitlines(keepends=True)
    for first, last in sorted(spans, key=lambda s: (s[0], s[1]), reverse=True):
        indent = lines[first - 1][: len(lines[first - 1])
                                  - len(lines[first - 1].lstrip())]
        lines[first - 1:last] = [indent + "pass  # M1 disabled\n"]
    path.write_text("".join(lines), encoding="utf-8")
    return {rel_file: original}


def restore(work: Path, originals: Dict[str, str]) -> None:
    for rel_file, text in originals.items():
        (work / rel_file).write_text(text, encoding="utf-8")


def source_rel_file(project: str, file: str) -> str:
    """Candidate file (relative to package root) -> project-relative path."""
    root = project_root(project, releases())
    return (package_dir(project).relative_to(root) / file).as_posix()


def test_nodeids_from_coverage(project: str, target: Dict[str, Any]) -> List[str]:
    path = COVERAGE / f"{project}.json"
    if not path.exists():
        return []
    data = load_json(path)
    abs_path = str((package_dir(project) / target["file"]).resolve())
    # coverage was measured inside the work copy; paths are work paths.
    work_path = str((WORK / project /
                      source_rel_file(project, target["file"])).resolve())
    rows = data.get(work_path) or data.get(abs_path) or {}
    tests = rows.get(str(target["a_first"]), [])
    return sorted(set(tests))


# --------------------------------------------------------------------------
# variant execution
# --------------------------------------------------------------------------
def watch_target(work: Path, target: Dict[str, Any], rel_file: str,
                 spans: Sequence[Tuple[int, int]],
                 original_lines: int) -> Dict[str, Any]:
    mapping = build_mapping(original_lines, spans)
    return {
        "label": target["target_id"],
        "file": str((work / rel_file).resolve()),
        "function": target["function"],
        "firstlineno": to_physical(
            target["function_code_firstlineno"], mapping),
        "a_line": to_physical(target["a_first"], mapping),
        "a_end": to_physical(target["a_last"], mapping),
        "func_end": to_physical(target["function_end"], mapping),
        "var": target["a_var"],
    }


def run_variant(project: str, target: Dict[str, Any],
                disabled: Iterable[Dict[str, Any]], delete_a: bool,
                nodeids: List[str], tag: str) -> Dict[str, Any]:
    work = WORK / project
    rel_file = source_rel_file(project, target["file"])
    spans = [(int(op["first_line"]), int(op["last_line"]))
             for op in disabled]
    if delete_a:
        spans.append((int(target["a_first"]), int(target["a_last"])))
    # deduplicate and drop spans contained in another span
    spans = sorted(set(spans))
    kept: List[Tuple[int, int]] = []
    for span in spans:
        if any(o[0] <= span[0] and span[1] <= o[1] and o != span
               for o in spans):
            continue
        kept.append(span)
    spans = kept
    originals = apply_deletions(work, rel_file, spans)
    RUNS.mkdir(parents=True, exist_ok=True)
    stem = hashlib.sha1(
        (f"{target['target_id']}|{sorted(op['id'] for op in disabled)}|"
         f"{delete_a}|{tag}").encode()).hexdigest()[:16]
    config_path = RUNS / f"{stem}.config.json"
    out_path = RUNS / f"{stem}.out.json"
    if out_path.exists():
        out_path.unlink()
    try:
        watch = watch_target(work, target, rel_file, spans,
                             len(originals[rel_file].splitlines()))
        write_json(config_path, {"out": str(out_path), "targets": [watch]})
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [str(QUAL), str(source_root(work))])
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONHASHSEED"] = "0"
        env["M1_WATCH_CONFIG"] = str(config_path)
        env.pop("PYTEST_ADDOPTS", None)
        command = [str(venv_python(project)), "-m", "pytest", *nodeids,
                   "-q", "--disable-warnings", "--rootdir", str(work),
                   "-p", "no:cacheprovider",
                   "-p", "m1_watch_plugin"]
        started = time.perf_counter()
        timed_out_flag = False
        try:
            completed = subprocess.run(
                command, cwd=str(work), env=env, capture_output=True,
                text=True, encoding="utf-8", errors="replace", timeout=60)
            returncode = completed.returncode
            stdout_tail = completed.stdout.strip().splitlines()[-15:]
            stderr_tail = completed.stderr.strip().splitlines()[-10:]
        except subprocess.TimeoutExpired:
            returncode, stdout_tail, stderr_tail = None, [], ["timeout"]
            timed_out_flag = True
        wall = round(time.perf_counter() - started, 2)
        payload = load_json(out_path) if out_path.exists() else None
    finally:
        restore(work, originals)
    return {
        "returncode": returncode,
        "wall_seconds": wall,
        "stdout_tail": stdout_tail,
        "stderr_tail": stderr_tail,
        "watch": payload,
        "timed_out": timed_out_flag,
        "known": bool(payload is not None and not timed_out_flag),
    }


def observation(run: Dict[str, Any], nodeids: List[str],
                mapping: Sequence[int]) -> Dict[str, Any]:
    payload = run.get("watch") or {}
    records = payload.get("records", {})
    outcomes = {}
    values: Dict[str, Dict[str, List[str]]] = {}
    hits: Dict[str, int] = {}
    returns: Dict[str, List[str]] = {}
    truncated = False
    for nodeid in nodeids:
        record = records.get(nodeid, {})
        outcomes[nodeid] = record.get("outcome") or "missing"
        hits[nodeid] = sum(record.get("hits", {}).values())
        truncated = truncated or bool(record.get("truncated"))
        per_line: Dict[str, List[str]] = {}
        for physical, vals in record.get("values_by_line", {}).items():
            original = to_original(int(physical), mapping)
            if original is not None:
                per_line.setdefault(str(original), []).extend(vals)
        values[nodeid] = per_line
        returns[nodeid] = list(record.get("return_values", []))
    return {
        "known": payload is not None,
        "exitstatus": payload.get("exitstatus"),
        "returncode": run.get("returncode"),
        "outcomes": outcomes,
        "values": values,
        "hits": hits,
        "return_values": returns,
        "truncated": truncated,
        "wall_seconds": run.get("wall_seconds"),
    }


def passed(obs: Dict[str, Any], nodeids: List[str]) -> bool:
    return all(obs["outcomes"].get(n) == "passed" for n in nodeids)


def canonical_obs(obs: Dict[str, Any]) -> str:
    payload = {
        "outcomes": obs["outcomes"],
        "values": obs["values"],
        "return_values": obs["return_values"],
        "truncated": obs["truncated"],
    }
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True).encode()).hexdigest()


# --------------------------------------------------------------------------
# stage: select original tests by P+ coverage only
# --------------------------------------------------------------------------
def stage_select() -> Dict[str, Any]:
    targets = load_json(SCREEN / "targets.json")["targets"]
    rel = releases()
    rows = []
    for target in targets:
        if not target["eligible"]:
            continue
        tests = test_nodeids_from_coverage(target["project"], target)
        if not tests:
            rows.append({"target_id": target["target_id"],
                         "candidate_id": target["candidate_id"],
                         "project": target["project"],
                         "status": "UNCOVERED", "tests": []})
            continue
        rows.append({
            "target_id": target["target_id"],
            "candidate_id": target["candidate_id"],
            "project": target["project"],
            "status": "SELECTED",
            "tests": tests[:3],
            "tests_available": len(tests),
        })
    write_json(SCREEN / "selected.json", {
        "stage": "m1_original_test_selection",
        "rule": ("Tests are the original upstream tests whose coverage "
                 "context executed A. At most three, lexicographic order. "
                 "No P- outcome is consulted."),
        "counts": {
            "targets": len(rows),
            "selected": sum(1 for r in rows if r["status"] == "SELECTED"),
            "uncovered": sum(1 for r in rows if r["status"] == "UNCOVERED"),
            "by_project": {
                p: {"selected": sum(1 for r in rows if r["project"] == p and
                                    r["status"] == "SELECTED"),
                    "uncovered": sum(1 for r in rows if r["project"] == p and
                                     r["status"] == "UNCOVERED")}
                for p in rel},
        },
        "rows": rows,
    })
    print(json.dumps({
        "selected": sum(1 for r in rows if r["status"] == "SELECTED"),
        "uncovered": sum(1 for r in rows if r["status"] == "UNCOVERED"),
    }, indent=2))
    return {"rows": rows}


# --------------------------------------------------------------------------
# stage: full-program P- prefilter
# --------------------------------------------------------------------------
def load_targets_by_id() -> Dict[str, Dict[str, Any]]:
    return {t["target_id"]: t for t in
            load_json(SCREEN / "targets.json")["targets"]}


def span_mapping_for(target: Dict[str, Any], project: str,
                     disabled: Sequence[Dict[str, Any]],
                     delete_a: bool) -> List[int]:
    spans = [(int(op["first_line"]), int(op["last_line"])) for op in disabled]
    if delete_a:
        spans.append((int(target["a_first"]), int(target["a_last"])))
    text = (WORK / project /
            source_rel_file(project, target["file"])).read_text(encoding="utf-8")
    return build_mapping(len(text.splitlines()), spans)


def stage_probe(projects: Optional[List[str]] = None) -> Dict[str, Any]:
    selected = load_json(SCREEN / "selected.json")["rows"]
    targets = load_targets_by_id()
    probe_path = SCREEN / "probe.json"
    old = load_json(probe_path) if probe_path.exists() else {"rows": {}}
    rows: Dict[str, Any] = dict(old.get("rows", {}))
    budgets = old.get("budgets", {"targeted_pm_runs": 0,
                                  "plus_runs": 0, "wall_seconds": 0.0})
    order = load_json(OUT / "static_candidates.json")["review_order"]
    rank = {cid: i for i, cid in enumerate(order)}
    work = [row for row in selected if row["status"] == "SELECTED"]
    if projects:
        work = [row for row in work if row["project"] in projects]
    work.sort(key=lambda row: (rank[row["candidate_id"]], row["target_id"]))
    for row in work:
        tid = row["target_id"]
        if tid in rows and rows[tid].get("status") not in ("ERROR",):
            continue
        if budgets["targeted_pm_runs"] >= TARGETED_PM_BUDGET:
            rows[tid] = {"target_id": tid, "project": row["project"],
                         "status": "UNPROCESSED_TARGETED_BUDGET"}
            continue
        target = targets[tid]
        project = target["project"]
        nodeids = row["tests"]
        plus = run_variant(project, target, [], False, nodeids, "probe_plus")
        budgets["plus_runs"] += 1
        budgets["wall_seconds"] += plus.get("wall_seconds") or 0
        mapping_plus = span_mapping_for(target, project, [], False)
        obs_plus = observation(plus, nodeids, mapping_plus)
        passing = [n for n in nodeids
                   if obs_plus["outcomes"].get(n) == "passed"]
        record: Dict[str, Any] = {
            "target_id": tid,
            "candidate_id": target["candidate_id"],
            "project": project,
            "tests_selected": nodeids,
            "tests_passing_plus": passing,
            "plus": obs_plus,
            "plus_run": {k: plus[k] for k in
                         ("returncode", "wall_seconds", "stdout_tail",
                          "stderr_tail")},
        }
        if not obs_plus["known"]:
            record["status"] = "UNKNOWN_PLUS_RUN"
            rows[tid] = record
            write_json(probe_path, {"stage": "m1_full_program_probe",
                                    "rows": rows, "budgets": budgets})
            continue
        if not passing:
            record["status"] = "NO_PASSING_TEST"
            rows[tid] = record
            write_json(probe_path, {"stage": "m1_full_program_probe",
                                    "rows": rows, "budgets": budgets})
            continue
        minus = run_variant(project, target, [], True, passing, "probe_minus")
        budgets["targeted_pm_runs"] += 1
        budgets["wall_seconds"] += minus.get("wall_seconds") or 0
        mapping_minus = span_mapping_for(target, project, [], True)
        obs_minus = observation(minus, passing, mapping_minus)
        record["minus"] = obs_minus
        record["minus_run"] = {k: minus[k] for k in
                               ("returncode", "wall_seconds", "stdout_tail",
                                "stderr_tail")}
        record["a_executes"] = sum(obs_plus["hits"].values()) > 0
        if not obs_minus["known"]:
            record["status"] = "UNKNOWN_MINUS_RUN"
            record["local_effect"] = None
        elif not record["a_executes"]:
            record["status"] = "NO_EXECUTION"
        elif not passed(obs_minus, passing):
            record["status"] = "EXPOSED"
            record["local_effect"] = None
        else:
            # first original line after A that both variants observed
            common = sorted(
                set().union(*[set(v) for v in obs_plus["values"].values()])
                & set().union(*[set(v) for v in obs_minus["values"].values()]),
                key=int)
            common = [line for line in common
                      if int(line) > int(target["a_last"])]
            effect = None
            effect_line = common[0] if common else None
            if effect_line is not None:
                effect = any(obs_plus["values"][n].get(effect_line, []) !=
                             obs_minus["values"][n].get(effect_line, [])
                             for n in passing)
            else:
                effect = any(obs_plus["return_values"][n] !=
                             obs_minus["return_values"][n] for n in passing)
            record["local_effect"] = bool(effect)
            record["effect_line"] = effect_line
            record["status"] = ("MASKED_FULL" if effect else
                                "NO_LOCAL_EFFECT")
        rows[tid] = record
        write_json(probe_path, {"stage": "m1_full_program_probe",
                                "rows": rows, "budgets": budgets})
        print(f"[probe] {tid}: {record['status']}", flush=True)
    write_json(probe_path, {"stage": "m1_full_program_probe",
                            "rows": rows, "budgets": budgets,
                            "budget_limits": {
                                "targeted_pm_runs": TARGETED_PM_BUDGET,
                                "plus_runs": None}})
    summary: Dict[str, int] = {}
    for record in rows.values():
        summary[record["status"]] = summary.get(record["status"], 0) + 1
    print(json.dumps({"budgets": budgets, "statuses": summary}, indent=2))
    return {"rows": rows, "budgets": budgets}


# --------------------------------------------------------------------------
# stage: subset matrix for full-program masked candidates
# --------------------------------------------------------------------------
def _powerset(items: Sequence[str], minimum: int = 1) -> Iterable[Tuple[str, ...]]:
    for size in range(minimum, len(items) + 1):
        yield from itertools.combinations(items, size)


def stage_matrix(projects: Optional[List[str]] = None) -> Dict[str, Any]:
    probe = load_json(SCREEN / "probe.json")
    targets = load_targets_by_id()
    path = SCREEN / "matrix.json"
    old = load_json(path) if path.exists() else {"targets": {},
                                                 "budget": {"executions": 0}}
    rows: Dict[str, Any] = old.get("targets", {})
    budget = old.get("budget", {})
    budget.setdefault("executions", 0)
    budget.setdefault("wall_seconds", 0.0)
    budget.setdefault("stage_wall_seconds", 0.0)
    stage_started = time.perf_counter()
    order = load_json(OUT / "static_candidates.json")["review_order"]
    rank = {cid: i for i, cid in enumerate(order)}
    masked_full = [(tid, row) for tid, row in probe["rows"].items()
                   if row.get("status") == "MASKED_FULL"
                   and (not projects or row["project"] in projects)]
    legacy_candidates = sorted(tid for tid, row in masked_full
                               if not ((row.get("plus") or {}).get("known")
                                       and (row.get("minus") or {})
                                       .get("known")))
    survivors = masked_full
    survivors.sort(key=lambda pair: (
        rank[targets[pair[0]]["candidate_id"]], pair[0]))
    for tid, prow in survivors:
        if tid in rows and (rows[tid].get("complete")
                            or rows[tid].get("status") == "EVIDENCE_LOST"):
            continue
        target = targets[tid]
        project = target["project"]
        ops = {op["id"]: op for op in target["u"]}
        ids = sorted(ops)
        nodeids = prow["tests_passing_plus"]
        if len(ids) > MAX_U:
            rows[tid] = {"target_id": tid, "project": project,
                         "status": "STRUCTURAL_SKIP",
                         "u_size": len(ids), "complete": False}
            continue
        base_plus = prow["plus"]
        base_minus = prow["minus"]
        base_rerun = False
        # Legacy probe rows carry no tri-state flag.  Re-run only the base
        # D=empty pair here so the cached evidence has a known status; the
        # legacy probe row itself stays LEGACY_NO_TRI_STATE in probe.json.
        if not (base_plus.get("known") and base_minus.get("known")):
            if (budget["executions"] + 2 > MATRIX_EXEC_BUDGET
                    or time.perf_counter() - stage_started
                    >= MATRIX_WALL_BUDGET):
                rows[tid] = {"target_id": tid, "project": project,
                             "status": "INCOMPLETE_SUBSET_VERIFICATION",
                             "complete": False,
                             "reason": "budget exhausted before base re-run"}
                write_json(path, {"stage": "m1_subset_matrix",
                                  "targets": rows, "budget": budget,
                                  "budget_limit": MATRIX_EXEC_BUDGET,
                                  "wall_budget": MATRIX_WALL_BUDGET,
                                  "legacy_candidates": legacy_candidates})
                break
            plus0 = run_variant(project, target, [], False, nodeids,
                                "matrix_base_plus")
            budget["executions"] += 1
            budget["wall_seconds"] = round(
                budget["wall_seconds"] + (plus0.get("wall_seconds") or 0), 2)
            obs0 = observation(plus0, nodeids,
                               span_mapping_for(target, project, [], False))
            if not obs0["known"]:
                rows[tid] = {"target_id": tid, "project": project,
                             "status": "BASE_EVIDENCE_UNKNOWN",
                             "complete": False,
                             "reason": "legacy base plus run unknown"}
                continue
            passing = [n for n in nodeids
                       if obs0["outcomes"].get(n) == "passed"]
            if not passing:
                rows[tid] = {"target_id": tid, "project": project,
                             "status": "NO_PASSING_TEST",
                             "complete": False,
                             "reason": "legacy base re-run: no passing test"}
                continue
            minus0 = run_variant(project, target, [], True, passing,
                                 "matrix_base_minus")
            budget["executions"] += 1
            budget["wall_seconds"] = round(
                budget["wall_seconds"] + (minus0.get("wall_seconds") or 0), 2)
            obs0m = observation(minus0, passing,
                                span_mapping_for(target, project, [], True))
            if not obs0m["known"]:
                rows[tid] = {"target_id": tid, "project": project,
                             "status": "BASE_EVIDENCE_UNKNOWN",
                             "complete": False,
                             "reason": "legacy base minus run unknown"}
                continue
            if not passed(obs0m, passing):
                rows[tid] = {"target_id": tid, "project": project,
                             "status": "BASE_NOT_MASKED",
                             "complete": False,
                             "reason": "legacy base re-run exposed A"}
                continue
            nodeids = passing
            base_plus, base_minus = obs0, obs0m
            base_rerun = True
        evaluations: Dict[str, Any] = {}
        evaluations[""] = {
            "disabled": [],
            "status": "OK",
            "plus_pass": True,
            "minus_pass": True,
            "masked": True,
            "exposed": False,
            "plus_hash": canonical_obs(base_plus),
            "minus_hash": canonical_obs(base_minus),
            "outcomes_plus": base_plus["outcomes"],
            "outcomes_minus": base_minus["outcomes"],
            "cached_from_probe": not base_rerun,
            "base_rerun": base_rerun,
        }
        complete = True
        for disabled in _powerset(ids):
            budget["stage_wall_seconds"] = round(
                time.perf_counter() - stage_started, 1)
            if (budget["executions"] >= MATRIX_EXEC_BUDGET
                    or budget["stage_wall_seconds"] >= MATRIX_WALL_BUDGET):
                complete = False
                break
            key = "+".join(disabled)
            disabled_ops = [ops[name] for name in disabled]
            plus = run_variant(project, target, disabled_ops, False,
                               nodeids, "matrix_plus")
            budget["executions"] += 1
            budget["wall_seconds"] = round(
                budget["wall_seconds"] + (plus.get("wall_seconds") or 0), 2)
            mapping_plus = span_mapping_for(target, project, disabled_ops,
                                            False)
            obs_plus = observation(plus, nodeids, mapping_plus)
            if not obs_plus["known"]:
                evaluations[key] = {
                    "disabled": list(disabled), "status": "UNKNOWN",
                    "plus_pass": None, "minus_pass": None,
                    "masked": None, "exposed": None,
                    "plus_hash": canonical_obs(obs_plus),
                    "outcomes_plus": obs_plus["outcomes"],
                    "outcomes_minus": None, "reason": "plus run unknown",
                }
                continue
            plus_ok = passed(obs_plus, nodeids)
            if not plus_ok:
                evaluations[key] = {
                    "disabled": list(disabled), "status": "INVALID",
                    "plus_pass": False,
                    "minus_pass": None,
                    "masked": False,
                    "exposed": False,
                    "plus_hash": canonical_obs(obs_plus),
                    "outcomes_plus": obs_plus["outcomes"],
                    "outcomes_minus": None,
                }
                continue
            minus = run_variant(project, target, disabled_ops, True,
                                nodeids, "matrix_minus")
            budget["executions"] += 1
            budget["wall_seconds"] = round(
                budget["wall_seconds"] + (minus.get("wall_seconds") or 0), 2)
            mapping_minus = span_mapping_for(target, project, disabled_ops,
                                             True)
            obs_minus = observation(minus, nodeids, mapping_minus)
            if not obs_minus["known"]:
                evaluations[key] = {
                    "disabled": list(disabled), "status": "UNKNOWN",
                    "plus_pass": True, "minus_pass": None,
                    "masked": None, "exposed": None,
                    "plus_hash": canonical_obs(obs_plus),
                    "outcomes_plus": obs_plus["outcomes"],
                    "outcomes_minus": obs_minus["outcomes"],
                    "reason": "minus run unknown",
                }
                continue
            minus_ok = passed(obs_minus, nodeids)
            evaluations[key] = {
                "disabled": list(disabled), "status": "OK",
                "plus_pass": True,
                "minus_pass": minus_ok,
                "masked": minus_ok,
                "exposed": not minus_ok,
                "plus_hash": canonical_obs(obs_plus),
                "minus_hash": canonical_obs(obs_minus),
                "outcomes_plus": obs_plus["outcomes"],
                "outcomes_minus": obs_minus["outcomes"],
            }
        record: Dict[str, Any] = {
            "target_id": tid,
            "candidate_id": target["candidate_id"],
            "project": project,
            "u_size": len(ids),
            "universe": [ops[name] for name in ids],
            "tests": nodeids,
            "evaluations": evaluations,
            "complete": complete,
            "budget_exhausted": not complete,
        }
        if not complete:
            record["status"] = "INCOMPLETE_SUBSET_VERIFICATION"
            rows[tid] = record
            write_json(path, {"stage": "m1_subset_matrix", "targets": rows,
                              "budget": budget,
                              "budget_limit": MATRIX_EXEC_BUDGET,
                              "wall_budget": MATRIX_WALL_BUDGET,
                              "legacy_candidates": legacy_candidates})
            break
        # Tri-state evidence: True / False / None (None = UNKNOWN).  UNKNOWN is
        # never coerced to False and never allowed to justify minimality.
        masked = {frozenset(row["disabled"]): row["masked"]
                  for row in evaluations.values()}
        exposed = {frozenset(row["disabled"]): row["exposed"]
                   for row in evaluations.values()}
        all_ids = frozenset(ids)
        minimal_multi: List[List[str]] = []
        minimal_single: List[List[str]] = []
        unknown_blocked_sets: List[Dict[str, Any]] = []

        # A kept set S is minimal-masked iff masked(U\S) is True and every
        # non-empty proper T has masked(U\T) known-False (frozen MSMS rule).
        for size in range(1, len(ids) + 1):
            for kept in itertools.combinations(ids, size):
                S = frozenset(kept)
                if masked.get(all_ids - S) is not True:
                    continue
                proper = [all_ids - frozenset(T)
                          for T in _powerset(kept)
                          if len(T) < size]
                values = [masked.get(d) for d in proper]
                if any(v is True for v in values):
                    continue
                unknown = [sorted(d) for d, v in zip(proper, values)
                           if v is None]
                if unknown:
                    unknown_blocked_sets.append({
                        "evidence": "masked", "members": list(kept),
                        "unknown_disabled_sets": unknown})
                    continue
                (minimal_multi if size >= 2 else minimal_single).append(
                    list(kept))

        # A disabled set D is minimal-exposing iff exposed(D) is True and every
        # proper D' subset has exposed(D') known-False.
        minimal_mmbs: List[List[str]] = []
        for size in range(1, len(ids) + 1):
            for disabled in itertools.combinations(ids, size):
                if exposed.get(frozenset(disabled)) is not True:
                    continue
                proper = [frozenset(T)
                          for T in _powerset(disabled, minimum=0)
                          if len(T) < size]
                values = [exposed.get(d) for d in proper]
                if any(v is True for v in values):
                    continue
                unknown = [sorted(d) for d, v in zip(proper, values)
                           if v is None]
                if unknown:
                    unknown_blocked_sets.append({
                        "evidence": "exposed",
                        "members": list(disabled),
                        "unknown_disabled_sets": unknown})
                    continue
                minimal_mmbs.append(list(disabled))

        for kept in minimal_multi:
            kept.sort()
        minimal_multi.sort(key=lambda kept: (len(kept), kept))
        base_out_plus = evaluations[""]["outcomes_plus"]
        base_out_minus = evaluations[""]["outcomes_minus"]
        inert: Dict[str, Dict[str, Any]] = {}
        for name in ids:
            ev = evaluations.get(name)
            if not ev or ev.get("status") != "OK":
                inert[name] = {"known": False}
                continue
            inert[name] = {
                "known": True,
                "single_inert_outcomes": bool(
                    ev["plus_pass"] and ev["minus_pass"] and
                    ev["outcomes_plus"] == base_out_plus and
                    ev["outcomes_minus"] == base_out_minus),
                "single_inert_full": bool(
                    ev["plus_pass"] and ev["minus_pass"] and
                    ev["plus_hash"] == evaluations[""]["plus_hash"] and
                    ev["minus_hash"] == evaluations[""]["minus_hash"]),
            }
        qualified_sets = [kept for kept in minimal_multi
                          if any(inert.get(name, {})
                                 .get("single_inert_outcomes", False)
                                 for name in kept)]
        record.update({
            "minimal_multi_sets": minimal_multi,
            "minimal_single_sets": minimal_single,
            "minimal_mmbs": minimal_mmbs,
            "unknown_blocked_sets": unknown_blocked_sets,
            "inert_members": inert,
            "qualified_sets": qualified_sets,
            "evidence_tri_state": True,
        })
        if qualified_sets:
            record["status"] = "CONFIRMED_M1_PENDING_FULL_SUITE"
            record["selected_set"] = qualified_sets[0]
        elif minimal_multi:
            record["status"] = "NOT_M1_NO_INERT_MEMBER"
        elif minimal_single:
            record["status"] = "SINGLE_OP_ONLY"
        elif unknown_blocked_sets or any(v.get("known") is False
                                         for v in inert.values()):
            record["status"] = "UNKNOWN_EVIDENCE_BLOCKED"
        else:
            record["status"] = "NO_MULTI_OP_MASK"
        rows[tid] = record
        write_json(path, {"stage": "m1_subset_matrix", "targets": rows,
                          "budget": budget,
                          "budget_limit": MATRIX_EXEC_BUDGET,
                          "wall_budget": MATRIX_WALL_BUDGET,
                          "legacy_candidates": legacy_candidates})
        print(f"[matrix] {tid}: {record['status']} "
              f"multi={len(minimal_multi)} single={len(minimal_single)}",
              flush=True)
    write_json(path, {"stage": "m1_subset_matrix", "targets": rows,
                      "budget": budget, "budget_limit": MATRIX_EXEC_BUDGET,
                      "wall_budget": MATRIX_WALL_BUDGET,
                      "legacy_candidates": legacy_candidates})
    summary: Dict[str, int] = {}
    for record in rows.values():
        summary[record["status"]] = summary.get(record["status"], 0) + 1
    print(json.dumps({"budget": budget, "statuses": summary}, indent=2))
    return {"targets": rows, "budget": budget}


# --------------------------------------------------------------------------
# stage: independent acceptance, full original suite
# --------------------------------------------------------------------------
FAIL_PREFIXES = ("FAILED ", "ERROR ")


def run_full_suite(project: str, delete_a: bool,
                   target: Dict[str, Any]) -> Dict[str, Any]:
    rel = releases()
    work = WORK / project
    tests = tests_dir(project_root(project, rel))
    rel_file = source_rel_file(project, target["file"])
    spans = [(int(target["a_first"]), int(target["a_last"]))] if delete_a \
        else []
    originals = apply_deletions(work, rel_file, spans)
    env = os.environ.copy()
    env["PYTHONPATH"] = str(source_root(work))
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env.pop("PYTEST_ADDOPTS", None)
    command = [str(venv_python(project)), "-m", "pytest", tests, "-q",
               "--tb=no", "-rf", "--disable-warnings", "--rootdir", str(work),
               "-p", "no:cacheprovider"]
    started = time.perf_counter()
    try:
        completed = subprocess.run(
            command, cwd=str(work), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=7200)
        returncode = completed.returncode
        lines = completed.stdout.splitlines()
        timed_out = False
    except subprocess.TimeoutExpired:
        returncode, lines, timed_out = None, [], True
    finally:
        restore(work, originals)
    failures = sorted({line.split(" ", 1)[1].strip()
                       for line in lines
                       if line.startswith(FAIL_PREFIXES)})
    tail = lines[-40:]
    return {
        "delete_a": delete_a,
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "wall_seconds": round(time.perf_counter() - started, 2),
        "failure_count": len(failures),
        "failures": failures,
        "stdout_tail": tail,
    }


def stage_finalize(projects: Optional[List[str]] = None) -> Dict[str, Any]:
    matrix = load_json(SCREEN / "matrix.json")
    targets = load_targets_by_id()
    path = SCREEN / "cases.json"
    old = load_json(path) if path.exists() else {
        "cases": {}, "budget": {"full_suite_pm_runs": 0}}
    cases: Dict[str, Any] = old.get("cases", {})
    budget = old.get("budget", {"full_suite_pm_runs": 0,
                                "wall_seconds": 0.0})
    pending = [(tid, row) for tid, row in matrix["targets"].items()
               if row.get("status") == "CONFIRMED_M1_PENDING_FULL_SUITE"
               and (not projects or row["project"] in projects)]
    for tid, row in pending:
        if tid in cases and cases[tid].get("final_status"):
            continue
        if budget["full_suite_pm_runs"] >= FULL_SUITE_PM_BUDGET:
            cases[tid] = {**row,
                          "final_status": "UNPROCESSED_FULL_SUITE_BUDGET"}
            continue
        target = targets[tid]
        project = target["project"]
        plus = run_full_suite(project, False, target)
        budget["wall_seconds"] = round(
            budget["wall_seconds"] + plus["wall_seconds"], 2)
        minus = run_full_suite(project, True, target)
        budget["full_suite_pm_runs"] += 1
        budget["wall_seconds"] = round(
            budget["wall_seconds"] + minus["wall_seconds"], 2)
        new_failures = sorted(set(minus["failures"]) - set(plus["failures"]))
        passed_full = (minus["returncode"] is not None
                       and not minus["timed_out"] and not new_failures)
        case = dict(row)
        case.update({
            "project": project,
            "version": releases()[project]["version"],
            "sdist_sha256": releases()[project]["sha256"],
            "target_a": {
                "file": target["file"],
                "function": target["function"],
                "first_line": target["a_first"],
                "last_line": target["a_last"],
                "code": target["a_code"],
                "variables": target["a_lhs"],
            },
            "universe": target["u"],
            "full_suite": {
                "plus": plus,
                "minus": minus,
                "new_failures_from_deleting_a": new_failures,
            },
            "original_tests_missed_deletion": passed_full,
            "final_status": ("CONFIRMED_M1" if passed_full
                             else "DETECTED_BY_FULL_SUITE"),
        })
        cases[tid] = case
        write_json(path, {"stage": "m1_independent_acceptance",
                          "cases": cases, "budget": budget})
        print(f"[finalize] {tid}: {case['final_status']} "
              f"new_failures={len(new_failures)}", flush=True)
    write_json(path, {"stage": "m1_independent_acceptance",
                      "cases": cases, "budget": budget})
    summary: Dict[str, int] = {}
    for case in cases.values():
        summary[case["final_status"]] = summary.get(
            case["final_status"], 0) + 1
    print(json.dumps({"budget": budget, "statuses": summary}, indent=2))
    return {"cases": cases, "budget": budget}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("plan")
    cov = sub.add_parser("coverage")
    cov.add_argument("--projects", nargs="*", default=None)
    sub.add_parser("select")
    probe = sub.add_parser("probe")
    probe.add_argument("--projects", nargs="*", default=None)
    matrix = sub.add_parser("matrix")
    matrix.add_argument("--projects", nargs="*", default=None)
    finalize = sub.add_parser("finalize")
    finalize.add_argument("--projects", nargs="*", default=None)
    sub.add_parser("status")
    args = parser.parse_args()
    if args.command == "plan":
        build_targets()
        coverage_targets()
    elif args.command == "coverage":
        rel = releases()
        names = args.projects or [p for p in rel
                                  if tests_dir(project_root(p, rel))]
        for name in names:
            run_coverage(name)
    elif args.command == "select":
        stage_select()
    elif args.command == "probe":
        stage_probe(args.projects)
    elif args.command == "matrix":
        stage_matrix(args.projects)
    elif args.command == "finalize":
        stage_finalize(args.projects)
    elif args.command == "status":
        def counts(name: str, key: str) -> Dict[str, int]:
            path = SCREEN / name
            if not path.exists():
                return {}
            payload = load_json(path)
            rows = payload.get(key, payload)
            out: Dict[str, int] = {}
            for row in rows.values() if isinstance(rows, dict) else rows:
                status = row.get("status") or row.get("final_status")
                out[status] = out.get(status, 0) + 1
            return out
        print(json.dumps({
            "targets": load_json(SCREEN / "targets.json")["counts"]
            if (SCREEN / "targets.json").exists() else {},
            "selected": counts("selected.json", "rows"),
            "probe": counts("probe.json", "rows"),
            "matrix": counts("matrix.json", "targets"),
            "cases": counts("cases.json", "cases"),
        }, ensure_ascii=False, indent=2))
