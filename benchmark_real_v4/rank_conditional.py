"""Rank static candidates whose masking write is conditional.

Condition 5 of a FULL_MASKING_STORY needs an input where deleting A is
observable.  Such an input exists naturally when the later overwrite that
masks A is itself inside an ``if``/``while``/``try`` body: a legal input that
takes the other path keeps A's value.  This module does not claim masking; it
orders the review queue by that structural signal, so the expensive test runs
go to the candidates where an exposing counterexample is plausible.

Usage::

    python -m benchmark_real_v4.rank_conditional
"""
from __future__ import annotations

import ast
import json
from pathlib import Path
from typing import Any, Dict, List

from benchmark_real_v4.config import CANDIDATES, PROJECTS, V4

SOURCES = [
    CANDIDATES / "candidates_static.json",
    CANDIDATES / "candidates_static_more.json",
    CANDIDATES / "candidates_static_state.json",
]
OUT = V4 / "candidates" / "ranked_conditional.json"

GUARDS = (ast.If, ast.While, ast.Try, ast.For, ast.AsyncFor, ast.With,
          ast.AsyncWith, ast.ExceptHandler)


def _nodes_by_line(tree: ast.Module) -> Dict[int, List[ast.AST]]:
    out: Dict[int, List[ast.AST]] = {}
    for node in ast.walk(tree):
        if hasattr(node, "lineno"):
            out.setdefault(int(node.lineno), []).append(node)
    return out


def _parents(tree: ast.Module) -> Dict[int, ast.AST]:
    parents: Dict[int, ast.AST] = {}
    for node in ast.walk(tree):
        for child in ast.iter_child_nodes(node):
            parents[id(child)] = node
    return parents


def _guards(node: ast.AST, parents: Dict[int, ast.AST],
            stop_line: int | None = None) -> List[str]:
    labels = []
    current = parents.get(id(node))
    while current is not None:
        if isinstance(current, ast.FunctionDef) or isinstance(
                current, ast.AsyncFunctionDef):
            break
        if isinstance(current, ast.If):
            labels.append("if")
        elif isinstance(current, ast.While):
            labels.append("while")
        elif isinstance(current, ast.Try):
            labels.append("try")
        elif isinstance(current, (ast.For, ast.AsyncFor)):
            labels.append("for")
        elif isinstance(current, (ast.With, ast.AsyncWith)):
            labels.append("with")
        elif isinstance(current, ast.ExceptHandler):
            labels.append("except")
        current = parents.get(id(current))
    return labels


def _statement_at(tree: ast.Module, line: int) -> ast.AST | None:
    best = None
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and int(node.lineno) == line:
            if best is None or int(getattr(node, "end_lineno", line)) < int(
                    getattr(best, "end_lineno", line)):
                best = node
    return best


def analyse(row: Dict[str, Any]) -> Dict[str, Any] | None:
    cfg = PROJECTS.get(row["project_id"])
    if not cfg:
        return None
    path = cfg["root"] / row["file"]
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return None
    parents = _parents(tree)
    a_stmt = _statement_at(tree, int(row["target_A"]["line"]))
    a_guards = _guards(a_stmt, parents) if a_stmt is not None else []
    later = []
    for item in row["later_assignments"]:
        stmt = _statement_at(tree, int(item["line"]))
        guards = _guards(stmt, parents) if stmt is not None else []
        later.append({
            "line": item["line"],
            "guards": guards,
            "conditional": bool(guards),
            "same_guard_as_A": bool(guards) and guards == a_guards,
        })
    conditional = any(item["conditional"] and not item["same_guard_as_A"]
                      for item in later)
    score = (3 if conditional else 0)
    score += 2 if row["static_shape"].get("read_before_later_write") else 0
    score += 1 if row["static_shape"].get("later_write_reads_A") else 0
    score += 1 if "cross_method" == row.get("mechanism") else 0
    return {
        "candidate_id": row["candidate_id"],
        "project_id": row["project_id"],
        "file": row["file"],
        "function": row["function"],
        "mechanism": row.get("mechanism", "name-overwrite"),
        "A": row["target_A"],
        "A_guards": a_guards,
        "later": later,
        "conditional_masking_possible": conditional,
        "score": score,
    }


def main() -> int:
    seen = set()
    rows: List[Dict[str, Any]] = []
    for source in SOURCES:
        if not source.exists():
            continue
        for row in json.loads(source.read_text(encoding="utf-8"))["candidates"]:
            if row["candidate_id"] in seen:
                continue
            seen.add(row["candidate_id"])
            result = analyse(row)
            if result is not None:
                result["exposing_input_plausible"] = bool(
                    result["conditional_masking_possible"]
                    and row["static_shape"].get("read_before_later_write"))
                rows.append(result)
    rows.sort(key=lambda item: (-item["score"], item["candidate_id"]))
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps({"candidates": rows}, ensure_ascii=False,
                              indent=2) + "\n", encoding="utf-8")
    top = [item for item in rows if item["exposing_input_plausible"]]
    print(json.dumps({
        "path": str(OUT),
        "total": len(rows),
        "conditional_masking_possible": sum(
            1 for item in rows if item["conditional_masking_possible"]),
        "exposing_input_plausible": len(top),
        "top": [{"id": item["candidate_id"], "score": item["score"],
                 "A": item["A"]["code"], "later": item["later"]}
                for item in top[:20]],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
