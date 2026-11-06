"""Minimal difference-guided masking-candidate discovery (phase 3).

The method is deliberately small and toggleable.  It uses only the public
task bundle, the public probe, and execution traces of the target file.  It
never reads the hidden reference to propose a candidate.

Methods
-------
``downstream_only``
    Control: same-name assignments after A, no trace filter.
``downstream_trace``
    Control: after A, and executed in P+ or P-.
``diff_guided``
    Difference-guided: after A, and either (a) executed only on the P- fallback
    path, or (b) executed on both sides but the target value differs before the
    operation and converges after it (overwrite / absorb).  Candidates are
    validated one at a time; no subset of candidates is enumerated.

Every method submits only single-operation MSMS/MMBS claims that pass the same
execution-intervention check.  Unsupported candidates are reported UNKNOWN,
never silently promoted.
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import subprocess
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Sequence, Tuple

from benchmark_baseline.ast_method import (
    MAX_INPUTS,
    PROBE_BY_TASK,
    PUBLIC_FILE_CACHE,
    _assignment_name,
    _build,
    _observe,
    candidate_operations,
    input_pool,
)
from benchmark_baseline.prompts import public_task
from benchmark_real_v3.config import KIT, PROJECTS

DIFF_TRACE = KIT / "benchmark_baseline" / "diff_trace.py"
OUT_ROOT = KIT / "benchmark_baseline" / "runs" / "diff_guided"
METHODS = ("downstream_only", "downstream_trace", "diff_guided")


def target_variable(task: Dict[str, Any]) -> str:
    """Read the assigned name from the published A statement, nothing else."""
    node = ast.parse(task["target_operation"]["code"]).body[0]
    name = _assignment_name(node)
    if name is None:
        raise SystemExit("target A is not a simple name assignment")
    return name


def _trace(project_id: str, root: Path, probe: str, target_file: str,
           target_var: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    cfg = PROJECTS[project_id]
    out = Path(tempfile.mkstemp(prefix="diff_", suffix=".json")[1])
    request = {
        "probe": str(KIT / "benchmark_real_v3" / "probes" / probe),
        "target_file": str((root / target_file).resolve()),
        "target_var": target_var,
        "payload": payload,
        "out": str(out),
        "max_events": 20000,
    }
    req = out.with_suffix(".req.json")
    req.write_text(json.dumps(request), encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str((root / cfg["source_dir"]).resolve())
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        completed = subprocess.run(
            [cfg["python"], str(DIFF_TRACE), str(req)],
            cwd=str(root), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=120)
        if completed.returncode != 0 or not out.exists():
            return {"events": [], "errors": [
                {"type": "TRACE_FAILED", "message": completed.stderr[-500:]}]}
        return json.loads(out.read_text(encoding="utf-8"))
    except Exception as exc:  # noqa: BLE001
        return {"events": [], "errors": [
            {"type": "TRACE_EXCEPTION", "message": repr(exc)}]}
    finally:
        for path in (out, req):
            try:
                path.unlink()
            except OSError:
                pass


def _first_index(events: Sequence[Dict[str, Any]], line: int) -> int | None:
    for index, event in enumerate(events):
        if event["line"] == line:
            return index
    return None


def _last_index(events: Sequence[Dict[str, Any]], line: int) -> int | None:
    found = None
    for index, event in enumerate(events):
        if event["line"] == line:
            found = index
    return found


def _pre(events: Sequence[Dict[str, Any]], line: int) -> str:
    """State before the candidate executes (line events fire pre-execution)."""
    index = _first_index(events, line)
    if index is None:
        return "NOT_EXECUTED"
    event = events[index]
    if event["bound"] and event["hash"]:
        return event["hash"]
    return "UNBOUND"


def _post(events: Sequence[Dict[str, Any]], line: int) -> str | None:
    index = _last_index(events, line)
    if index is None:
        return None
    func = events[index]["func"]
    for event in events[index + 1:]:
        if event["func"] != func:
            continue
        if event["bound"] and event["hash"]:
            return event["hash"]
        return None
    return None


def _final(events: Sequence[Dict[str, Any]]) -> str | None:
    for event in reversed(events):
        if event["bound"] and event["hash"]:
            return event["hash"]
    return None


def _lines(events: Sequence[Dict[str, Any]]) -> set:
    return {int(event["line"]) for event in events}


def _evidence(candidate: Dict[str, Any], plus: Sequence[Dict[str, Any]],
              minus: Sequence[Dict[str, Any]], a_line: int) -> Dict[str, Any]:
    line = int(candidate["line"])
    p_lines, m_lines = _lines(plus), _lines(minus)
    in_plus = line in p_lines
    in_minus = line in m_lines
    pre_plus, pre_minus = _pre(plus, line), _pre(minus, line)
    post_plus, post_minus = _post(plus, line), _post(minus, line)
    final_plus, final_minus = _final(plus), _final(minus)
    control = in_plus != in_minus
    a_index = _first_index(plus, a_line)
    cand_index = _first_index(plus, line)
    a_func = plus[a_index]["func"] if a_index is not None else None
    after_a_plus = bool(
        a_index is not None and cand_index is not None and cand_index > a_index)
    # A is deleted in P-.  For a P--only fallback, require the same function and
    # a source line after A; this covers the fallback path, not pre-A setup.
    minus_funcs = {event["func"] for event in minus if event["line"] == line}
    after_a_minus = bool(
        not in_plus and line > a_line and a_func is not None
        and a_func in minus_funcs)
    downstream = bool(after_a_plus or after_a_minus)
    absorb = bool(
        in_plus and in_minus
        and pre_plus != "NOT_EXECUTED" and pre_minus != "NOT_EXECUTED"
        and pre_plus != pre_minus
        and post_plus is not None and post_minus is not None
        and post_plus == post_minus
        and final_plus is not None and final_plus == final_minus
    )
    if in_minus and not in_plus:
        score = 4
    elif absorb:
        score = 3
    elif in_plus and not in_minus:
        score = 2
    else:
        score = 1
    return {
        "in_plus": in_plus,
        "in_minus": in_minus,
        "control_divergence": control,
        "pre_plus": pre_plus,
        "pre_minus": pre_minus,
        "post_plus": post_plus,
        "post_minus": post_minus,
        "final_plus": final_plus,
        "final_minus": final_minus,
        "absorb": absorb,
        "score": score,
        "difference_carrying": bool(control or absorb),
        "downstream": downstream,
        "after_a_plus": after_a_plus,
        "after_a_minus": after_a_minus,
    }


def _select(method: str, candidates: List[Dict[str, Any]],
            evidence: Dict[int, Dict[str, Any]], a_line: int) -> List[Dict[str, Any]]:
    selected = []
    for candidate in candidates:
        line = int(candidate["line"])
        item = evidence.get(line, {})
        if method == "downstream_only":
            # Naive static control: source order only, known to miss a mask
            # that is textually earlier but dynamically after A.
            if line > a_line:
                selected.append(candidate)
        elif method == "downstream_trace":
            if item.get("downstream") and (item.get("in_plus") or item.get("in_minus")):
                selected.append(candidate)
        elif method == "diff_guided":
            if item.get("downstream") and item.get("difference_carrying"):
                selected.append(candidate)
    if method == "diff_guided":
        selected.sort(key=lambda op: (-int(evidence[int(op["line"])]["score"]),
                                      int(op["line"])))
    else:
        selected.sort(key=lambda op: int(op["line"]))
    return selected


def _claims_for_row(method: str, task_id: str, project_id: str, probe: str,
                    target: Dict[str, Any], payload: Dict[str, Any],
                    plus_root: Path, minus_root: Path, plus_base: Dict[str, Any],
                    minus_base: Dict[str, Any], candidates: List[Dict[str, Any]],
                    plus_events: Sequence[Dict[str, Any]],
                    minus_events: Sequence[Dict[str, Any]],
                    cache: Dict[str, str]) -> Dict[str, Any]:
    evidence = {int(op["line"]): _evidence(
                    op, plus_events, minus_events, int(target["line"]))
                for op in candidates}
    universe = _select(method, candidates, evidence, int(target["line"]))
    validated = []
    for candidate in universe:
        line = int(candidate["line"])
        others = [op for op in universe if op is not candidate]
        keep_plus = _observe(
            project_id,
            _build(project_id, task_id, "plus", others, cache),
            probe, payload)
        keep_minus = _observe(
            project_id,
            _build(project_id, task_id, "minus", others, cache),
            probe, payload)
        masked_keep = bool(
            keep_plus["ok"] and keep_minus["ok"]
            and keep_plus["observation"].get("outcome") == "return"
            and keep_plus["observation"] == keep_minus["observation"])
        del_plus = _observe(
            project_id,
            _build(project_id, task_id, "plus", [candidate], cache),
            probe, payload)
        del_minus = _observe(
            project_id,
            _build(project_id, task_id, "minus", [candidate], cache),
            probe, payload)
        exposed = bool(
            del_plus["ok"] and del_minus["ok"]
            and del_plus["observation"] != del_minus["observation"])
        validated.append({
            "operation": {"file": candidate["file"], "line": line,
                          "end_line": candidate["end_line"]},
            "evidence": evidence[line],
            "keep_only_masked": masked_keep,
            "delete_exposed": exposed,
            "passes_singleton": bool(masked_keep and exposed),
        })
    passes = [row for row in validated if row["passes_singleton"]]
    claims = []
    if passes:
        best = passes[0]["operation"]
        claims.append({"type": "MSMS", "input": payload,
                       "operations": [{"file": best["file"],
                                       "line": best["line"]}]})
        claims.append({"type": "MMBS", "input": payload,
                       "operations": [{"file": best["file"],
                                       "line": best["line"]}]})
    return {
        "input": payload,
        "base_masked": True,
        "candidate_universe": [
            {"file": op["file"], "line": int(op["line"]),
             "end_line": int(op["end_line"])} for op in universe],
        "evidence": evidence,
        "validation": validated,
        "submitted": passes[0]["operation"] if passes else None,
        "claims": claims,
    }


def run_task(task_id: str, method: str) -> Dict[str, Any]:
    task = public_task(task_id)
    project_id = task["project_id"]
    probe = PROBE_BY_TASK[task_id]
    PUBLIC_FILE_CACHE[task_id] = task["target_operation"]["file"]
    target = task["target_operation"]
    target_file = target["file"]
    target_var = target_variable(task)
    candidates = candidate_operations(task)
    inputs = input_pool(task_id)[:MAX_INPUTS]
    cache: Dict[str, str] = {}

    plus_base_path = _build(project_id, task_id, "plus", [], cache)
    minus_base_path = _build(project_id, task_id, "minus", [], cache)

    rows = []
    for payload in inputs:
        plus = _observe(project_id, plus_base_path, probe, payload)
        minus = _observe(project_id, minus_base_path, probe, payload)
        if not (plus["ok"] and minus["ok"]):
            kind = "invalid"
        elif plus["observation"] != minus["observation"]:
            kind = "exposing"
        else:
            kind = "masked"
        trace = _trace(project_id, plus_base_path, probe, target_file,
                       target_var, payload)
        rows.append({
            "input": payload, "kind": kind,
            "plus": plus["observation"], "minus": minus["observation"],
            "a_executes": int(target["line"]) in _lines(trace.get("events", [])),
            "trace_errors": trace.get("errors", []),
        })

    masked_rows = [row for row in rows
                   if row["kind"] == "masked" and row["a_executes"]][:3]
    exposing_rows = [row for row in rows
                     if row["kind"] == "exposing" and row["a_executes"]][:2]
    claims: List[Dict[str, Any]] = []
    row_results = []
    for row in masked_rows:
        plus_events = _trace(project_id, plus_base_path, probe, target_file,
                             target_var, row["input"]).get("events", [])
        minus_events = _trace(project_id, minus_base_path, probe, target_file,
                              target_var, row["input"]).get("events", [])
        result = _claims_for_row(
            method, task_id, project_id, probe, target, row["input"],
            plus_base_path, minus_base_path, {"ok": True}, {"ok": True},
            candidates, plus_events, minus_events, cache)
        row_results.append(result)
        claims.extend(result["claims"])
    for row in exposing_rows:
        claims.append({"type": "EXPOSING_COUNTEREXAMPLE",
                       "input": row["input"]})

    return {
        "task_id": task_id,
        "method": method,
        "target": target,
        "candidate_operations": candidates,
        "inputs_evaluated": rows,
        "masked_rows_used": len(masked_rows),
        "claims": claims[:8],
        "variant_builds": len(cache),
        "rows": row_results,
        "unresolved": [] if claims else ["UNKNOWN: no validated single operation"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--method", choices=METHODS, required=True)
    parser.add_argument("--task", action="append")
    args = parser.parse_args()
    tasks = args.task or [
        "jinja2_bytecode_cache_read",
        "werkzeug_bind_server_name_lower",
        "werkzeug_filestorage_stream_name",
        "werkzeug_get_host_default_empty",
        "werkzeug_secure_filename_ascii_filter",
    ]
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    for task_id in tasks:
        result = run_task(task_id, args.method)
        path = OUT_ROOT / args.method / f"{task_id}.json"
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                   sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({
            "task": task_id, "method": args.method,
            "claims": len(result["claims"]),
            "builds": result["variant_builds"],
            "path": str(path),
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
