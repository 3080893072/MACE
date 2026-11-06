"""Second static pass: attribute / subscript / augmented / cross-function.

The first pass only accepts one-line local-name assignments in the same
function.  This pass adds mechanisms the user asked for:

* ``attribute``: object state (``self.x = ...`` then ``self.x = ...``);
* ``subscript``: container state (``d[k] = ...``);
* ``augassign``: loop-carried accumulation;
* ``multiline``: a statement whose value spans lines;
* ``cross_function``: A is a local name in F and a callee reached from F
  assigns the same local name (direct call, method call, or class
  instantiation followed by ``__init__``).

Rows use the same shape as the first pass so the existing screening pipeline
can consume them, with two extra keys: ``mechanism`` and ``callee``.
"""
from __future__ import annotations

import ast
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

import benchmark_real_v4.pipeline as pipeline
from benchmark_real_v4.config import CANDIDATES, EVIDENCE, PROJECTS

MORE_WORK_ROOT = Path("<local-path>")
MORE_STATIC = CANDIDATES / "candidates_static_more.json"
MORE_FUNNEL = EVIDENCE / "screening_funnel_more.json"
MORE_ROWS = EVIDENCE / "screening_rows_more"

MORE_BUDGET = {
    "max_candidates_reviewed": 150,
    "max_targeted_minus_runs": 150,
    "max_full_suite_minus_runs": 50,
    "targeted_timeout": 180,
    "full_timeout": 900,
}

Key = Tuple[str, str]


def _target_key(node: ast.AST) -> tuple[Key, str, Any] | None:
    """Return (key, receiver_name, literal_index) for a single-target store."""
    if isinstance(node, ast.Assign):
        if len(node.targets) != 1:
            return None
        target = node.targets[0]
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        target = node.target
    else:
        return None
    if isinstance(target, ast.Name):
        return ("name", target.id), "", None
    if isinstance(target, ast.Attribute):
        base = target.value
        receiver = base.id if isinstance(base, ast.Name) else ""
        return ("attr", target.attr), receiver, None
    if isinstance(target, ast.Subscript):
        base = target.value
        receiver = ""
        if isinstance(base, ast.Name):
            receiver = base.id
        elif isinstance(base, ast.Attribute):
            receiver = base.attr
        index = target.slice
        literal = None
        if isinstance(index, ast.Constant) and isinstance(
                index.value, (str, int, float, bool, type(None))):
            literal = index.value
        return ("sub", receiver or "subscript"), receiver, literal
    return None


def _key_of(node: ast.AST) -> Key | None:
    parsed = _target_key(node)
    return parsed[0] if parsed else None


def _key_json(key: Key) -> str:
    return key[0] + ":" + key[1]


def _assignments(fn: ast.AST) -> List[Dict[str, Any]]:
    nodes = pipeline._local_nodes(fn)
    out = []
    for node in nodes:
        parsed = _target_key(node)
        if parsed is None:
            continue
        key, obj, index = parsed
        out.append({
            "key": key,
            "obj": obj,
            "index": index,
            "line": int(node.lineno),
            "end_line": int(getattr(node, "end_lineno", node.lineno) or node.lineno),
            "kind": type(node).__name__,
            "node": node,
        })
    return out


def _reads(nodes: List[ast.AST], key: Key, start: int, end: int) -> bool:
    """Any load of the target between A and its first later write."""
    for node in nodes:
        if key[0] == "attr":
            hit = isinstance(node, ast.Attribute) and node.attr == key[1]
        else:
            hit = isinstance(node, ast.Name) and node.id == key[1]
        if not hit:
            continue
        if isinstance(node.ctx, ast.Load) and start < node.lineno < end:
            return True
    return False


def _code(lines: List[str], first: int, last: int) -> str:
    if first == last:
        return lines[first - 1].strip()
    return lines[first - 1].strip() + "  # multi-line"


def _classes(tree: ast.Module) -> Dict[str, ast.ClassDef]:
    return {node.name: node for node in ast.walk(tree)
            if isinstance(node, ast.ClassDef)}


def _callees(fn: ast.FunctionDef, classes: Dict[str, ast.ClassDef],
             functions: Dict[str, ast.AST]) -> List[ast.AST]:
    """Functions/methods directly reachable from F by name or instantiation."""
    out: List[ast.AST] = []
    called = set()
    for node in ast.walk(fn):
        if not isinstance(node, ast.Call):
            continue
        func = node.func
        if isinstance(func, ast.Name):
            called.add(func.id)
        elif isinstance(func, ast.Attribute):
            called.add(func.attr)
    for name in called:
        if name in functions:
            out.append(functions[name])
        if name in classes:
            out.extend(m for m in classes[name].body
                       if isinstance(m, (ast.FunctionDef, ast.AsyncFunctionDef)))
    return out


def scan_project_more(project_id: str) -> List[Dict[str, Any]]:
    cfg = PROJECTS[project_id]
    rows: List[Dict[str, Any]] = []
    for rel in cfg["scan_files"]:
        path = cfg["root"] / rel
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        lines = text.splitlines()
        classes = _classes(tree)
        functions = {n.name: n for n in tree.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
        for fn in [n for n in ast.walk(tree)
                   if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
            nodes = pipeline._local_nodes(fn)
            local = _assignments(fn)
            by_key: Dict[Key, List[Dict[str, Any]]] = {}
            for item in local:
                by_key.setdefault(item["key"], []).append(item)
            for key, items in by_key.items():
                items = sorted(items, key=lambda item: item["line"])
                if len(items) < 2:
                    continue
                for index, item in enumerate(items[:-1]):
                    later = [other for other in items[index + 1:]
                             if other["line"] > item["line"]]
                    if not later:
                        continue
                    first_later = later[0]["line"]
                    multi = item["end_line"] != item["line"]
                    mech = {
                        ("attr",): "attribute",
                        ("sub",): "subscript",
                    }.get((key[0],), None)
                    if item["kind"] == "AugAssign":
                        mech = "augassign"
                    elif multi:
                        mech = "multiline"
                    if mech is None:
                        continue  # plain same-function names were pass 1
                    rows.append(_row(project_id, cfg, rel, fn, lines,
                                     item, later, nodes, mech, None,
                                     path.read_bytes()))
            # cross-function: same local name assigned in a directly reached
            # callee.  Only plain local names, to keep the pool interpretable.
            for key, items in by_key.items():
                if key[0] != "name" or len(items) != 1:
                    continue
                item = items[0]
                for callee in _callees(fn, classes, functions):
                    target_items = [other for other in _assignments(callee)
                                    if other["key"] == key]
                    if not target_items:
                        continue
                    rows.append(_row(project_id, cfg, rel, fn, lines,
                                     item, target_items, nodes,
                                     "cross_function", callee.name,
                                     path.read_bytes()))
                    break
    return rows


def _row(project_id: str, cfg: Dict[str, Any], rel: str, fn: ast.AST,
         lines: List[str], item: Dict[str, Any], later: List[Dict[str, Any]],
         nodes: List[ast.AST], mechanism: str, callee: str | None,
         raw: bytes) -> Dict[str, Any]:
    key = item["key"]
    first_later = later[0]["line"]
    reads = _reads(nodes, key, item["line"], first_later)
    later_rows = [{
        "line": other["line"],
        "end_line": other["end_line"],
        "kind": other["kind"],
        "code": _code(lines, other["line"], other["end_line"]),
        "key_obj": other["obj"],
        "key_index": other["index"],
        "reads_A": any(isinstance(n, ast.Name) and n.id == key[1]
                       and isinstance(n.ctx, ast.Load)
                       for n in ast.walk(other["node"])),
    } for other in later]
    return {
        "candidate_id": (f"{project_id}:{rel}:{item['line']}:"
                         f"{mechanism}:{key[1]}"),
        "project_id": project_id,
        "project": cfg["project"],
        "version": cfg["version"],
        "file": rel,
        "function": getattr(fn, "name", "<lambda>"),
        "variable": key[1],
        "target_key": _key_json(key),
        "key_kind": key[0],
        "key_obj": item["obj"],
        "key_index": item["index"],
        "mechanism": mechanism,
        "callee": callee,
        "target_A": {
            "line": item["line"],
            "end_line": item["end_line"],
            "kind": item["kind"],
            "code": _code(lines, item["line"], item["end_line"]),
        },
        "later_assignments": later_rows,
        "read_between_A_and_first_later": [item["line"]] if reads else [],
        "static_shape": {
            **pipeline._scope_depth(nodes, item["line"]),
            "read_before_later_write": bool(reads),
            "later_write_reads_A": any(row["reads_A"] for row in later_rows),
            "later_write_is_plain_assign": later[0]["kind"] == "Assign",
            "cross_function": mechanism == "cross_function",
            "mechanism": mechanism,
        },
        "source_sha256": hashlib.sha256(raw).hexdigest(),
    }


def cmd_scan() -> int:
    rows: List[Dict[str, Any]] = []
    for project_id in PROJECTS:
        rows.extend(scan_project_more(project_id))
    rows.sort(key=lambda row: (row["project_id"], row["file"],
                               row["target_A"]["line"], row["variable"]))
    seen = set()
    unique = []
    for row in rows:
        if row["candidate_id"] in seen:
            continue
        seen.add(row["candidate_id"])
        unique.append(row)
    MORE_STATIC.parent.mkdir(parents=True, exist_ok=True)
    MORE_STATIC.write_text(json.dumps({
        "protocol": "benchmark_real_v4_more",
        "candidates": unique,
        "counts": {pid: sum(1 for row in unique
                            if row["project_id"] == pid)
                   for pid in PROJECTS},
        "mechanisms": {},
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    counts: Dict[str, int] = {}
    for row in unique:
        counts[row["mechanism"]] = counts.get(row["mechanism"], 0) + 1
    print(json.dumps({"path": str(MORE_STATIC), "total": len(unique),
                      "mechanisms": counts,
                      "counts": {pid: sum(1 for row in unique
                                          if row["project_id"] == pid)
                                 for pid in PROJECTS}},
                     ensure_ascii=False, indent=2))
    return 0


def cmd_screen() -> int:
    static_path = MORE_STATIC
    subset = [item for item in os.environ.get(
        "MACE_SCREEN_PROJECTS", "").split(",") if item]
    if subset:
        data = json.loads(MORE_STATIC.read_text(encoding="utf-8"))
        wanted = set(subset)
        data["candidates"] = [row for row in data["candidates"]
                              if row["project_id"] in wanted]
        data["counts"] = {pid: sum(1 for row in data["candidates"]
                                   if row["project_id"] == pid)
                          for pid in subset}
        static_path = MORE_STATIC.with_name(
            "candidates_static_more_subset.json")
        static_path.write_text(json.dumps(data, ensure_ascii=False, indent=2)
                               + "\n", encoding="utf-8")
        pipeline.PROJECTS = {pid: PROJECTS[pid] for pid in subset}
    pipeline.STATIC_PATH = static_path
    pipeline.FUNNEL_PATH = MORE_FUNNEL
    pipeline.ROWS_DIR = MORE_ROWS
    pipeline.BUDGET = MORE_BUDGET
    # A separate work root lets this pass run beside the first-pass review,
    # which owns WORK_ROOT/{project}_minus_base.
    pipeline.WORK_ROOT = MORE_WORK_ROOT
    return pipeline.cmd_screen()


def cmd_report() -> int:
    pipeline.STATIC_PATH = MORE_STATIC
    pipeline.FUNNEL_PATH = MORE_FUNNEL
    pipeline.ROWS_DIR = MORE_ROWS
    pipeline.BUDGET = MORE_BUDGET
    return pipeline.cmd_report()


def cmd_qualify() -> int:
    """Run the shared qualifier against the second-pass funnel."""
    import benchmark_real_v4.qualify as qualify

    qualify.FUNNEL = MORE_FUNNEL
    qualify.ROWS_DIR = MORE_ROWS
    sys.argv = [sys.argv[0], *sys.argv[2:]]
    return qualify.main()


def main() -> int:
    if len(sys.argv) < 2 or sys.argv[1] not in {
            "scan", "screen", "report", "qualify"}:
        print("usage: python -m benchmark_real_v4.scan_more "
              "scan|screen|report|qualify [...]")
        return 2
    return {"scan": cmd_scan, "screen": cmd_screen,
            "report": cmd_report, "qualify": cmd_qualify}[sys.argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main())
