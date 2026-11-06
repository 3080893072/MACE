"""MACE Candidate Discovery v2: Qwen-assisted candidate expansion.

Scope: four frozen source-derived tasks only.  The adapter reuses the existing
SD executor, block projection and strict scorer.  It does not modify the
dataset, hidden references, C0/Graph results or the role-separated search.

New pieces:
  * U_ast   -- an AST catalogue of executable statements in A's function and
               same-file functions reachable from it, plus non-deletable
               control regions / function boundaries / unsupported nodes.
  * U_qwen  -- model-proposed operations mapped back to real AST statements.
  * U_union -- U_graph union U_qwen, with provenance; nothing from U_graph is
               removed.
  * targeted causal verification -- every proposed kept-set is executed and
               checked for strict minimality; SEARCH_INCOMPLETE is recorded
               rather than hidden.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))
TOOLS = KIT / "benchmark_v4_dataset" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from sd_algorithm_pilot import (  # noqa: E402
    DS, SD, WORK, SDExecutor, block_spans, family, load,
    project_containment, stage0_row, _MARKER,
)
from benchmark_v3_baselines.ast_discovery import (  # noqa: E402
    _signature, discover, rank_and_prune, reachable_functions,
    target_lhs_variables, target_variables,
)
from benchmark_v4_dataset.tools.sd_algorithm_pilot import MAX_OPS  # noqa: E402
from benchmark_v3_baselines import subgraph as sg  # noqa: E402
from benchmark_v3_baselines.graph_search import (  # noqa: E402
    search_relations_role_separated, subset_key,
)
from mace.qwen import QwenClient, extract_json  # noqa: E402
from mace.paths import venv_python  # noqa: E402

MODEL = "qwen2.5-coder:32b"
ENDPOINT = "http://127.0.0.1:11434"
NUM_CTX = 16384
NUM_PREDICT = 4096
BUDGET = 16
TASKS = [
    "sd_attrs_asdict_loop_m7",
    "sd_coverage_glob_backslash_m2",
    "sd_docutils_backticks_m1",
    "sd_docutils_educate_dashes_m2",
    "sd_docutils_ellipsis_m3",
    "sd_docutils_language_tag_m3",
    "sd_docutils_make_id_lower",
    "sd_docutils_make_id_nonid_m2",
    "sd_docutils_smartquotes_strip_m1",
    "sd_docutils_stupefy_emdash_m2",
    "sd_docutils_stupefy_endash_m1",
    "sd_humanize_filesize_gnu_m5",
    "sd_isort_format_strip_m4",
    "sd_jsonschema_1145_pointer",
    "sd_networkx_adjlist_strip_m1",
    "sd_pygments_latex297_italic",
    "sd_pygments_style95_cache",
    "sd_tabulate_1052_strip_right",
    "sd_tabulate_1056_strip_center",
    "sd_tabulate_2557_curlen",
    "sd_toml_strict_num_strip_m1",
]
RUN = Path(os.environ.get("MACE_RUN_DIR", KIT / "runs" / "candidate_discovery_v2_1"))
OUT = Path(os.environ.get("MACE_DEV_OUT", KIT / "results" / "MACE_candidate_discovery_v2_1_dev.json"))
OLD = KIT / "results" / "MACE_direct_vs_full.json"
BASE_DIR = RUN / "baselines"
DEADLINE_SECONDS = 45 * 60

CONTROL_TYPES = (ast.If, ast.While, ast.For, ast.AsyncFor, ast.Try,
                 ast.With, ast.AsyncWith, ast.Match)
BOUNDARY_TYPES = (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)
UNSUPPORTED_TYPES = (ast.Pass, ast.Break, ast.Continue, ast.Global,
                     ast.Nonlocal, ast.Import, ast.ImportFrom)


def utc() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def span(node: ast.AST) -> Tuple[int, int]:
    return (int(getattr(node, "lineno", 0)),
            int(getattr(node, "end_lineno", node.lineno)))


def nearest_function(node: ast.AST,
                     parents: Dict[int, ast.AST]) -> ast.AST | None:
    parent = parents.get(id(node))
    while parent is not None:
        if isinstance(parent, (ast.FunctionDef, ast.AsyncFunctionDef)):
            return parent
        parent = parents.get(id(parent))
    return None


def node_payload(node: ast.AST, source_text: str, source_lines: Sequence[str],
                 rel: str, parents: Dict[int, ast.AST],
                 function: str) -> Dict[str, Any]:
    first, last = span(node)
    kind = type(node).__name__
    plain, attrs = sg._stored_names(node)
    calls = [name for name, _, _ in sg._called(node) if name]
    return {
        "id": f"{rel}:{first}-{last}",
        "file": rel,
        "first_line": first,
        "last_line": last,
        "kind": kind,
        "code": "\n".join(source_lines[first - 1:last]),
        "function": function,
        "guards": sg._guards(source_text, node, parents),
        "defs": sorted(plain),
        "attr_defs": sorted(attrs),
        "uses": sorted(sg._loaded_names(node)),
        "calls": sorted(set(calls)),
        "in_loop": any(isinstance(anc, (ast.For, ast.AsyncFor, ast.While))
                       for anc in sg._ancestors(node, parents)),
    }


def build_catalog(source_text: str, rel: str, a_line: int,
                  task: Dict[str, Any]) -> Dict[str, Any]:
    tree = ast.parse(source_text)
    parents = sg._parent_map(tree)
    functions = reachable_functions(tree, task["target_operation"])
    if not functions:
        root = None
        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                    span(node)[0] <= a_line <= span(node)[1]:
                root = node
                break
        functions = [root] if root else []
    allowed = {id(fn) for fn in functions}
    source_lines = source_text.splitlines()
    executable, controls, boundaries, unsupported = [], [], [], []
    seen: set[str] = set()

    for fn in functions:
        f_first, f_last = span(fn)
        boundaries.append({
            "id": f"function:{fn.name}:{f_first}-{f_last}",
            "name": fn.name,
            "first_line": f_first,
            "last_line": f_last,
            "category": "function_boundary",
            "deletable": False,
        })

    for node in ast.walk(tree):
        if not isinstance(node, ast.stmt):
            continue
        if isinstance(node, ast.ClassDef):
            continue
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if id(node) in allowed and id(node) not in {id(fn) for fn in functions}:
                first, last = span(node)
                boundaries.append({
                    "id": f"function:{node.name}:{first}-{last}",
                    "name": node.name, "first_line": first,
                    "last_line": last, "category": "function_boundary",
                    "deletable": False,
                })
            continue
        fn = nearest_function(node, parents)
        if fn is None or id(fn) not in allowed:
            continue
        first, last = span(node)
        base = node_payload(node, source_text, source_lines, rel, parents,
                            fn.name)
        contains_a = first <= a_line <= last
        base["contains_target"] = contains_a
        if isinstance(node, CONTROL_TYPES):
            base.update({
                "id": f"control:{rel}:{first}-{last}",
                "category": "control_context",
                "deletable": False,
                "control_kind": type(node).__name__,
                "condition": sg._condition_text(source_text, node),
            })
            controls.append(base)
            continue
        if isinstance(node, UNSUPPORTED_TYPES):
            base.update({"category": "unsupported", "deletable": False,
                         "reason": "not a state-changing executable operation"})
            unsupported.append(base)
            continue
        is_exec = (
            isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign,
                              ast.Delete, ast.Return, ast.Raise, ast.Assert))
            or (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call))
        )
        if not is_exec:
            base.update({"category": "unsupported", "deletable": False,
                         "reason": "expression has no call or state effect"})
            unsupported.append(base)
            continue
        if contains_a:
            base.update({"category": "contains_target", "deletable": False,
                         "reason": "deleting it would delete A"})
            unsupported.append(base)
            continue
        if base["id"] in seen:
            base.update({"category": "unsupported", "deletable": False,
                         "reason": "duplicate span"})
            unsupported.append(base)
            continue
        seen.add(base["id"])
        base.update({"category": "executable", "deletable": True})
        executable.append(base)

    # control regions: list executable statements contained in each region
    for control in controls:
        cf, cl = control["first_line"], control["last_line"]
        control["contained_executable_ids"] = [
            op["id"] for op in executable
            if cf <= op["first_line"] and op["last_line"] <= cl
        ]
        control["contained_executable_spans"] = [
            [op["first_line"], op["last_line"]] for op in executable
            if cf <= op["first_line"] and op["last_line"] <= cl
        ]

    executable.sort(key=lambda x: (x["first_line"], x["last_line"], x["id"]))
    controls.sort(key=lambda x: (x["first_line"], x["last_line"]))
    boundaries.sort(key=lambda x: (x["first_line"], x["last_line"]))
    unsupported.sort(key=lambda x: (x["first_line"], x["last_line"]))
    return {
        "schema": "mace-u-ast/1",
        "file": rel,
        "target_line": a_line,
        "target_variables": sorted(target_variables(source_text,
                                                     task["target_operation"])),
        "target_lhs_variables": sorted(target_lhs_variables(
            source_text, task["target_operation"])),
        "functions": [{"name": fn.name, "first_line": span(fn)[0],
                       "last_line": span(fn)[1]} for fn in functions],
        "executable": executable,
        "control_contexts": controls,
        "function_boundaries": boundaries,
        "unsupported": unsupported,
        "counts": {
            "executable": len(executable),
            "control_context": len(controls),
            "function_boundary": len(boundaries),
            "unsupported": len(unsupported),
        },
    }


def render_source(source_lines: Sequence[str],
                  functions: Sequence[Dict[str, Any]],
                  max_lines: int = 260,
                  center_line: int | None = None) -> str:
    ranges = sorted((f["first_line"], f["last_line"]) for f in functions)
    merged: List[List[int]] = []
    for first, last in ranges:
        if merged and first <= merged[-1][1] + 1:
            merged[-1][1] = max(merged[-1][1], last)
        else:
            merged.append([first, last])
    out, used = [], 0
    for first, last in merged:
        if used >= max_lines:
            out.append("... (source excerpt truncated)")
            break
        if center_line is not None and first <= center_line <= last:
            window = max_lines - used
            start = max(first, min(center_line - 25, last - window + 1))
            first = start
        take_last = min(last, first + max_lines - used - 1)
        for number in range(first, take_last + 1):
            out.append(f"{number:5d} | {source_lines[number - 1]}")
        used += take_last - first + 1
        if take_last < last:
            out.append(f"... lines {take_last + 1}-{last} omitted")
    return "\n".join(out)


def compress_lines(lines: Iterable[int]) -> str:
    ordered = sorted(set(int(x) for x in lines))
    if not ordered:
        return "(none)"
    ranges, start, prev = [], ordered[0], ordered[0]
    for value in ordered[1:]:
        if value == prev + 1:
            prev = value
            continue
        ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
        start = prev = value
    ranges.append(f"{start}" if start == prev else f"{start}-{prev}")
    return ", ".join(ranges)


def trace_run(executor: SDExecutor, payload: dict, side: str) -> Dict[str, Any]:
    vdir = executor.variant_dir([], side)
    target = str((vdir / executor.rel).resolve())
    boot = (
        "import json, runpy, sys\n"
        f"target = {target!r}\n"
        "hit = []\n"
        "def tr(frame, event, arg):\n"
        "    if event == 'line' and frame.f_code.co_filename == target:\n"
        "        hit.append(frame.f_lineno)\n"
        "    return tr\n"
        f"sys.path.insert(0, {str(vdir)!r})\n"
        f"sys.path.insert(0, {str(vdir / executor.top)!r})\n"
        "sys.settrace(tr)\n"
        "try:\n"
        f"    runpy.run_path({str(executor.probe)!r}, run_name='__main__')\n"
        "finally:\n"
        "    sys.settrace(None)\n"
        "print(json.dumps({'lines': hit}))\n")
    env = {k: v for k, v in os.environ.items()
           if k in ("PATH", "SystemRoot", "TEMP", "TMP", "HOME",
                    "USERPROFILE", "LOCALAPPDATA", "APPDATA")}
    env.update({"PYTHONIOENCODING": "utf-8",
                "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"})
    venv = venv_python(executor.slug)
    scratch = Path(tempfile.mkdtemp(prefix="mace_trace_"))
    try:
        proc = subprocess.run(
            [str(venv), "-I", "-c", boot], cwd=str(scratch), env=env,
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=300)
        lines: List[int] = []
        for line in reversed(proc.stdout.strip().splitlines()):
            try:
                lines = list(extract_json(line).get("lines") or [])
                break
            except Exception:  # noqa: BLE001
                continue
        return {"side": side, "lines": lines, "returncode": proc.returncode,
                "stderr_tail": proc.stderr[-300:] if proc.stderr else ""}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


def observation_text(value: Any, limit: int = 260) -> str:
    text = json.dumps(value, ensure_ascii=False, sort_keys=True)
    return text if len(text) <= limit else text[:limit] + "..."


def build_prompt(cid: str, rel: str, a_line: int, a_code: str,
                 source_text: str, catalog: Dict[str, Any],
                 graph: Dict[str, Any], u_graph: Sequence[dict],
                 traces: Sequence[Dict[str, Any]], n_inputs: int) -> str:
    inputs = ", ".join(f"`in{i}`" for i in range(1, n_inputs + 1))
    graph_ids = {op["id"] for op in u_graph}
    ast_exec = catalog["executable"]
    ast_ids = {op["id"] for op in ast_exec}
    target_id = graph.get("target", {}).get("id", "")
    focus_functions = {graph.get("target", {}).get("function", "")}
    focus_functions |= {op.get("function", "") for op in u_graph}
    focus_ids = graph_ids | {target_id}
    for op in ast_exec:
        if op["function"] in focus_functions:
            focus_ids.add(op["id"])
    # Also include AST statements sharing a name with A or with a graph op.
    shared_names = set(catalog.get("target_variables") or [])
    for op in u_graph:
        shared_names |= set(op.get("defs") or []) | set(op.get("uses") or [])
    for op in ast_exec:
        if (set(op["defs"]) | set(op["uses"])) & shared_names:
            focus_ids.add(op["id"])

    focus_ast = [op for op in ast_exec if op["id"] in focus_ids]
    focused = {op["id"] for op in focus_ast[:18]}
    ast_lines = []
    for op in ast_exec:
        if op["id"] in focused:
            code = " ".join(op["code"].split())
            if len(code) > 130:
                code = code[:130] + "..."
            ast_lines.append(
                f"- {op['id']} | lines={op['first_line']}-{op['last_line']} | "
                f"kind={op['kind']} | fn={op['function']} | "
                f"guards={op['guards']} | defs={op['defs']} | uses={op['uses']} | "
                f"calls={op['calls']} | code={code!r}")
        else:
            ast_lines.append(f"- {op['id']}")
    control_focus = []
    control_other = 0
    for op in catalog["control_contexts"]:
        if (set(op.get("contained_executable_ids") or []) & focus_ids
                or op["function"] in focus_functions):
            control_focus.append(op)
        else:
            control_other += 1
    control_lines = [
        f"- {op['id']} | lines={op['first_line']}-{op['last_line']} | "
        f"kind={op['kind']} | condition={op['condition']!r} | "
        f"contained_executable="
        f"{op['contained_executable_ids'][:12]}"
        f"{' ...' if len(op['contained_executable_ids']) > 12 else ''}"
        for op in control_focus[:8]]
    if len(control_focus) > 8:
        control_lines.append(
            f"- ({len(control_focus) - 8} more focus control regions omitted)")
    if control_other:
        control_lines.append(f"- ({control_other} less relevant control regions omitted)")
    boundary_lines = [
        f"- {op['name']} | lines={op['first_line']}-{op['last_line']}"
        for op in catalog["function_boundaries"]]
    unsupported_lines = [
        f"- {op['id']} | lines={op['first_line']}-{op['last_line']} | "
        f"kind={op['kind']} | reason={op['reason']}"
        for op in catalog["unsupported"]]

    graph_lines = []
    for op in u_graph:
        code = " ".join(str(op.get("code", "")).split())
        if len(code) > 180:
            code = code[:180] + "..."
        graph_lines.append(
            f"- {op['id']} | lines={op.get('first_line')}-{op.get('last_line')} | "
            f"kind={op.get('kind')} | code={code!r}")

    rel_edges = []
    for edge in graph.get("edges", []):
        if edge["src"] in focus_ids or edge["dst"] in focus_ids:
            if edge["src"] in ast_ids or edge["src"] in graph_ids or \
                    edge["dst"] in ast_ids or edge["dst"] in graph_ids:
                rel_edges.append(edge)
    edge_lines = [
        f"- {e['src']} -> {e['dst']} | {e['kind']}/{e['confidence']} | "
        f"guard={e.get('guard', '')!r} | evidence={e.get('evidence', '')!r}"
        for e in rel_edges[:8]]
    if len(rel_edges) > 8:
        edge_lines.append(f"... ({len(rel_edges) - 8} more edges omitted)")

    trace_lines = []
    for row in traces:
        trace_lines.append(
            f"- {row['input']}: plus={row['plus']} | minus={row['minus']} | "
            f"A-deletion={row['a_deletion']} | executed_plus={row['executed_plus']} | "
            f"executed_minus={row['executed_minus']} | "
            f"executed_only_plus={row['executed_only_plus']} | "
            f"executed_only_minus={row['executed_only_minus']} | "
            f"u_graph_single_delete_changes={row['u_graph_single_delete_changes']} | "
            f"unexplained_by_u_base={row['unexplained_by_u_base']}")

    target_fn_name = graph.get("target", {}).get("function", "")
    source_functions = [fn for fn in catalog["functions"]
                        if fn["name"] == target_fn_name]
    if not source_functions:
        source_functions = [fn for fn in catalog["functions"]
                            if fn["name"] in focus_functions][:2]
    if not source_functions:
        source_functions = catalog["functions"]
    source_excerpt = render_source(
        source_text.splitlines(), source_functions, max_lines=42,
        center_line=a_line)
    # Related functions: same-file functions that contain U_base operations or
    # are directly reachable from the target.  Bounded so the prompt stays in
    # context; the operation catalogue still lists every executable statement.
    base_fns = []
    for op in u_graph:
        fn = op.get("function") or ""
        if fn and fn != target_fn_name and fn not in base_fns:
            base_fns.append(fn)
    related = [fn for fn in catalog["functions"]
               if fn["name"] in base_fns and fn["name"] != target_fn_name]
    if not related:
        # No U_base operation lives in another function.  Still show the
        # same-file functions that the target or U_base operations call, so
        # Qwen can reason about cross-function repair paths.
        called_names = set()
        for op in ast_exec:
            if op["id"] in focus_ids:
                called_names |= set(op.get("calls") or [])
        for op in u_graph:
            called_names |= set(op.get("calls") or [])
        related = [fn for fn in catalog["functions"]
                   if fn["name"] in called_names
                   and fn["name"] != target_fn_name][:2]
    if not related:
        related = [fn for fn in catalog["functions"]
                   if any(op["function"] == fn["name"] for op in ast_exec)
                   and fn["name"] != target_fn_name][:2]
    related_excerpts = []
    for fn in related[:2]:
        text = render_source(source_text.splitlines(), [fn], max_lines=16)
        related_excerpts.append(
            f"### {fn['name']} (lines {fn['first_line']}-{fn['last_line']})\n"
            f"```text\n{text}\n```")
    related_block = ("\n\n".join(related_excerpts) if related_excerpts
                     else "(no additional same-file function needed)")
    return f"""You are analysing a proposed deletion A in Python. Use only the public
information below. Do not assume hidden answers, hidden test roles or any
relation that is not supported by source and execution evidence.

## Task
{cid}

## File
`{rel}`

## Target operation A
Line {a_line}: `{a_code.strip()}`
Deletion rule: replace exactly this line with equal-indentation `pass`.

## Legal inputs
The declared finite inputs are opaque labels: {inputs}.  Do not assume their
roles or argument values.

## Source excerpt: target function
```text
{source_excerpt}
```

## Related same-file functions (bounded excerpts)
{related_block}

## U_base: operations already in Full MACE's frozen C0 candidate pool
These are already in the candidate pool.  Do not delete or replace them; you
may add operations outside this list.
{chr(10).join(graph_lines) if graph_lines else "(empty)"}

## U_ast: executable statements (the only legal operation ids)
These are real AST executable statements.  Use their exact `operation_id`.
Do not use a whole control region as an operation.
{chr(10).join(ast_lines) if ast_lines else "(empty)"}

## Control contexts (NOT deletable operations)
{chr(10).join(control_lines) if control_lines else "(none)"}

## Function boundaries (NOT deletable operations)
{chr(10).join(boundary_lines) if boundary_lines else "(none)"}

## Unsupported nodes (NOT deletable operations)
{chr(10).join(unsupported_lines) if unsupported_lines else "(none)"}

## Data / control dependencies involving U_base or A
{chr(10).join(edge_lines) if edge_lines else "(none)"}

## Dynamic execution trace and A-deletion state difference
`plus` is A present; `minus` is A replaced by pass.  `A-deletion` is
`same` when the observations are identical, `different` when they differ.
`executed_only_plus` / `executed_only_minus` are the lines that run on only
one side.  `u_graph_single_delete_changes` lists U_base operations whose
single deletion changes the plus observation.
`unexplained_by_u_base=true` marks an A-deletion behaviour change that no
single U_base deletion reproduces; those changes are the main target for new
candidate operations.
__TRACE_LINES__

## Question
A is masked on an input when deleting A produces the same observation.  Find
executable operations outside U_base that may be part of a minimal masking
relation: a set S of one or more executable operations such that, on at least
one legal input, keeping S while deleting all other candidate operations makes
A's deletion unobservable.  S must be minimal.

Use `relation_type` to distinguish:
- `cooperative_leg`: one leg of a multi-operation repair;
- `alternative_path`: one independent repair path;
- `shared_state`: a write/read of the same object or variable;
- `control_flow`: an operation whose guard changes whether the repair runs;
- `exception_fallback`: an exception/fallback path.

For each candidate operation, give the exact `operation_id` from U_ast, the
source span, why it may participate, related operation ids, the masking
condition, and the execution evidence you used.  If a control region matters,
put its executable body operations in `related_operations`, not as the
operation itself.

Return at most 4 candidate operations and at most 3 candidate sets.  Return
one JSON object and no prose outside it.

## Required JSON
{{
  "candidates": [
    {{
      "operation_id": "<exact U_ast executable id>",
      "source_span": "<file>:<first>-<last>",
      "relation_type": "cooperative_leg|alternative_path|shared_state|control_flow|exception_fallback",
      "related_operations": ["<id>", "..."],
      "masking_condition": "<boolean expression or true>",
      "semantic_rationale": "<one sentence>",
      "supporting_execution_evidence": "<one sentence>"
    }}
  ],
  "candidate_sets": [
    {{
      "kept_operations": ["<id>", "..."],
      "relation_type": "cooperative_leg|alternative_path|...",
      "masking_condition": "<boolean expression or true>",
      "rationale": "<one sentence>"
    }}
  ]
}}
""".replace("__TRACE_LINES__", "\n".join(trace_lines))


def parse_answer(raw: str) -> Dict[str, Any]:
    try:
        obj = extract_json(raw)
        return {"ok": True, "object": obj, "error": None}
    except Exception as exc:  # noqa: BLE001
        return {"ok": False, "object": {}, "error": f"{type(exc).__name__}: {exc}"}


def map_token(token: Any, ast_exec: Dict[str, dict],
              graph_ops: Dict[str, dict],
              controls: Dict[str, dict]) -> Dict[str, Any]:
    if isinstance(token, dict):
        token = (token.get("operation_id") or token.get("id")
                 or token.get("source_span") or token.get("line"))
    text = str(token or "").strip()
    if not text:
        return {"status": "rejected", "reason": "empty_id", "token": token}
    if text in ast_exec:
        return {"status": "mapped", "op": ast_exec[text], "token": text}
    if text in graph_ops:
        return {"status": "mapped_graph", "op": graph_ops[text], "token": text}
    if text in controls:
        c = controls[text]
        return {"status": "rejected", "reason": "control_context_not_deletable",
                "token": text, "expanded_executable_ids": c.get(
                    "contained_executable_ids", [])}
    match = re.match(r"^(.+):(\d+)-(\d+)$", text)
    if match:
        rel, first, last = match.group(1), int(match.group(2)), int(match.group(3))
        for op in ast_exec.values():
            if op["file"] == rel and op["first_line"] == first and \
                    op["last_line"] == last:
                return {"status": "mapped", "op": op, "token": text}
        for op in controls.values():
            if op["file"] == rel and op["first_line"] == first and \
                    op["last_line"] == last:
                return {"status": "rejected",
                        "reason": "control_context_not_deletable",
                        "token": text,
                        "expanded_executable_ids": op.get(
                            "contained_executable_ids", [])}
    line_match = re.search(r"(?:line\s*)?(\d+)", text, re.I)
    if line_match:
        line = int(line_match.group(1))
        hits = [op for op in ast_exec.values() if op["first_line"] == line]
        if len(hits) == 1:
            return {"status": "mapped_by_line", "op": hits[0], "token": text}
    return {"status": "rejected", "reason": "unknown_operation_id", "token": text}


def collect_qwen(obj: Dict[str, Any], ast_exec: Dict[str, dict],
                 graph_ops: Dict[str, dict], controls: Dict[str, dict]) -> Dict:
    candidates_raw = obj.get("candidates") or obj.get("operations") or []
    sets_raw = obj.get("candidate_sets") or obj.get("candidate_relations") or []
    if isinstance(candidates_raw, dict):
        candidates_raw = [candidates_raw]
    if isinstance(sets_raw, dict):
        sets_raw = [sets_raw]
    mapped, rejected, mapping = [], [], []
    for raw in candidates_raw:
        if not isinstance(raw, dict):
            raw = {"operation_id": raw}
        result = map_token(raw.get("operation_id") or raw.get("source_span"),
                           ast_exec, graph_ops, controls)
        related = []
        for token in raw.get("related_operations") or []:
            rel = map_token(token, ast_exec, graph_ops, controls)
            if rel["status"].startswith("mapped"):
                related.append(rel["op"]["id"])
        record = {
            "raw": raw,
            "status": result["status"],
            "reason": result.get("reason"),
            "operation_id": (result.get("op") or {}).get("id"),
            "expanded_executable_ids": result.get("expanded_executable_ids", []),
            "related_operations": sorted(set(related)),
        }
        mapping.append(record)
        if result["status"].startswith("mapped"):
            mapped.append({
                **result["op"],
                "provenance": "qwen",
                "qwen_status": result["status"],
                "qwen_raw": raw,
                "qwen_related": sorted(set(related)),
            })
        else:
            rejected.append(record)
    sets, set_rejects = [], []
    for raw in sets_raw:
        if not isinstance(raw, dict):
            raw = {"kept_operations": raw}
        tokens = (raw.get("kept_operations") or raw.get("operations")
                  or raw.get("related_operations") or [])
        ids, rejected_tokens = [], []
        for token in tokens:
            result = map_token(token, ast_exec, graph_ops, controls)
            if result["status"].startswith("mapped"):
                ids.append(result["op"]["id"])
            else:
                rejected_tokens.append({"token": token,
                                        "reason": result.get("reason")})
        ids = sorted(set(ids))
        if rejected_tokens or not ids:
            set_rejects.append({"raw": raw, "rejected": rejected_tokens,
                                "reason": "unmapped_or_empty"})
        else:
            sets.append({
                "kept_operations": ids,
                "relation_type": raw.get("relation_type"),
                "masking_condition": raw.get("masking_condition"),
                "rationale": raw.get("rationale"),
                "source": "qwen_candidate_set",
            })
    # A model candidate is also a legal singleton hypothesis.
    for op in mapped:
        sets.append({
            "kept_operations": [op["id"]],
            "relation_type": op.get("qwen_raw", {}).get("relation_type"),
            "masking_condition": op.get("qwen_raw", {}).get("masking_condition"),
            "rationale": op.get("qwen_raw", {}).get("semantic_rationale"),
            "source": "qwen_singleton",
        })
    # Deduplicate in order.
    unique, seen = [], set()
    for item in sets:
        key = tuple(item["kept_operations"])
        if key in seen:
            continue
        seen.add(key)
        unique.append(item)
    return {
        "candidates": mapped,
        "rejected_candidates": rejected,
        "mapping": mapping,
        "candidate_sets": unique,
        "rejected_sets": set_rejects,
        "stats": {
            "proposed": len(candidates_raw),
            "mapped": len(mapped),
            "rejected": len(rejected),
            "sets_proposed": len(sets_raw),
            "sets_accepted": len(unique),
            "sets_rejected": len(set_rejects),
        },
    }


def union_ops(u_graph: Sequence[dict], u_qwen: Sequence[dict]) -> List[dict]:
    by_id: Dict[str, dict] = {}
    order: List[str] = []
    for op in u_graph:
        item = dict(op)
        item["sources"] = ["graph"]
        item["provenance"] = "graph"
        by_id[item["id"]] = item
        order.append(item["id"])
    for op in u_qwen:
        if op["id"] in by_id:
            by_id[op["id"]]["sources"].append("qwen")
            by_id[op["id"]]["qwen_repeat"] = True
            by_id[op["id"]]["qwen_raw"] = op.get("qwen_raw")
            continue
        item = dict(op)
        item["sources"] = ["qwen"]
        item["provenance"] = "qwen"
        by_id[item["id"]] = item
        order.append(item["id"])
    return [by_id[op_id] for op_id in order]


def block_cover(ops: Sequence[dict], spans: Dict[str, tuple]) -> Dict[str, Any]:
    by_id = {op["id"]: op for op in ops}
    covered, stray = set(), []
    for op in ops:
        blocks, bad = project_containment([op["id"]], by_id, spans)
        if blocks:
            covered |= blocks
        else:
            stray.append(op["id"])
    return {
        "covered_blocks": sorted(covered),
        "stray_candidates": stray,
        "recall": round(len(covered) / len(spans), 3) if spans else None,
        "wrong_candidates": len(stray),
    }


def candidate_sets_for_verification(qwen_sets: Sequence[dict],
                                    qwen_candidates: Sequence[dict],
                                    u_graph: Sequence[dict],
                                    search_sets: Sequence[Sequence[str]],
                                    limit: int = 36) -> List[dict]:
    graph_ids = [op["id"] for op in u_graph]
    qwen_ids = [op["id"] for op in qwen_candidates]
    out: List[dict] = []
    seen = set()

    def add(ids: Sequence[str], source: str, extra: dict | None = None):
        key = tuple(sorted(set(ids)))
        if not key or key in seen:
            return
        seen.add(key)
        item = {"kept_operations": list(key), "source": source}
        if extra:
            item.update(extra)
        out.append(item)

    for item in qwen_sets:
        add(item["kept_operations"], item.get("source", "qwen_set"), item)
    for size in range(1, min(3, len(qwen_ids)) + 1):
        for combo in itertools.combinations(qwen_ids, size):
            add(combo, f"qwen_combo_{size}")
    for q in qwen_ids:
        for g in graph_ids:
            add([q, g], "qwen_graph_pair")
    for size in range(1, min(3, len(graph_ids)) + 1):
        for combo in itertools.combinations(graph_ids, size):
            add(combo, f"graph_combo_{size}")
    for ids in search_sets:
        add(ids, "search_msms")
    return out[:limit]


def proper_nonempty_subsets(ids: Sequence[str]):
    ordered = sorted(ids)
    for size in range(1, len(ordered)):
        for combo in itertools.combinations(ordered, size):
            yield combo


def verify_candidate_sets(executor: SDExecutor, universe: Sequence[str],
                          candidate_sets: Sequence[dict], payload: dict) -> Dict:
    universe = sorted(universe)
    needed = set()
    plans = []
    for item in candidate_sets:
        kept = tuple(sorted(set(item["kept_operations"]) & set(universe)))
        if not kept:
            continue
        subs = [tuple(sorted(s)) for s in proper_nonempty_subsets(kept)]
        disabled = tuple(sorted(set(universe) - set(kept)))
        needed.add(disabled)
        for sub in subs:
            needed.add(tuple(sorted(set(universe) - set(sub))))
        plans.append((item, kept, subs))
    if needed:
        executor.prefetch(list(needed))

    def masked(kept: Sequence[str]):
        disabled = tuple(sorted(set(universe) - set(kept)))
        plus = executor.observation(disabled, "plus", payload)
        minus = executor.observation(disabled, "minus", payload)
        if plus.get("__probe_error__") or minus.get("__probe_error__"):
            return None
        return bool(plus.get("outcome") == "return" and plus == minus)

    results = []
    for item, kept, subs in plans:
        base = masked(kept)
        record = {
            **item,
            "kept_operations": list(kept),
            "disabled_operations": sorted(set(universe) - set(kept)),
            "masked": base,
            "minimal": False,
            "status": "NOT_MASKED",
            "minimality_witness": None,
            "unknown_subset": None,
        }
        if base is None:
            record["status"] = "UNKNOWN"
            results.append(record)
            continue
        if not base:
            results.append(record)
            continue
        minimal, witness, unknown = True, None, None
        for sub in subs:
            value = masked(sub)
            if value is True:
                minimal = False
                witness = list(sub)
                break
            if value is None:
                minimal = False
                unknown = list(sub)
                break
        record["minimal"] = minimal
        record["minimality_witness"] = witness
        record["unknown_subset"] = unknown
        record["status"] = ("CONFIRMED" if minimal and not unknown
                            else ("MINIMALITY_UNKNOWN" if unknown
                                  else "NOT_MINIMAL"))
        results.append(record)
    return {
        "payload": payload,
        "sets": results,
        "confirmed": [r["kept_operations"] for r in results
                      if r["status"] == "CONFIRMED"],
        "candidate_count": len(results),
    }


def score_sets(sets: Sequence[Sequence[str]], ops_by_id: dict,
               spans: dict, hidden_msms: Sequence[Sequence[str]]) -> dict:
    want = family(hidden_msms)
    hits = [project_containment(s, ops_by_id, spans) for s in sets]
    got = family([h[0] for h in hits])
    stray = [o for h in hits for o in h[1]]
    return {
        "hidden_msms": sorted(sorted(s) for s in hidden_msms),
        "got_msms_blocks": sorted(sorted(s) for s in got),
        "stray_ops": stray,
        "msms_exact": got == want and not stray,
        "hidden_msms_present": bool(want) and want <= got,
        "false_relations": len(got - want) + len(stray),
        "unmatched_sets": sum(1 for h in hits if not h[0]),
    }


def reference_for(cid: str) -> Dict[str, Any]:
    """DEV reference.  Use the formal file when present, else derive roles and
    minimal masking sets from the DEV acceptance record (never HELDOUT)."""
    formal = SD / "tasks" / cid / "reference.json"
    if formal.exists():
        return load(formal)
    acc = load(SD / "acceptance" / f"{cid}.json")
    inputs: Dict[str, Any] = {}
    for key, row in acc.get("per_input", {}).items():
        raw_sets = row.get("minimal_masking_sets") or []
        sets = [[b for b in s if b] for s in raw_sets]
        sets = [s for s in sets if s]
        empty_minimal = any(not s for s in raw_sets)
        if row.get("exposing_witness") or row.get("p_minus_equals_plus") is False:
            role, msms = "exposing", []
        elif (row.get("empty_kept_masks") and empty_minimal) or not sets:
            role, msms = "control", [[]]
        else:
            role, msms = "masking", sets
        inputs[key] = {"role": role, "msms": msms}
    return {"task_id": cid, "inputs": inputs}


def _prepare_baseline(cid: str, spec: dict, public: str,
                      payloads: Sequence[dict], key_map: Dict[str, str],
                      executor: SDExecutor, task: dict) -> Tuple[dict, dict]:
    """Load frozen C0/Graph results, or compute them once if absent."""
    c0_path = BASE_DIR / f"{cid}__c0.json"
    graph_path = BASE_DIR / f"{cid}__graph.json"
    if c0_path.exists() and graph_path.exists():
        return load(c0_path), load(graph_path)

    # C0 discovery, identical to benchmark_v4_dataset/tools/sd_algorithm_pilot.
    found = discover(task, public)
    executor.set_universe(found["candidate_ops"])
    pruned = rank_and_prune(executor, found, payloads, MAX_OPS)
    universe = pruned["universe"]
    executor.set_universe(universe)
    universe_ids = [op["id"] for op in universe]
    union_map = {op["id"]: op for op in universe}
    spans = block_spans(load(SD / "evidence" / cid / "enumeration.json"))
    ref = reference_for(cid)
    scoring = {"msms_exact": 0, "false_relations": 0, "masking_inputs": 0}
    probes_before = executor.probe_executions
    for payload in payloads:
        plus = executor.observation([], "plus", payload)
        minus = executor.observation([], "minus", payload)
        if plus.get("__probe_error__") or minus.get("__probe_error__"):
            continue
        if not (executor.a_executes(payload) and plus.get("outcome") == "return"
                and plus == minus):
            continue
        result = search_relations_role_separated(
            executor, payload, universe_ids, budget=BUDGET)
        hidden = ref["inputs"].get(key_map[payload["id"]], {})
        if hidden.get("role") != "masking":
            continue
        score = score_sets(result.get("msms_ids") or [], union_map, spans,
                           hidden.get("msms") or [])
        scoring["masking_inputs"] += 1
        scoring["msms_exact"] += int(score["msms_exact"])
        scoring["false_relations"] += score["false_relations"]
    c0 = {
        "case_id": cid, "method": "c0", "universe": universe,
        "discovery": {k: pruned.get(k) for k in (
            "considered", "dropped_no_effect", "dropped_duplicate_effect",
            "truncated")},
        "scoring": scoring,
        "cost": {"probe_executions_algorithm":
                 executor.probe_executions - probes_before},
        "source": "computed_v2_1",
    }
    graph = sg.build(task, public)
    selection = sg.candidate_selection(graph, MAX_OPS)
    graph_rec = {
        "case_id": cid, "method": "graph", "universe": selection["ops"],
        "source": "computed_v2_1",
    }
    BASE_DIR.mkdir(parents=True, exist_ok=True)
    c0_path.write_text(json.dumps(c0, ensure_ascii=False, indent=2),
                       encoding="utf-8")
    graph_path.write_text(json.dumps(graph_rec, ensure_ascii=False, indent=2),
                          encoding="utf-8")
    return c0, graph_rec


def prepare(cid: str):
    spec = load(SD / "cases" / f"{cid}.json")
    rel = spec["base"]["file"]
    patched = (SD / "evidence" / cid / "patched" / Path(rel).name) \
        .read_text("utf-8").splitlines(keepends=True)
    public = "".join(line if not _MARKER.match(line) else "\n"
                     for line in patched)
    a_line = int(spec["base"]["A_line"])
    payloads = [{"id": f"in{i + 1}"} for i in range(len(spec["inputs"]))]
    key_map = {f"in{i + 1}": key for i, key in enumerate(spec["inputs"])}
    meta = stage0_row(spec["base"]["slug"])
    root = (DS / "discovery" / meta["root"]).resolve()
    probe = (KIT / spec["probe"]).resolve()
    work = WORK / cid / "candidate_discovery_v2"
    work.mkdir(parents=True, exist_ok=True)
    executor = SDExecutor(spec["base"]["slug"], root, rel, patched, a_line,
                          probe, key_map, work)
    return spec, rel, patched, public, a_line, payloads, key_map, executor


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="+", default=TASKS)
    ap.add_argument("--out", type=Path, default=RUN / "results.json")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args()
    RUN.mkdir(parents=True, exist_ok=True)
    (RUN / "raw").mkdir(exist_ok=True)
    (RUN / "scores").mkdir(exist_ok=True)

    old = load(OLD)["tasks"] if OLD.exists() else {}
    client = QwenClient(provider="ollama", model=MODEL, endpoint=ENDPOINT,
                        num_ctx=NUM_CTX, num_predict=NUM_PREDICT,
                        temperature=0.0, seed=42, timeout=900, retries=0)
    tasks: Dict[str, dict] = {}
    totals = {
        "tasks": 0, "masking_inputs": 0,
        "c0_exact": 0, "direct_exact": 0, "old_full_exact": 0,
        "new_exact": 0, "new_present": 0, "new_false": 0,
        "new_unmatched": 0, "new_probes": 0, "new_runtime": 0.0,
        "new_prompt_tokens": 0, "new_completion_tokens": 0,
        "qwen_calls": 0, "search_incomplete_inputs": 0,
    }
    run_started = time.time()
    skipped: List[str] = []
    for cid in args.tasks:
        if time.time() - run_started > DEADLINE_SECONDS:
            skipped = list(args.tasks[args.tasks.index(cid):])
            print(f"[deadline] marking {len(skipped)} tasks INCOMPLETE", flush=True)
            break
        started = time.perf_counter()
        spec, rel, patched, public, a_line, payloads, key_map, executor = \
            prepare(cid)
        a_code = spec["base"]["A_code"]
        task = {"file": rel, "target_operation": {
            "file": rel, "line": a_line, "code": a_code}}
        catalog = build_catalog(public, rel, a_line, task)
        graph = sg.build(task, public)
        frozen_c0 = KIT / "runs" / "sd_v1_algorithm_pilot" / f"{cid}__c0.json"
        frozen_graph = KIT / "runs" / "sd_v1_algorithm_pilot" / f"{cid}__graph.json"
        if frozen_c0.exists():
            c0 = load(frozen_c0)
            graph_run = load(frozen_graph)
        else:
            c0, graph_run = _prepare_baseline(
                cid, spec, public, payloads, key_map, executor, task)
        u_graph_only = graph_run["universe"]
        # Full MACE's actual frozen candidate pool is C0.  Expand that pool;
        # the separate Graph-only universe is retained as a diagnostic.
        u_graph = c0["universe"]
        u_graph_map = {op["id"]: op for op in u_graph}
        ast_exec = {op["id"]: op for op in catalog["executable"]}
        controls = {op["id"]: op for op in catalog["control_contexts"]}

        executor.set_universe(u_graph)
        traces = []
        for payload in payloads:
            plus = executor.observation([], "plus", payload)
            minus = executor.observation([], "minus", payload)
            side_plus = trace_run(executor, payload, "plus")
            side_minus = trace_run(executor, payload, "minus")
            same = (not plus.get("__probe_error__")
                    and not minus.get("__probe_error__") and plus == minus)
            single_effects = []
            for op in u_graph:
                after = executor.observation([op["id"]], "plus", payload)
                if after != plus:
                    single_effects.append(op["id"])
            plus_lines, minus_lines = set(side_plus["lines"]), set(side_minus["lines"])
            traces.append({
                "input": payload["id"],
                "plus": observation_text(plus),
                "minus": observation_text(minus),
                "a_deletion": ("same" if same else "different"),
                "executed_plus": compress_lines(side_plus["lines"]),
                "executed_minus": compress_lines(side_minus["lines"]),
                "executed_only_plus": compress_lines(plus_lines - minus_lines),
                "executed_only_minus": compress_lines(minus_lines - plus_lines),
                "u_graph_single_delete_changes": single_effects,
                "unexplained_by_u_base": bool(not same and not single_effects),
                "trace_plus_lines": side_plus["lines"],
                "trace_minus_lines": side_minus["lines"],
            })

        prompt = build_prompt(cid, rel, a_line, a_code, public, catalog,
                              graph, u_graph, traces, len(payloads))
        messages = [
            {"role": "system", "content": (
                "You analyse Python masking relations. Return one JSON object "
                "only. Use exact executable operation ids from U_ast; control "
                "regions and function boundaries are not operations.")},
            {"role": "user", "content": prompt},
        ]
        print(f"[{cid}] prompt chars={len(prompt)} U_ast={len(ast_exec)} "
              f"U_graph={len(u_graph)}", flush=True)
        if args.dry_run:
            tasks[cid] = {
                "task_id": cid, "mechanism": spec["mechanism"],
                "u_ast_counts": catalog["counts"],
                "u_ast_ids": sorted(ast_exec),
                "u_graph": u_graph,
                "prompt_chars": len(prompt),
                "prompt": messages,
                "traces": traces,
                "graph_stats": graph.get("stats"),
            }
            print(f"[{cid}] dry-run catalog/pretrace done", flush=True)
            continue

        call_started = time.perf_counter()
        try:
            response = client.chat(messages, purpose=f"cd_v2_{cid}",
                                   json_mode=True)
            call = {
                "ok": True, "messages": messages,
                "raw_response": response.content, "stats": response.stats,
                "wall_seconds": round(time.perf_counter() - call_started, 3),
            }
            totals["qwen_calls"] += 1
            totals["new_prompt_tokens"] += response.stats.get(
                "prompt_tokens") or 0
            totals["new_completion_tokens"] += response.stats.get(
                "completion_tokens") or 0
        except Exception as exc:  # noqa: BLE001
            call = {
                "ok": False, "messages": messages, "raw_response": "",
                "stats": None,
                "wall_seconds": round(time.perf_counter() - call_started, 3),
                "error": f"{type(exc).__name__}: {exc}",
            }
            tasks[cid] = {
                "task_id": cid, "mechanism": spec["mechanism"],
                "u_ast": catalog, "u_graph": u_graph, "traces": traces,
                "call": call, "status": "MODEL_UNAVAILABLE",
            }
            print(f"[{cid}] MODEL_UNAVAILABLE: {call['error']}", flush=True)
            break

        parsed_answer = parse_answer(call["raw_response"])
        qwen = collect_qwen(parsed_answer["object"], ast_exec, u_graph_map,
                            controls) if parsed_answer["ok"] else {
            "candidates": [], "rejected_candidates": [],
            "mapping": [], "candidate_sets": [], "rejected_sets": [],
            "stats": {"proposed": 0, "mapped": 0, "rejected": 0,
                      "sets_proposed": 0, "sets_accepted": 0,
                      "sets_rejected": 0},
        }
        u_qwen = qwen["candidates"]
        u_union = union_ops(u_graph, u_qwen)
        executor.set_universe(u_union)
        union_ids = [op["id"] for op in u_union]
        union_map = {op["id"]: op for op in u_union}

        # Single-delete signatures: never used to drop a candidate in v2.
        pruning = {"policy": "retain_all_graph_and_qwen_candidates",
                   "candidates": [], "u_ast_not_selected": []}
        for op in u_union:
            sig, changed, total = _signature(executor, op, payloads)
            pruning["candidates"].append({
                "id": op["id"],
                "sources": op.get("sources", []),
                "changed_cells": changed,
                "cells": total,
                "zero_effect": changed == 0,
                "retained_reason": (
                    "qwen_candidate_for_verification"
                    if "qwen" in op.get("sources", [])
                    else "graph_candidate_retained_even_if_zero_effect"),
            })
        selected_ids = {op["id"] for op in u_union}
        pruning["u_ast_not_selected"] = [
            {"id": op["id"], "reason": "not_proposed_by_graph_or_qwen"}
            for op in catalog["executable"] if op["id"] not in selected_ids]

        # C0 diagnostics for the NetworkX pruning claim (and the other tasks).
        executor.set_universe(c0["universe"])
        c0_diag = []
        for op in c0["universe"]:
            sig, changed, total = _signature(executor, op, payloads)
            c0_diag.append({"id": op["id"], "changed_cells": changed,
                            "cells": total, "zero_effect": changed == 0})
        executor.set_universe(u_union)

        # Public masking-input detection: no hidden reference is read here.
        public_masking = []
        for payload in payloads:
            plus = executor.observation([], "plus", payload)
            minus = executor.observation([], "minus", payload)
            executes = executor.a_executes(payload)
            masked_empty = bool(not plus.get("__probe_error__")
                                and not minus.get("__probe_error__")
                                and plus.get("outcome") == "return"
                                and plus == minus)
            if executes and masked_empty:
                public_masking.append(payload)

        all_search_sets = []
        search_rows = {}
        verification_rows = {}
        for payload in public_masking:
            hypotheses = {"msms": [
                {"kept_ops": item["kept_operations"]}
                for item in qwen["candidate_sets"][:8]], "mmbs": []}
            search_started = time.perf_counter()
            result = search_relations_role_separated(
                executor, payload, union_ids, budget=BUDGET,
                hypotheses=hypotheses, max_hypothesis_probes_per_role=3)
            result["wall_seconds"] = round(time.perf_counter() - search_started, 3)
            search_rows[payload["id"]] = result
            all_search_sets.extend(result.get("msms_ids") or [])
            search_sets = result.get("msms_ids") or []
            candidates = candidate_sets_for_verification(
                qwen["candidate_sets"], u_qwen, u_graph, search_sets)
            verification = verify_candidate_sets(
                executor, union_ids, candidates, payload)
            verification["search_incomplete"] = not result.get("complete")
            verification["search_subsets_total"] = result.get("subsets_total")
            verification["search_evaluations"] = result.get("evaluations")
            verification["search_budget"] = BUDGET
            verification["SEARCH_INCOMPLETE"] = (
                "SEARCH_INCOMPLETE" if not result.get("complete") else None)
            verification_rows[payload["id"]] = verification
            if not result.get("complete"):
                totals["search_incomplete_inputs"] += 1

        # Hidden data is read only below this line.
        reference = reference_for(cid)
        enumeration = load(SD / "evidence" / cid / "enumeration.json")
        spans = block_spans(enumeration)
        detail, scoring = [], {
            "masking_inputs": 0, "exact": 0, "present": 0,
            "false_relations": 0, "unmatched_sets": 0,
        }
        for payload in public_masking:
            input_key = key_map[payload["id"]]
            hidden = reference["inputs"][input_key]
            if hidden.get("role") != "masking":
                continue
            scoring["masking_inputs"] += 1
            verified = verification_rows[payload["id"]]
            result = score_sets(verified["confirmed"], union_map, spans,
                                hidden["msms"])
            detail.append({
                "input": input_key, "public_id": payload["id"],
                "hidden": hidden["msms"],
                "confirmed": verified["confirmed"],
                "candidate_sets": verified["sets"],
                "score": result,
            })
            scoring["exact"] += int(result["msms_exact"])
            scoring["present"] += int(result["hidden_msms_present"])
            scoring["false_relations"] += result["false_relations"]
            scoring["unmatched_sets"] += result["unmatched_sets"]

        blocks = set(spans)
        recall = {
            "u_graph": block_cover(u_graph, spans),
            "u_graph_only": block_cover(u_graph_only, spans),
            "u_ast": block_cover(catalog["executable"], spans),
            "u_qwen": block_cover(u_qwen, spans),
            "u_union": block_cover(u_union, spans),
        }
        baseline = {
            "c0_exact": c0["scoring"]["msms_exact"],
            "c0_false": c0["scoring"]["false_relations"],
            "c0_probes": c0["cost"]["probe_executions_algorithm"],
            "direct_exact": (old.get(cid, {}).get("direct", {}).get("exact")),
            "old_full_exact": (old.get(cid, {}).get("full_mace", {}).get("exact")),
            "masking_inputs": len(public_masking),
        }
        wall = round(time.perf_counter() - started, 2)
        totals["tasks"] += 1
        totals["masking_inputs"] += scoring["masking_inputs"]
        totals["c0_exact"] += baseline["c0_exact"] or 0
        totals["direct_exact"] += baseline["direct_exact"] or 0
        totals["old_full_exact"] += baseline["old_full_exact"] or 0
        totals["new_exact"] += scoring["exact"]
        totals["new_present"] += scoring["present"]
        totals["new_false"] += scoring["false_relations"]
        totals["new_unmatched"] += scoring["unmatched_sets"]
        totals["new_probes"] += executor.probe_executions
        totals["new_runtime"] += wall

        record = {
            "task_id": cid,
            "mechanism": spec["mechanism"],
            "status": "OK" if (call.get("ok") and parsed_answer["ok"]) else "INCOMPLETE",
            "public_source_sha256": hashlib.sha256(
                public.encode("utf-8")).hexdigest(),
            "u_ast": catalog,
            "u_graph": u_graph,
            "u_graph_only": u_graph_only,
            "u_qwen": u_qwen,
            "u_union": u_union,
            "qwen": qwen,
            "call": call,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "parsed_answer_ok": parsed_answer["ok"],
            "parsed_answer_error": parsed_answer["error"],
            "traces": traces,
            "pruning": pruning,
            "c0_diagnostics": c0_diag,
            "recall": recall,
            "search": search_rows,
            "verification": verification_rows,
            "scoring": scoring,
            "detail": detail,
            "baseline": baseline,
            "cost": {
                "wall_seconds": wall,
                "probe_executions": executor.probe_executions,
                "variant_builds": executor.variant_builds,
            },
        }
        tasks[cid] = record
        (RUN / "raw" / f"{cid}.json").write_text(json.dumps({
            "task_id": cid, "messages": messages,
            "raw_response": call.get("raw_response"),
            "stats": call.get("stats"), "wall_seconds": call.get("wall_seconds"),
            "prompt_sha256": record["prompt_sha256"],
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        (RUN / "scores" / f"{cid}.json").write_text(json.dumps({
            "task_id": cid, "scoring": scoring, "detail": detail,
            "baseline": baseline, "recall": recall,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[{cid}] U_union={len(u_union)} qwen={len(u_qwen)} "
              f"exact={scoring['exact']}/{scoring['masking_inputs']} "
              f"false={scoring['false_relations']} probes={executor.probe_executions} "
              f"wall={wall}s", flush=True)
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(json.dumps({
            "schema": "mace-candidate-discovery-v2/1",
            "generated_utc": utc(), "model": MODEL,
            "tasks": tasks, "totals": totals,
        }, ensure_ascii=False, indent=2), encoding="utf-8")

    for cid in skipped:
        tasks[cid] = {"task_id": cid, "status": "INCOMPLETE",
                      "reason": "45-minute deadline reached before this task"}

    if args.dry_run:
        print(json.dumps({cid: t.get("u_ast_counts") for cid, t in tasks.items()},
                         indent=1))
        return 0

    # Focus answers are computed from the records, not asserted.
    def focus(cid: str) -> dict:
        t = tasks.get(cid, {})
        return {
            "u_graph": len(t.get("u_graph", [])),
            "u_ast": t.get("u_ast", {}).get("counts", {}).get("executable"),
            "u_qwen": len(t.get("u_qwen", [])),
            "u_union": len(t.get("u_union", [])),
            "new_exact": t.get("scoring", {}).get("exact"),
            "masking_inputs": t.get("scoring", {}).get("masking_inputs"),
            "c0_exact": t.get("baseline", {}).get("c0_exact"),
            "direct_exact": t.get("baseline", {}).get("direct_exact"),
        }

    payload = {
        "schema": "mace-candidate-discovery-v2/1",
        "generated_utc": utc(),
        "mode": "qwen_assisted_candidate_expansion",
        "dataset": {"name": "source-derived controlled (V4-DEV)",
                    "task_count": len(tasks), "researcher_constructed": True},
        "model": {"name": MODEL, "options": {
            "temperature": 0.0, "seed": 42, "num_ctx": NUM_CTX,
            "num_predict": NUM_PREDICT, "retries": 0}},
        "protocol": {
            "same_public_source_and_inputs_as_c0": True,
            "qwen_calls": 1,
            "u_union_rule": "U_graph union U_qwen; U_graph is never removed",
            "u_ast_rule": ("executable statements in A's function and same-file "
                           "call-reachable functions; control regions, function "
                           "boundaries and unsupported nodes are not operations"),
            "search_budget_per_input": BUDGET,
            "search_incomplete": "recorded, never silently pruned",
            "msms": ("targeted strict causal verification: masked observation, "
                     "all proper non-empty subsets checked, UNKNOWN != FALSE"),
            "mmbs": "NOT_SEPARABLE; not scored",
        },
        "totals": totals,
        "focus": {cid: focus(cid) for cid in args.tasks},
        "answers": {
            "q1_qwen_expanded_u": _answer_expand(tasks),
            "q2_bbcode_double": _answer_bbcode(tasks),
            "q3_groff_triple": _answer_groff(tasks),
            "q4_networkx_pruning": _answer_networkx(tasks),
            "q5_beats_c0": _answer_beats(tasks, totals),
        },
        "tasks": tasks,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    (RUN / "results.json").write_text(json.dumps(payload, ensure_ascii=False,
                                                 indent=2), encoding="utf-8")
    print(f"wrote {OUT}")
    return 0


def _answer_expand(tasks: Dict[str, dict]) -> str:
    rows = []
    for cid, t in tasks.items():
        new = [op for op in t.get("u_qwen", [])]
        cov = t.get("recall", {})
        rows.append(f"{cid}: +{len(new)} qwen ops; "
                    f"U_graph recall={cov.get('u_graph', {}).get('recall')}, "
                    f"U_union recall={cov.get('u_union', {}).get('recall')}")
    return "; ".join(rows)


def _answer_bbcode(tasks: Dict[str, dict]) -> str:
    t = tasks.get("sd_pygments_bbcode70_italic")
    if not t:
        return "not run"
    return (f"bbcode70: new exact={t['scoring']['exact']}/"
            f"{t['scoring']['masking_inputs']}; U_qwen="
            f"{[op['id'] for op in t['u_qwen']]}")


def _answer_groff(tasks: Dict[str, dict]) -> str:
    t = tasks.get("sd_pygments_groff73_italic")
    if not t:
        return "not run"
    return (f"groff73: new exact={t['scoring']['exact']}/"
            f"{t['scoring']['masking_inputs']}; U_qwen="
            f"{[op['id'] for op in t['u_qwen']]}")


def _answer_networkx(tasks: Dict[str, dict]) -> str:
    t = tasks.get("sd_networkx_gexf448_slices")
    if not t:
        return "not run"
    diag = {row["id"]: row for row in t.get("c0_diagnostics", [])}
    has_451 = any("451-451" in k for k in diag)
    return (f"networkx: new exact={t['scoring']['exact']}/"
            f"{t['scoring']['masking_inputs']}; correct candidate 451 in C0="
            f"{has_451}; U_qwen={[op['id'] for op in t['u_qwen']]}; "
            f"C0 signatures={diag}")


def _answer_beats(tasks: Dict[str, dict], totals: Dict) -> str:
    return (f"new exact={totals['new_exact']}/{totals['masking_inputs']} "
            f"vs C0 {totals['c0_exact']}/{totals['masking_inputs']} "
            f"vs Direct {totals['direct_exact']}/{totals['masking_inputs']}; "
            f"beats C0={totals['new_exact'] > totals['c0_exact']}")


if __name__ == "__main__":
    raise SystemExit(main())
