"""Stage 0 (project/test metadata) and Stage 1 (AST candidate discovery).

Only the DEV half of the broad pool is extracted and scanned.  HELDOUT_BROAD
archives stay packed and unread.

Outputs::

    discovery/stage0/projects.json          test entry points, package roots
    discovery/stage1/candidates_static.json every static candidate
    discovery/stage1/stage1_counts.json     per-project counts
"""
from __future__ import annotations

import ast
import hashlib
import json
import re
import shutil
import sys
import tarfile
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

KIT = Path(__file__).resolve().parents[2]
DS = KIT / "benchmark_v4_dataset" / "discovery"
META = DS / "manifest"
SDISTS = DS / "sdists"
SOURCES = DS / "sources"
STAGE0 = DS / "stage0"
STAGE1 = DS / "stage1"

EXCLUDE_DIRS = {
    "test", "tests", "testing", "docs", "doc", "examples", "example",
    "scripts", "benchmark", "benchmarks", ".github", "build", "dist",
    "site-packages", "node_modules", "tools", "ci",
}
TEST_FILE_RE = re.compile(r"^(test_.*\.py|.*_test\.py|conftest\.py)$")


def registry() -> list[dict]:
    return json.loads((META / "source_registry.json").read_text(
        encoding="utf-8"))["projects"]


def safe_extract(tar_path: Path, dest: Path) -> str:
    """Extract one sdist, refusing absolute/parent paths. Returns top dir."""
    dest.mkdir(parents=True, exist_ok=True)
    with tarfile.open(tar_path, "r:*") as tar:
        members = tar.getmembers()
        tops = {m.name.split("/")[0] for m in members if m.name}
        for member in members:
            name = Path(member.name)
            if name.is_absolute() or ".." in name.parts:
                raise SystemExit(f"unsafe member {member.name!r}")
            if member.issym() or member.islnk():
                # PyPI sdists occasionally contain links; materialize files
                # only and skip links to keep the extraction self-contained.
                continue
        tar.extractall(dest)
    if len(tops) != 1:
        raise SystemExit(f"{tar_path.name}: expected one top dir, got {tops}")
    return tops.pop()


def project_source(row: dict) -> Path:
    return SOURCES / row["slug"]


def find_packages(root: Path) -> tuple[list[Path], list[Path]]:
    """Return (package roots to scan, test roots)."""
    candidates = []
    if (root / "src").is_dir():
        candidates = [d for d in (root / "src").iterdir()]
    if not candidates:
        candidates = list(root.iterdir())
    packages = []
    tests = []
    for path in sorted(candidates):
        if not path.is_dir() or path.name in EXCLUDE_DIRS:
            continue
        name = path.name.lower()
        if name.startswith("test") or name == "testing":
            tests.append(path)
            continue
        if (path / "__init__.py").exists() or any(
                p.suffix == ".py" for p in path.iterdir() if p.is_file()):
            packages.append(path)
    for extra in ("tests", "test", "testing"):
        path = root / extra
        if path.is_dir():
            tests.append(path)
    # single-module distributions (decorator.py, six.py, ...)
    for path in sorted(root.glob("*.py")):
        if path.name in {"setup.py", "conftest.py"} or TEST_FILE_RE.match(path.name):
            continue
        if path.name in {"setup.py", "conftest.py"}:
            continue
        packages.append(path)
    # dedupe
    tests = sorted({p.resolve() for p in tests})
    packages = sorted({p.resolve() for p in packages})
    return packages, tests


def stage0() -> int:
    rows = []
    for row in registry():
        if row["split"] != "DEV":
            continue
        dest = project_source(row)
        top = safe_extract(SDISTS / row["filename"], dest)
        root = dest / top
        packages, tests = find_packages(root)
        # Test modules may live inside the package (toolz/tests, coverage/*),
        # so enumerate the whole tree and only drop docs/build trees.
        test_files = []
        for path in root.rglob("*.py"):
            if not TEST_FILE_RE.match(path.name):
                continue
            rel_parts = path.relative_to(root).parts[:-1]
            if any(part in {"docs", "doc", "build", "dist", ".tox"}
                   for part in rel_parts):
                continue
            test_files.append(path)
        configs = [n for n in ("pytest.ini", "tox.ini", "setup.cfg",
                               "pyproject.toml", "setup.py", "conftest.py")
                   if (root / n).exists()]
        rows.append({
            "slug": row["slug"],
            "name": row["name"],
            "version": row["version"],
            "split": row["split"],
            "root": str(root.relative_to(DS)),
            "top_dir": top,
            "packages": [str(p.relative_to(root).as_posix()) for p in packages],
            "test_roots": [str(p.relative_to(root).as_posix()) for p in tests],
            "test_file_count": len(test_files),
            "has_original_tests": bool(test_files),
            "config_files": configs,
            "requires_python": row.get("requires_python"),
        })
        print(row["slug"], "tests=", len(test_files), "pkgs=", len(packages))
    STAGE0.mkdir(parents=True, exist_ok=True)
    (STAGE0 / "projects.json").write_text(
        json.dumps({"schema": "mace_v4_stage0/1", "projects": rows},
                   ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"projects": len(rows),
                      "with_tests": sum(r["has_original_tests"] for r in rows)},
                     indent=2))
    return 0


# --------------------------------------------------------------- stage 1 AST
def _target_key(node: ast.AST):
    if isinstance(node, ast.Assign):
        if len(node.targets) != 1:
            return None
        target = node.targets[0]
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        target = node.target
    else:
        return None
    if isinstance(target, ast.Name):
        return ("name", target.id), ""
    if isinstance(target, ast.Attribute):
        base = target.value
        receiver = base.id if isinstance(base, ast.Name) else ""
        return ("attr", target.attr), receiver
    if isinstance(target, ast.Subscript):
        base = target.value
        receiver = ""
        if isinstance(base, ast.Name):
            receiver = base.id
        elif isinstance(base, ast.Attribute):
            receiver = base.attr
        index = None
        if isinstance(target.slice, ast.Constant) and isinstance(
                target.slice.value, (str, int, float, bool, type(None))):
            index = target.slice.value
        return ("sub", str(index)) if index is not None else ("sub", "*"), receiver
    return None


def _local_nodes(function: ast.AST) -> list[ast.AST]:
    out: list[ast.AST] = []

    def visit(node: ast.AST) -> None:
        for child in ast.iter_child_nodes(node):
            out.append(child)
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef,
                                  ast.Lambda, ast.ClassDef)):
                continue
            visit(child)

    visit(function)
    return out


def _scope_depth(nodes: list[ast.AST], line: int) -> dict:
    flags = {"in_loop": False, "in_try": False, "in_if": False,
             "in_with": False, "nested_scope": False}
    for child in nodes:
        if not isinstance(child, ast.stmt):
            continue
        end = getattr(child, "end_lineno", child.lineno) or child.lineno
        if not (child.lineno <= line <= end):
            continue
        if isinstance(child, (ast.For, ast.While, ast.AsyncFor)):
            flags["in_loop"] = True
        elif isinstance(child, ast.Try):
            flags["in_try"] = True
        elif isinstance(child, ast.If):
            flags["in_if"] = True
        elif isinstance(child, (ast.With, ast.AsyncWith)):
            flags["in_with"] = True
    return flags


def _code(lines: list[str], first: int, last: int) -> str:
    text = lines[first - 1].strip()
    if last != first:
        text += "  # multi-line"
    return text[:300]


def _callees(fn: ast.AST, functions: dict, classes: dict) -> list[ast.AST]:
    out = []
    called = set()
    for node in ast.walk(fn):
        if isinstance(node, ast.Call):
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


def scan_file(project_row: dict, root: Path, path: Path) -> list[dict]:
    rel = path.relative_to(root).as_posix()
    try:
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
    except (UnicodeDecodeError, SyntaxError):
        return []
    lines = text.splitlines()
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    classes = {n.name: n for n in ast.walk(tree) if isinstance(n, ast.ClassDef)}
    functions = {n.name: n for n in ast.walk(tree)
                 if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))}
    rows = []
    for fn in [n for n in ast.walk(tree)
               if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))]:
        nodes = _local_nodes(fn)
        items = []
        for node in nodes:
            parsed = _target_key(node)
            if parsed is None:
                continue
            key, obj = parsed
            items.append({
                "key": key, "obj": obj, "line": int(node.lineno),
                "end_line": int(getattr(node, "end_lineno", node.lineno)
                                or node.lineno),
                "kind": type(node).__name__, "node": node,
            })
        by_key: dict[tuple, list[dict]] = defaultdict(list)
        for item in items:
            by_key[item["key"]].append(item)
        for key, group in by_key.items():
            group.sort(key=lambda x: x["line"])
            if len(group) < 2:
                continue
            for index, item in enumerate(group[:-1]):
                later = [g for g in group[index + 1:] if g["line"] > item["line"]]
                if not later:
                    continue
                multi = item["end_line"] != item["line"]
                if item["kind"] == "AugAssign":
                    mech = "augassign"
                elif key[0] == "attr":
                    mech = "attribute"
                elif key[0] == "sub":
                    mech = "subscript"
                elif multi:
                    mech = "multiline"
                else:
                    mech = "name"
                first_later = later[0]["line"]
                reads_between = [
                    n.lineno for n in nodes
                    if isinstance(n, ast.Name) and n.id == key[1]
                    and isinstance(n.ctx, ast.Load)
                    and item["line"] < n.lineno < first_later
                ]
                later_reads_a = False
                for other in later:
                    later_reads_a = later_reads_a or any(
                        isinstance(n, ast.Name) and n.id == key[1]
                        and isinstance(n.ctx, ast.Load) for n in ast.walk(other["node"]))
                rows.append({
                    "candidate_id": (f"{project_row['slug']}:{rel}:"
                                     f"{item['line']}:{mech}:{key[1]}"),
                    "project_id": project_row["slug"],
                    "project": project_row["name"],
                    "version": project_row["version"],
                    "split": project_row["split"],
                    "file": rel,
                    "function": getattr(fn, "name", "<lambda>"),
                    "variable": key[1],
                    "key_kind": key[0],
                    "key_obj": item["obj"],
                    "mechanism": mech,
                    "target_A": {
                        "line": item["line"], "end_line": item["end_line"],
                        "kind": item["kind"],
                        "code": _code(lines, item["line"], item["end_line"]),
                    },
                    "later_assignments": [{
                        "line": o["line"], "end_line": o["end_line"],
                        "kind": o["kind"],
                        "code": _code(lines, o["line"], o["end_line"]),
                    } for o in later[:5]],
                    "later_count": len(later),
                    "read_between_A_and_first_later": reads_between,
                    "static_shape": {
                        **_scope_depth(nodes, item["line"]),
                        "read_before_later_write": bool(reads_between),
                        "later_write_reads_A": later_reads_a,
                        "later_write_is_plain_assign": later[0]["kind"] == "Assign",
                        "mechanism": mech,
                    },
                    "source_sha256": digest,
                })
        # cross-function local-name mechanism
        for key, group in by_key.items():
            if key[0] != "name" or len(group) != 1:
                continue
            item = group[0]
            for callee in _callees(fn, functions, classes):
                if not any(isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
                           for n in [callee]):
                    continue
                hits = []
                for node in _local_nodes(callee):
                    parsed = _target_key(node)
                    if parsed and parsed[0] == key:
                        hits.append(node)
                if not hits:
                    continue
                rows.append({
                    "candidate_id": (f"{project_row['slug']}:{rel}:"
                                     f"{item['line']}:cross_function:{key[1]}"),
                    "project_id": project_row["slug"],
                    "project": project_row["name"],
                    "version": project_row["version"],
                    "split": project_row["split"],
                    "file": rel,
                    "function": getattr(fn, "name", "<lambda>"),
                    "variable": key[1],
                    "key_kind": key[0],
                    "key_obj": item["obj"],
                    "mechanism": "cross_function",
                    "callee": callee.name,
                    "target_A": {"line": item["line"],
                                 "end_line": item["end_line"],
                                 "kind": item["kind"],
                                 "code": _code(lines, item["line"], item["end_line"])},
                    "later_assignments": [{
                        "line": int(n.lineno),
                        "end_line": int(getattr(n, "end_lineno", n.lineno)
                                        or n.lineno),
                        "kind": type(n).__name__,
                        "code": _code(lines, n.lineno,
                                      getattr(n, "end_lineno", n.lineno)),
                    } for n in hits[:5]],
                    "later_count": len(hits),
                    "read_between_A_and_first_later": [],
                    "static_shape": {
                        **_scope_depth(nodes, item["line"]),
                        "read_before_later_write": False,
                        "later_write_reads_A": False,
                        "later_write_is_plain_assign": False,
                        "mechanism": "cross_function",
                    },
                    "source_sha256": digest,
                })
                break
    return rows


def stage1() -> int:
    projects = json.loads((STAGE0 / "projects.json").read_text(
        encoding="utf-8"))["projects"]
    rows = []
    per_project = {}
    for project in projects:
        root = DS / project["root"]
        seen = set()
        rows_p = []
        for pkg in project["packages"]:
            base = root / pkg
            if base.is_file():
                paths = [base]
            else:
                paths = sorted(base.rglob("*.py"))
            for path in paths:
                rel = path.relative_to(root).as_posix()
                if any(part in EXCLUDE_DIRS for part in Path(rel).parts[:-1]):
                    continue
                for row in scan_file(project, root, path):
                    if row["candidate_id"] in seen:
                        continue
                    seen.add(row["candidate_id"])
                    rows_p.append(row)
        per_project[project["slug"]] = len(rows_p)
        rows.extend(rows_p)
        print(project["slug"], len(rows_p))
    STAGE1.mkdir(parents=True, exist_ok=True)
    (STAGE1 / "candidates_static.json").write_text(json.dumps({
        "schema": "mace_v4_stage1/1",
        "protocol": "benchmark_v4_dataset/PROTOCOL.md",
        "counts_by_project": per_project,
        "counts_by_mechanism": dict(Counter(r["mechanism"] for r in rows)),
        "counts_by_project_and_mechanism": {
            p: dict(Counter(r["mechanism"] for r in rows
                            if r["project_id"] == p))
            for p in per_project},
        "total": len(rows),
        "candidates": rows,
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (STAGE1 / "stage1_counts.json").write_text(json.dumps({
        "projects_scanned": len(per_project),
        "candidates_total": len(rows),
        "counts_by_project": per_project,
        "counts_by_mechanism": dict(Counter(r["mechanism"] for r in rows)),
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({"projects": len(per_project), "candidates": len(rows),
                      "mechanisms": dict(Counter(r["mechanism"] for r in rows))},
                     indent=2))
    return 0


def main() -> int:
    cmd = sys.argv[1] if len(sys.argv) > 1 else ""
    if cmd == "stage0":
        return stage0()
    if cmd == "stage1":
        return stage1()
    print("usage: stage0_stage1.py stage0|stage1")
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
