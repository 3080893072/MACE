"""Reproduce the real-code screening funnel for the feasibility report.

Stages (each is a strict subset of the previous one):

1. every ``*.py`` file in the installed standard library and site-packages;
2. files that parse as Python 3.11;
3. top-level functions that the MACE AST subset accepts after being renamed
   ``program``, stripped of decorators, and paired with their transitive
   same-module helper closure (``mace.program.validate_subset``);
4. functions with a conditional assignment: an ``Assign``/``AugAssign`` that is
   a direct child of an ``If`` body, whose target is a plain local name, and
   which is not inside a loop;
5. functions where that target name already has a definition before the
   conditional assignment, so deleting A cannot simply raise ``NameError``;
6. functions where every parameter has an ``int``, ``bool`` or ``list[int]``
   annotation (needed to build a finite domain without guessing types).

No model is called.  The stage counts are the denominator for the claim that
the ten audited cases are a tiny, non-random slice of real code.

Usage
-----
    python scripts/screen_realcases.py
"""
from __future__ import annotations

import ast
import json
import site
import sys
import sysconfig
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mace.program import validate_subset  # noqa: E402

SKIP_PARTS = {"test", "tests", "testing", "__pycache__", "node_modules"}


def roots() -> List[Path]:
    found: List[Path] = []
    for key in ("stdlib", "platstdlib", "purelib", "platlib"):
        value = sysconfig.get_paths().get(key)
        if value:
            found.append(Path(value))
    user = site.getusersitepackages()
    if user:
        found.append(Path(user))
    seen = set()
    out = []
    for path in found:
        if path.exists() and str(path) not in seen:
            seen.add(str(path))
            out.append(path)
    return out


def all_files(base: Path) -> Iterable[Path]:
    for path in base.rglob("*.py"):
        if SKIP_PARTS & set(path.parts):
            continue
        yield path


def arg_sort(annotation: ast.expr | None) -> str | None:
    if annotation is None:
        return None
    text = ast.unparse(annotation)
    return text if text in ("int", "bool", "list[int]") else None


def parent_map(tree: ast.AST) -> Dict[ast.AST, ast.AST]:
    parents: Dict[ast.AST, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[child] = parent
    return parents


def inside_loop(node: ast.AST, parents: Dict[ast.AST, ast.AST]) -> bool:
    current = parents.get(node)
    while current is not None:
        if isinstance(current, (ast.For, ast.While)):
            return True
        current = parents.get(current)
    return False


def same_name_target(stmt: ast.stmt) -> str | None:
    if isinstance(stmt, ast.Assign):
        if len(stmt.targets) != 1 or not isinstance(stmt.targets[0], ast.Name):
            return None
        return stmt.targets[0].id
    if isinstance(stmt, ast.AugAssign) and isinstance(stmt.target, ast.Name):
        return stmt.target.id
    return None


def defined_before(name: str, line: int, fn: ast.FunctionDef) -> bool:
    if any(a.arg == name for a in fn.args.posonlyargs + fn.args.args):
        return True
    for node in ast.walk(fn):
        if isinstance(node, (ast.Assign, ast.AugAssign, ast.AnnAssign)) \
                and node.lineno < line:
            targets = node.targets if isinstance(node, ast.Assign) else [node.target]
            for target in targets:
                if isinstance(target, ast.Name) and target.id == name:
                    return True
    return False


def candidate(fn: ast.FunctionDef, parents: Dict[ast.AST, ast.AST]):
    out = []
    for node in ast.walk(fn):
        if not isinstance(node, ast.If):
            continue
        for stmt in node.body:
            name = same_name_target(stmt)
            if name is None or inside_loop(stmt, parents):
                continue
            out.append((stmt.lineno, name))
    return out


def wrapped(fn: ast.FunctionDef, module: ast.Module) -> ast.Module:
    """Target function plus its transitive same-module helper closure.

    Module-level assignments and imports are dropped: the ten audited cases
    inline their constants, and imports cannot be modelled by the subset.
    Keeping same-module helpers avoids rejecting a function merely because it
    calls a local helper that MACE could also extract.
    """
    import copy

    pool = {node.name: node for node in module.body
            if isinstance(node, ast.FunctionDef)}
    keep = {fn.name}
    pending = [fn]
    while pending:
        current = pending.pop()
        for node in ast.walk(current):
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Name):
                name = node.func.id
                if name in pool and name not in keep:
                    keep.add(name)
                    pending.append(pool[name])
    functions = []
    for name in sorted(keep):
        clone = copy.deepcopy(pool[name])
        if clone is fn or name == fn.name:
            clone.name = "program"
        clone.decorator_list = []
        functions.append(clone)
    return ast.fix_missing_locations(ast.Module(body=functions,
                                                type_ignores=[]))


def main() -> int:
    counts = {"files": 0, "parsed": 0, "functions": 0, "subset": 0,
              "conditional": 0, "earlier_definition": 0, "typed": 0}
    examples: Dict[str, List[Dict[str, Any]]] = {k: [] for k in
                                                 ("subset", "conditional",
                                                  "earlier_definition", "typed")}
    seen_paths = set()
    for base in roots():
        for path in all_files(base):
            key = str(path.resolve())
            if key in seen_paths:
                continue
            seen_paths.add(key)
            counts["files"] += 1
            if counts["files"] % 2000 == 0:
                print(f"  scanned {counts['files']} files: {counts}",
                      file=sys.stderr, flush=True)
            try:
                source = path.read_text(encoding="utf-8")
                module = ast.parse(source)
            except (OSError, SyntaxError, UnicodeDecodeError):
                continue
            counts["parsed"] += 1
            parents = parent_map(module)
            for fn in module.body:
                if not isinstance(fn, ast.FunctionDef):
                    continue
                if len(fn.body) < 2 or len(fn.body) > 20:
                    continue
                counts["functions"] += 1
                try:
                    problems = validate_subset(wrapped(fn, module))
                except (SyntaxError, ValueError):
                    continue
                if problems:
                    continue
                counts["subset"] += 1
                if len(examples["subset"]) < 5:
                    examples["subset"].append({"file": key, "name": fn.name,
                                               "line": fn.lineno})
                cands = candidate(fn, parents)
                if not cands:
                    continue
                counts["conditional"] += 1
                if len(examples["conditional"]) < 5:
                    examples["conditional"].append({
                        "file": key, "name": fn.name,
                        "targets": cands[:3]})
                early = [(line, name) for line, name in cands
                         if defined_before(name, line, fn)]
                if not early:
                    continue
                counts["earlier_definition"] += 1
                if len(examples["earlier_definition"]) < 5:
                    examples["earlier_definition"].append({
                        "file": key, "name": fn.name, "targets": early[:3]})
                args = fn.args.posonlyargs + fn.args.args
                if any(arg_sort(a.annotation) is None for a in args):
                    continue
                counts["typed"] += 1
                if len(examples["typed"]) < 20:
                    examples["typed"].append({
                        "file": key, "name": fn.name, "targets": early[:3],
                        "args": {a.arg: arg_sort(a.annotation) for a in args}})
    data = {"roots": [str(r) for r in roots()], "counts": counts,
            "examples": examples,
            "note": "Stages are nested; tests directories are skipped."}
    out = ROOT / "realcases" / "screening.json"
    out.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n",
                   encoding="utf-8")
    print(json.dumps(counts, indent=2))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
