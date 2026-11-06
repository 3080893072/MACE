"""Third static pass: object state written across methods.

The first two passes only pair assignments to the same syntactic key inside
one function (or a same-named local in a directly called function).  That
misses the common object-state pattern the user asked for:

    self.mode = "default"      # A in method F
    ...
    self._refresh()            # g() assigns self.mode again

Here the write that masks A lives in another method of the same class, and
the only connection between the two writes is the receiver object.  Legal
inputs that skip the refresh call are the natural exposing counterexamples.

Rows keep the v4 screening shape.  The candidate key is the attribute tuple
plus the masking method, so two methods writing the same attribute produce
separate, verifiable candidates.

Usage::

    python -m benchmark_real_v4.scan_state scan
    python -m benchmark_real_v4.scan_state screen
    python -m benchmark_real_v4.scan_state qualify --all-survivors
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import benchmark_real_v4.pipeline as pipeline
import benchmark_real_v4.scan_more as scan_more
from benchmark_real_v4.config import CANDIDATES, EVIDENCE, PROJECTS

STATE_WORK_ROOT = Path("<local-path>")
STATE_STATIC = CANDIDATES / "candidates_static_state.json"
STATE_FUNNEL = EVIDENCE / "screening_funnel_state.json"
STATE_ROWS = EVIDENCE / "screening_rows_state"

STATE_BUDGET = {
    "max_candidates_reviewed": 80,
    "max_targeted_minus_runs": 80,
    "max_full_suite_minus_runs": 40,
    "targeted_timeout": 180,
    "full_timeout": 900,
}


def _classes(tree: ast.Module) -> List[ast.ClassDef]:
    return [node for node in ast.walk(tree) if isinstance(node, ast.ClassDef)]


def _methods(cls: ast.ClassDef) -> Dict[str, ast.AST]:
    return {node.name: node for node in cls.body
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))}


def _self_attrs(fn: ast.AST, receiver: str) -> List[Dict[str, Any]]:
    out = []
    for node in pipeline._local_nodes(fn):
        parsed = scan_more._target_key(node)
        if parsed is None:
            continue
        key, obj, index = parsed
        if key[0] != "attr" or obj != receiver:
            continue
        out.append({
            "key": key, "obj": obj, "index": index,
            "line": int(node.lineno),
            "end_line": int(getattr(node, "end_lineno", node.lineno)),
            "kind": type(node).__name__, "node": node,
        })
    return out


def _self_calls(fn: ast.AST, receiver: str) -> List[Tuple[int, str]]:
    calls = []
    for node in ast.walk(fn):
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute):
            base = node.func.value
            if isinstance(base, ast.Name) and base.id == receiver:
                calls.append((int(node.lineno), node.func.attr))
    return calls


def scan_project_state(project_id: str) -> List[Dict[str, Any]]:
    cfg = PROJECTS[project_id]
    rows: List[Dict[str, Any]] = []
    for rel in cfg["scan_files"]:
        path = cfg["root"] / rel
        raw = path.read_bytes()
        text = raw.decode("utf-8")
        tree = ast.parse(text)
        lines = text.splitlines()
        for cls in _classes(tree):
            methods = _methods(cls)
            by_attr: Dict[Tuple[str, str], List[Tuple[str, Dict[str, Any]]]] = {}
            for name, fn in methods.items():
                for item in _self_attrs(fn, "self"):
                    by_attr.setdefault(item["key"], []).append((name, item))
            for name, fn in methods.items():
                calls = _self_calls(fn, "self")
                for item in _self_attrs(fn, "self"):
                    others = [(other_name, other)
                              for other_name, other in by_attr[item["key"]]
                              if other_name != name]
                    if not others:
                        continue
                    # A call to the writing method after A is the cleanest
                    # masking story; absent one, keep the cross-method write
                    # and let execution evidence decide.
                    called = [(line, callee) for line, callee in calls
                              if line > item["line"]]
                    call_line, callee = 0, others[0][0]
                    for line, candidate in called:
                        if any(candidate == other_name
                               for other_name, _ in others):
                            call_line, callee = line, candidate
                            break
                    if call_line == 0:
                        # Without a call after A the masking write is not part
                        # of this execution; it cannot be a masking story at
                        # the observation point (function return).
                        continue
                    target_items = [other for other_name, other in others
                                    if other_name == callee] or \
                                   [other for _, other in others]
                    rows.append(_row(project_id, cfg, rel, cls, fn, item,
                                     target_items, call_line, callee,
                                     lines, raw))
    return rows


def _row(project_id: str, cfg: Dict[str, Any], rel: str,
         cls: ast.ClassDef, fn: ast.AST, item: Dict[str, Any],
         later: List[Dict[str, Any]], call_line: int, callee: str,
         lines: List[str], raw: bytes) -> Dict[str, Any]:
    key = item["key"]
    nodes = pipeline._local_nodes(fn)
    first_later = later[0]["line"]
    # For a cross-method write the masking line can sit earlier in the file
    # than A.  Look for a read of the attribute anywhere after A in F.
    reads = scan_more._reads(
        nodes, key, item["line"],
        int(getattr(fn, "end_lineno", item["line"]) or item["line"]))
    later_rows = [{
        "line": other["line"],
        "end_line": other["end_line"],
        "kind": other["kind"],
        "code": scan_more._code(lines, other["line"], other["end_line"]),
        "key_obj": other["obj"],
        "key_index": other["index"],
        "reads_A": False,
        "via_call_at": call_line,
    } for other in later]
    return {
        "candidate_id": (f"{project_id}:{rel}:{item['line']}:cross_method:"
                         f"{key[1]}__{callee}"),
        "project_id": project_id,
        "project": cfg["project"],
        "version": cfg["version"],
        "file": rel,
        "function": getattr(fn, "name", "<lambda>"),
        "variable": key[1],
        "target_key": scan_more._key_json(key),
        "key_kind": key[0],
        "key_obj": item["obj"],
        "key_index": item["index"],
        "mechanism": "cross_method",
        "callee": callee,
        "class_name": cls.name,
        "target_A": {
            "line": item["line"],
            "end_line": item["end_line"],
            "kind": item["kind"],
            "code": scan_more._code(lines, item["line"], item["end_line"]),
        },
        "later_assignments": later_rows,
        "read_between_A_and_first_later": [item["line"]] if reads else [],
        "static_shape": {
            **pipeline._scope_depth(nodes, item["line"]),
            "read_before_later_write": bool(reads),
            "later_write_reads_A": False,
            "later_write_is_plain_assign": later[0]["kind"] == "Assign",
            "cross_function": True,
            "mechanism": "cross_method",
            "call_line": call_line,
            "callee_class": cls.name,
        },
        "source_sha256": hashlib.sha256(raw).hexdigest(),
    }


def cmd_scan() -> int:
    rows: List[Dict[str, Any]] = []
    for project_id in PROJECTS:
        rows.extend(scan_project_state(project_id))
    rows.sort(key=lambda row: (row["project_id"], row["file"],
                               row["target_A"]["line"], row["variable"]))
    seen = set()
    unique = []
    for row in rows:
        if row["candidate_id"] in seen:
            continue
        seen.add(row["candidate_id"])
        unique.append(row)
    counts: Dict[str, int] = {}
    for row in unique:
        counts[row["project_id"]] = counts.get(row["project_id"], 0) + 1
    STATE_STATIC.parent.mkdir(parents=True, exist_ok=True)
    STATE_STATIC.write_text(json.dumps({
        "protocol": "benchmark_real_v4_state",
        "candidates": unique,
        "counts": counts,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"path": str(STATE_STATIC), "total": len(unique),
                      "counts": counts}, ensure_ascii=False, indent=2))
    return 0


def cmd_screen() -> int:
    pipeline.STATIC_PATH = STATE_STATIC
    pipeline.FUNNEL_PATH = STATE_FUNNEL
    pipeline.ROWS_DIR = STATE_ROWS
    pipeline.BUDGET = STATE_BUDGET
    pipeline.WORK_ROOT = STATE_WORK_ROOT
    return pipeline.cmd_screen()


def cmd_qualify() -> int:
    import benchmark_real_v3.variant_lab as variant_lab
    import benchmark_real_v4.qualify as qualify

    qualify.FUNNEL = STATE_FUNNEL
    qualify.ROWS_DIR = STATE_ROWS
    variant_lab.WORK_ROOT = STATE_WORK_ROOT
    variant_lab.VARIANT_ROOT = STATE_WORK_ROOT / "variants"
    sys.argv = [sys.argv[0], *sys.argv[2:]]
    return qualify.main()


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in {"scan", "screen", "qualify"}:
        print("usage: python -m benchmark_real_v4.scan_state scan|screen|qualify")
        return 2
    return {"scan": cmd_scan, "screen": cmd_screen,
            "qualify": cmd_qualify}[sys.argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main())
