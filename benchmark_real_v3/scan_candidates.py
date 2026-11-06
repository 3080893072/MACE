"""Static deletion-candidate extraction for benchmark v3.

This is a generator, not a masking detector.  It finds local variables with
more than one assignment in the same function and emits a candidate for each
earlier assignment A that has a later assignment B.  Every emitted candidate
is later subjected to original-test execution; no candidate is promoted just
because it looks plausible statically.
"""
from __future__ import annotations

import ast
import hashlib
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from benchmark_real_v3.config import (
    CANDIDATES,
    EXCLUDED_LINES,
    PROJECTS,
)


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def tree_sha256(root: Path, package: str, source_dir: str) -> str:
    base = root / source_dir / package
    digest = hashlib.sha256()
    for path in sorted(base.rglob("*.py")):
        digest.update(path.relative_to(root).as_posix().encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _simple_assignment(node: ast.AST) -> Tuple[str, int] | None:
    """Return (target_name, line) for a one-line local-name assignment."""
    if isinstance(node, ast.Assign):
        if getattr(node, "end_lineno", node.lineno) != node.lineno:
            return None
        if len(node.targets) != 1 or not isinstance(node.targets[0], ast.Name):
            return None
        return node.targets[0].id, node.lineno
    if isinstance(node, ast.AnnAssign):
        if getattr(node, "end_lineno", node.lineno) != node.lineno:
            return None
        if not isinstance(node.target, ast.Name):
            return None
        return node.target.id, node.lineno
    return None


def _assignment_code(lines: List[str], line: int) -> str:
    return lines[line - 1].strip()


def _scope_depth(nodes: List[ast.AST], line: int) -> Dict[str, bool]:
    """Return rough structural flags for the statement at ``line``."""
    flags = {"in_loop": False, "in_try": False, "in_if": False}
    for child in nodes:
        if not isinstance(child, ast.stmt):
            continue
        if not (child.lineno <= line <= getattr(child, "end_lineno", child.lineno)):
            continue
        if isinstance(child, (ast.For, ast.While, ast.AsyncFor)):
            flags["in_loop"] = True
        elif isinstance(child, ast.Try):
            flags["in_try"] = True
        elif isinstance(child, ast.If):
            flags["in_if"] = True
    return flags


def _local_nodes(function: ast.AST) -> List[ast.AST]:
    """Nodes belonging to ``function`` itself, excluding nested scopes.

    ``ast.walk`` descends into nested functions and lambdas, which previously
    attributed their assignments to every enclosing function as well.  Only
    the innermost function may claim an assignment.
    """
    out: List[ast.AST] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            out.append(child)
            if isinstance(
                child,
                (ast.FunctionDef, ast.AsyncFunctionDef, ast.Lambda, ast.ClassDef),
            ):
                continue
            visit(child)

    visit(function)
    return out


def _reads_between(
    nodes: List[ast.AST], name: str, start_line: int, end_line: int
) -> List[int]:
    out = []
    for child in nodes:
        if not isinstance(child, ast.Name) or child.id != name:
            continue
        if not isinstance(child.ctx, ast.Load):
            continue
        line = getattr(child, "lineno", -1)
        if start_line < line < end_line:
            out.append(line)
    return sorted(set(out))


def _reads_name(node: ast.AST, name: str) -> bool:
    return any(
        isinstance(child, ast.Name)
        and child.id == name
        and isinstance(child.ctx, ast.Load)
        for child in ast.walk(node)
    )


def _functions(tree: ast.Module) -> Iterable[ast.AST]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def scan_project(project_id: str) -> List[Dict[str, Any]]:
    cfg = PROJECTS[project_id]
    root = cfg["root"]
    source_root = root / cfg["source_dir"]
    candidates: List[Dict[str, Any]] = []
    for path in sorted(source_root.rglob("*.py")):
        rel = path.relative_to(root).as_posix()
        try:
            text = path.read_text(encoding="utf-8")
            tree = ast.parse(text)
        except (UnicodeDecodeError, SyntaxError):
            continue
        lines = text.splitlines()
        for fn in _functions(tree):
            nodes = _local_nodes(fn)
            assignments: Dict[str, List[Tuple[int, str, ast.AST]]] = {}
            for stmt in nodes:
                parsed = _simple_assignment(stmt)
                if parsed is None:
                    continue
                name, line = parsed
                assignments.setdefault(name, []).append(
                    (line, type(stmt).__name__, stmt)
                )
            for name, rows in assignments.items():
                rows = sorted(set(rows), key=lambda row: (row[0], row[1]))
                if len(rows) < 2:
                    continue
                for index, (line, kind, node) in enumerate(rows[:-1]):
                    later = [
                        r for r in rows[index + 1 :]
                        if r[0] > line
                    ]
                    if not later:
                        continue
                    if (project_id, rel, line) in EXCLUDED_LINES:
                        continue
                    # Only one statement may start on the line.
                    same_line = [
                        n for n in ast.walk(tree)
                        if isinstance(n, ast.stmt) and n.lineno == line
                    ]
                    if len(same_line) != 1:
                        continue
                    reads = _reads_between(nodes, name, line, later[0][0])
                    later_rows = [
                        {
                            "line": other_line,
                            "kind": other_kind,
                            "code": _assignment_code(lines, other_line),
                            "reads_A": _reads_name(other_node, name),
                        }
                        for other_line, other_kind, other_node in later
                    ]
                    flags = _scope_depth(nodes, line)
                    candidates.append(
                        {
                            "candidate_id": (
                                f"{project_id}:{rel}:{line}:{name}"
                            ),
                            "project_id": project_id,
                            "project": cfg["project"],
                            "version": cfg["version"],
                            "file": rel,
                            "function": getattr(fn, "name", "<lambda>"),
                            "variable": name,
                            "target_A": {
                                "line": line,
                                "kind": kind,
                                "code": _assignment_code(lines, line),
                            },
                            "later_assignments": later_rows,
                            "read_between_A_and_first_later": reads,
                            "static_shape": {
                                **flags,
                                "read_before_later_write": bool(reads),
                                "later_write_reads_A": any(
                                    row["reads_A"] for row in later_rows
                                ),
                                "later_write_is_plain_assign": (
                                    later[0][1] == "Assign"
                                ),
                            },
                            "source_sha256": hashlib.sha256(
                                path.read_bytes()
                            ).hexdigest(),
                        }
                    )
    return candidates


def rank(candidate: Dict[str, Any]) -> Tuple[int, int, int, int]:
    shape = candidate["static_shape"]
    return (
        1 if shape["later_write_reads_A"] else 0,
        1 if shape["read_before_later_write"] else 0,
        0 if (shape["in_loop"] or shape["in_try"]) else 1,
        -candidate["target_A"]["line"],
    )


def build() -> Dict[str, Any]:
    all_rows: List[Dict[str, Any]] = []
    project_meta = {}
    for project_id, cfg in PROJECTS.items():
        if not cfg["root"].exists():
            raise FileNotFoundError(cfg["root"])
        rows = scan_project(project_id)
        all_rows.extend(rows)
        project_meta[project_id] = {
            "project": cfg["project"],
            "version": cfg["version"],
            "root": str(cfg["root"]),
            "source_tree_sha256": tree_sha256(
                cfg["root"], cfg["package"], cfg["source_dir"]
            ),
            "tests": cfg["tests"],
            "python": cfg["python"],
            "pytest": cfg["pytest"],
            "extra_args": cfg["extra_args"],
            "suite_note": cfg["suite_note"],
            "static_candidates": len(rows),
        }
    all_rows.sort(key=lambda row: (row["project_id"], row["file"],
                                  row["target_A"]["line"], row["variable"]))
    seen = set()
    unique_rows = []
    duplicate_rows = []
    for row in all_rows:
        if row["candidate_id"] in seen:
            duplicate_rows.append(row["candidate_id"])
            continue
        seen.add(row["candidate_id"])
        unique_rows.append(row)
    all_rows = unique_rows
    payload = {
        "protocol": "benchmark_real_v3",
        "scan_rule": (
            "local-name assignment A with at least one later assignment to "
            "the same name in the same function; one statement per line; "
            "prior v2/dev lines excluded"
        ),
        "projects": project_meta,
        "candidates": all_rows,
        "duplicate_rows_removed": duplicate_rows,
        "static_rank_order": [
            row["candidate_id"] for row in sorted(all_rows, key=rank, reverse=True)
        ],
    }
    CANDIDATES.mkdir(parents=True, exist_ok=True)
    path = CANDIDATES / "candidates_static.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8")
    return payload


if __name__ == "__main__":
    data = build()
    print(f"wrote {CANDIDATES / 'candidates_static.json'}")
    for project, meta in data["projects"].items():
        print(project, meta["static_candidates"], meta["source_tree_sha256"][:16])
    print("total", len(data["candidates"]))
