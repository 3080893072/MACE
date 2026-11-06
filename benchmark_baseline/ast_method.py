"""Deterministic AST + execution-intervention baseline (zero model calls).

Method
------
1. Read only the public task bundle (task.json, source tree, contract).
2. Parse the public source file and collect every assignment to the same
   *local variable name* as target A, in any function of that file.
3. Run a public-API observation probe on a small, contract-derived input pool
   while tracing executed lines.  Only candidates that actually execute on an
   input are considered for that input.
4. Build executable P+/P- variants with the target and candidate operations
   deleted, and enumerate deleted subsets.  Masking = both sides execute and
   observations are equal; exposing = both execute and observations differ.
5. Submit exposing witnesses and the enumerated minimal sufficient / minimal
   breaking sets.

No model is called.  Hidden references, story labels and witness files are
not read here.  The input pool is authored from the published contract and
source semantics only.
"""
from __future__ import annotations

import ast
import hashlib
import itertools
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from benchmark_baseline.prompts import PUBLIC, public_source, public_task
from benchmark_real_v3.config import KIT, PROJECTS
from benchmark_real_v3.variant_lab import build_variant, run_probe

PROBES = KIT / "benchmark_real_v3" / "probes"
TRACE = Path(__file__).with_name("trace_lines.py")
MAX_INPUTS = 12
MAX_SUBSET_CANDIDATES = 5
MAX_CLAIMS = 8

PROBE_BY_TASK = {
    "jinja2_bytecode_cache_read": "probe_jinja_bytecode_cache.py",
    "werkzeug_bind_server_name_lower": "probe_werkzeug_bind_server_name.py",
    "werkzeug_filestorage_stream_name": "probe_werkzeug_filestorage.py",
    "werkzeug_get_host_default_empty": "probe_werkzeug_get_host.py",
    "werkzeug_secure_filename_ascii_filter": "probe_werkzeug_secure_filename.py",
}


def input_pool(task_id: str) -> List[Dict[str, Any]]:
    """Contract-derived legal inputs, authored without any hidden witness."""
    if task_id == "jinja2_bytecode_cache_read":
        return [
            {"template": "{{ 6*7 }}"},
            {"template": "{{ 6*7 }}", "cached_source": "{{ 1+1 }}"},
            {"template": "Hello {{ name }}", "context": {"name": "World"}},
            {"template": "{% for i in range(3) %}{{ i }}{% endfor %}"},
            {"template": "{{ 6*7 }}", "cached_source": "Hello"},
        ]
    if task_id == "werkzeug_bind_server_name_lower":
        rows = []
        for host in ("example.com", "Example.COM"):
            for server_name in (None, "EXAMPLE.COM", "Example.COM"):
                for subdomain in (None, "www"):
                    rows.append({"host": host, "server_name": server_name,
                                 "subdomain": subdomain})
        return rows[:MAX_INPUTS]
    if task_id == "werkzeug_filestorage_stream_name":
        return [
            {"stream": "stderr"},
            {"stream": "tempfile"},
            {"stream": "none", "data": "abc"},
            {"stream": "named", "name": "file.txt", "data": "abc"},
            {"stream": "named", "name": "<special>", "data": "abc"},
        ]
    if task_id == "werkzeug_get_host_default_empty":
        return [
            {"host_header": "example.com", "scheme": "http", "server": None},
            {"host_header": None, "scheme": "http",
             "server": ["example.com", 8080]},
            {"host_header": None, "scheme": "http", "server": None},
            {"host_header": "example.com:80", "scheme": "http", "server": None},
            {"host_header": None, "scheme": "https",
             "server": ["example.com", 443]},
            {"host_header": "example.com", "scheme": "http",
             "server": ["other.com", 80]},
        ]
    if task_id == "werkzeug_secure_filename_ascii_filter":
        return [
            {"filename": "北京.txt"},
            {"filename": "a b"},
            {"filename": "i contain cool ümläuts.txt"},
            {"filename": "ümläuts.txt"},
            {"filename": "普通文件.txt"},
            {"filename": "a b"},
            {"filename": "a.b"},
            {"filename": "<stderr>"},
        ]
    raise KeyError(task_id)


def _assignment_name(node: ast.AST) -> str | None:
    targets: Sequence[ast.AST]
    if isinstance(node, ast.Assign):
        targets = node.targets
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = [node.target]
    else:
        return None
    if len(targets) != 1:
        return None
    target = targets[0]
    if isinstance(target, ast.Name):
        return target.id
    return None


def _target_node(tree: ast.Module, line: int) -> ast.AST | None:
    for node in ast.walk(tree):
        if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)) \
                and node.lineno == line:
            return node
    return None


def candidate_operations(task: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Same-name assignments in the public file, excluding A itself."""
    source = (PUBLIC / "tasks" / task["task_id"]
              / task["source_path"]).read_text(encoding="utf-8")
    tree = ast.parse(source)
    target = task["target_operation"]
    node = _target_node(tree, int(target["line"]))
    if node is None:
        return []
    name = _assignment_name(node)
    if name is None:
        return []
    seen = set()
    out = []
    for candidate in ast.walk(tree):
        if not isinstance(candidate, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
            continue
        if _assignment_name(candidate) != name:
            continue
        first = int(candidate.lineno)
        last = int(getattr(candidate, "end_lineno", candidate.lineno) or first)
        if first == int(target["line"]):
            continue
        key = (first, last)
        if key in seen:
            continue
        seen.add(key)
        out.append({"file": target["file"], "line": first,
                    "end_line": last, "variable": name})
    return sorted(out, key=lambda item: (item["line"], item["end_line"]))


def _op_key(op: Dict[str, Any]) -> Tuple[int, int]:
    return (int(op["line"]), int(op["end_line"]))


def _build(project_id: str, task_id: str, side: str,
           deleted: Iterable[Dict[str, Any]], cache: Dict[str, str]) -> Path:
    ops = sorted({_op_key(op) for op in deleted})
    tag = "_".join(f"{first}-{last}" for first, last in ops) or "EMPTY"
    name = f"ast_{task_id}_{side}_{tag}"
    if name in cache:
        return Path(cache[name])
    statements = []
    blocks = []
    for first, last in ops:
        if first == last:
            statements.append((PUBLIC_FILE_CACHE[task_id], first))
        else:
            blocks.append((PUBLIC_FILE_CACHE[task_id], first, last))
    target = public_task(task_id)["target_operation"]
    if side == "minus":
        statements.append((target["file"], int(target["line"])))
    variant = build_variant(
        project_id, name,
        statement_deletions=statements, block_deletions=blocks)
    cache[name] = variant["root"]
    return Path(variant["root"])


PUBLIC_FILE_CACHE: Dict[str, str] = {}


def _observe(project_id: str, root: Path, probe: str,
             payload: Dict[str, Any]) -> Dict[str, Any]:
    result = run_probe(project_id, root, probe, payload)
    observation = result.get("observation")
    ok = (result.get("returncode") == 0 and isinstance(observation, dict))
    return {"ok": ok, "observation": observation,
            "returncode": result.get("returncode")}


def _trace(project_id: str, root: Path, probe: str,
           target_file: str, payload: Dict[str, Any]) -> set:
    cfg = PROJECTS[project_id]
    out = Path(tempfile.mkstemp(prefix="trace_", suffix=".json")[1])
    request = {
        "probe": str(PROBES / probe),
        "target_file": str((root / target_file).resolve()),
        "payload": payload,
        "out": str(out),
    }
    req_path = out.with_suffix(".req.json")
    req_path.write_text(json.dumps(request), encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str((root / cfg["source_dir"]).resolve())
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        subprocess.run(
            [cfg["python"], str(TRACE), str(req_path)],
            cwd=str(root), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180)
        data = json.loads(out.read_text(encoding="utf-8"))
        return set(int(x) for x in data.get("lines", []))
    except Exception:  # noqa: BLE001
        return set()
    finally:
        for path in (out, req_path):
            try:
                path.unlink()
            except OSError:
                pass


def _minimal_sets(cands: List[Dict[str, Any]],
                  masked: Dict[str, bool]) -> List[Tuple[Tuple[int, int], ...]]:
    """MSMS as preserved sets over the executed candidate pool."""
    keys = [_op_key(op) for op in cands]
    out = []
    for size in range(1, len(keys) + 1):
        for kept in itertools.combinations(keys, size):
            rest = tuple(sorted(set(keys) - set(kept)))
            if not masked.get(rest, False):
                continue
            if any(masked.get(tuple(sorted(set(keys) - set(sub))), False)
                   for sub_size in range(1, size)
                   for sub in itertools.combinations(kept, sub_size)):
                continue
            out.append(tuple(sorted(kept)))
    return out


def _minimal_breaking(cands: List[Dict[str, Any]],
                      exposed: Dict[str, bool]) -> List[Tuple[Tuple[int, int], ...]]:
    keys = [_op_key(op) for op in cands]
    out = []
    for size in range(1, len(keys) + 1):
        for deleted in itertools.combinations(keys, size):
            key = tuple(sorted(deleted))
            if not exposed.get(key, False):
                continue
            if any(exposed.get(tuple(sorted(sub)), False)
                   for sub_size in range(0, size)
                   for sub in itertools.combinations(deleted, sub_size)):
                continue
            out.append(key)
    return out


def run_task(task_id: str) -> Dict[str, Any]:
    task = public_task(task_id)
    project_id = task["project_id"]
    probe = PROBE_BY_TASK[task_id]
    PUBLIC_FILE_CACHE[task_id] = task["target_operation"]["file"]
    target = task["target_operation"]
    cands = candidate_operations(task)[:32]
    inputs = input_pool(task_id)[:MAX_INPUTS]
    builds: Dict[str, str] = {}

    plus_base = _build(project_id, task_id, "plus", [], builds)
    minus_base = _build(project_id, task_id, "minus", [], builds)

    evaluated = []
    for payload in inputs:
        plus = _observe(project_id, plus_base, probe, payload)
        minus = _observe(project_id, minus_base, probe, payload)
        lines = _trace(project_id, plus_base, probe, target["file"], payload)
        a_executes = int(target["line"]) in lines
        executed = [op for op in cands if int(op["line"]) in lines]
        if not (plus["ok"] and minus["ok"]):
            kind = "invalid"
        elif plus["observation"] != minus["observation"]:
            kind = "exposing"
        else:
            kind = "masked"
        evaluated.append({
            "input": payload, "kind": kind, "a_executes": a_executes,
            "candidates_executed": executed,
            "plus": plus["observation"], "minus": minus["observation"],
        })

    claims: List[Dict[str, Any]] = []
    for row in evaluated:
        if row["kind"] != "exposing" or not row["a_executes"]:
            continue
        claims.append({"type": "EXPOSING_COUNTEREXAMPLE",
                       "input": row["input"]})
        if sum(1 for c in claims if c["type"] == "EXPOSING_COUNTEREXAMPLE") >= 2:
            break

    minimal_rows = []
    masked_rows = [row for row in evaluated
                   if row["kind"] == "masked" and row["a_executes"]
                   and row["candidates_executed"]]
    for row in masked_rows[:3]:
        if len(row["candidates_executed"]) > MAX_SUBSET_CANDIDATES:
            continue
        cand = row["candidates_executed"]
        keys = [_op_key(op) for op in cand]
        masked: Dict[Tuple[int, int], bool] = {}
        exposed: Dict[Tuple[int, int], bool] = {}
        for size in range(len(keys) + 1):
            for deleted in itertools.combinations(keys, size):
                key = tuple(sorted(deleted))
                plus = _observe(project_id,
                                _build(project_id, task_id, "plus",
                                       [op for op in cand
                                        if _op_key(op) in key], builds),
                                probe, row["input"])
                minus = _observe(project_id,
                                 _build(project_id, task_id, "minus",
                                        [op for op in cand
                                         if _op_key(op) in key], builds),
                                 probe, row["input"])
                if plus["ok"] and minus["ok"]:
                    masked[key] = plus["observation"] == minus["observation"]
                    exposed[key] = plus["observation"] != minus["observation"]
                else:
                    masked[key] = False
                    exposed[key] = False
        msms = _minimal_sets(cand, masked)
        mmbs = _minimal_breaking(cand, exposed)
        minimal_rows.append({
            "input": row["input"],
            "candidates": cand,
            "masked": {"+".join(map(str, k)) or "EMPTY": v
                       for k, v in masked.items()},
            "exposed": {"+".join(map(str, k)) or "EMPTY": v
                        for k, v in exposed.items()},
            "msms": [list(k) for k in msms],
            "mmbs": [list(k) for k in mmbs],
        })
        if msms:
            claims.append({"type": "MSMS", "input": row["input"],
                           "operations": [_op_json(op) for op in cand
                                          if _op_key(op) in msms[0]]})
        if mmbs:
            claims.append({"type": "MMBS", "input": row["input"],
                           "operations": [_op_json(op) for op in cand
                                          if _op_key(op) in mmbs[0]]})
        if len(claims) >= MAX_CLAIMS:
            break

    return {
        "task_id": task_id,
        "method": "deterministic_ast_intervention",
        "target": target,
        "candidate_operations": cands,
        "inputs_evaluated": evaluated,
        "subset_analysis": minimal_rows,
        "variant_builds": len(builds),
        "claims": claims[:MAX_CLAIMS],
        "test_gap": {
            "summary": ("not attempted: this baseline targets operation "
                        "relations, not per-test classification"),
            "tests": [],
        },
    }


def _op_json(op: Dict[str, Any]) -> Dict[str, Any]:
    row = {"file": op["file"], "line": op["line"]}
    if int(op["end_line"]) != int(op["line"]):
        row["end_line"] = op["end_line"]
    return row


def submission_for(task_id: str) -> Dict[str, Any]:
    result = run_task(task_id)
    submission = {
        "submission_id": f"ast-intervention-{task_id}",
        "task_id": task_id,
        "claims": result["claims"],
        "test_gap": result["test_gap"],
    }
    digest = hashlib.sha256(json.dumps(
        submission, ensure_ascii=False, sort_keys=True).encode("utf-8"))
    return {
        "submission": submission,
        "submission_sha256": digest.hexdigest(),
        "work": result,
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m benchmark_baseline.ast_method <task_id>")
        return 2
    payload = submission_for(sys.argv[1])
    print(json.dumps(payload, ensure_ascii=False, indent=2, default=list))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
