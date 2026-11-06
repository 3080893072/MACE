"""Stage 3.5: rank Stage-1 candidates by recomputation structure.

For every candidate A this script re-parses the source file and records, for
the same variable in the same enclosing function:

* earlier assignments and whether their normalised right-hand side equals A's;
* later assignments and whether their normalised right-hand side equals A's;
* whether the earlier/later assignment sits in the same statement block as A
  (a stronger signal for "the value is recomputed on the same path").

No candidate package is imported; this is pure ``ast`` over the DEV sources.

Output::

    discovery/stage3_5/recompute_signals.json
"""
from __future__ import annotations

import ast
import json
from collections import Counter, defaultdict
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
DS = KIT / "benchmark_v4_dataset"
DISC = DS / "discovery"
SRC = DISC / "sources"

TARGETS = ("Assign", "AnnAssign", "AugAssign")


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def assignment_sites(tree: ast.AST) -> list[dict]:
    """All simple assignment statements with their enclosing statement block."""
    out = []

    class Visitor(ast.NodeVisitor):
        def __init__(self):
            self.stack: list[ast.AST] = []

        def visit(self, node):
            is_block = isinstance(node, (ast.Module, ast.FunctionDef,
                                         ast.AsyncFunctionDef, ast.ClassDef,
                                         ast.If, ast.For, ast.AsyncFor,
                                         ast.While, ast.With, ast.AsyncWith,
                                         ast.Try, ast.ExceptHandler))
            if is_block:
                self.stack.append(node)
            method = "visit_" + node.__class__.__name__
            getattr(self, method, self.generic_visit)(node)
            if is_block:
                self.stack.pop()

        def _record(self, node):
            targets = []
            if isinstance(node, ast.Assign):
                for t in node.targets:
                    if isinstance(t, ast.Name):
                        targets.append(t.id)
            elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
                targets.append(node.target.id)
            elif isinstance(node, ast.AugAssign) and isinstance(node.target, ast.Name):
                targets.append(node.target.id)
            rhs = node.value
            try:
                rhs_text = ast.unparse(rhs)
            except Exception:
                rhs_text = ""
            block = self.stack[-1] if self.stack else None
            func = next((n for n in reversed(self.stack)
                         if isinstance(n, (ast.FunctionDef,
                                           ast.AsyncFunctionDef))), None)
            guards = []
            for n in self.stack:
                if isinstance(n, (ast.If, ast.While)):
                    try:
                        guards.append(ast.unparse(n.test))
                    except Exception:
                        guards.append("")
                elif isinstance(n, (ast.For, ast.AsyncFor)):
                    try:
                        guards.append("for " + ast.unparse(n.target))
                    except Exception:
                        guards.append("for")
                elif isinstance(n, ast.Try):
                    guards.append("try")
                elif isinstance(n, ast.ExceptHandler):
                    guards.append("except")
            out.append({
                "guards": guards,
                "line": node.lineno,
                "end_line": getattr(node, "end_lineno", node.lineno),
                "kind": node.__class__.__name__,
                "targets": targets,
                "rhs": rhs_text,
                "block_line": getattr(block, "lineno", 0),
                "block_type": block.__class__.__name__ if block else "",
                "func_line": getattr(func, "lineno", 0),
                "func_name": getattr(func, "name", ""),
            })

        visit_Assign = _record
        visit_AnnAssign = _record
        visit_AugAssign = _record

    Visitor().visit(tree)
    return out


def main() -> int:
    cands = load(DISC / "stage1" / "candidates_static.json")["candidates"]
    meta = {p["slug"]: p for p in
            load(DISC / "stage0" / "projects.json")["projects"]}
    by_file = defaultdict(list)
    for c in cands:
        by_file[(c["project_id"], c["file"])].append(c)

    cache: dict[tuple[str, str], list[dict]] = {}
    for (slug, rel), items in by_file.items():
        meta_row = meta.get(slug)
        if not meta_row:
            continue
        # stage0 "root" is relative to benchmark_v4_dataset/discovery
        path = DISC / meta_row["root"] / rel
        if not path.exists():
            path = SRC / slug / rel
        if not path.exists():
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        sites = assignment_sites(tree)
        per_var = defaultdict(list)
        for s in sites:
            for t in s["targets"]:
                per_var[t].append(s)
        cache[(slug, rel)] = per_var

    rows = []
    for c in cands:
        per_var = cache.get((c["project_id"], c["file"]))
        if per_var is None:
            continue
        var = c["variable"]
        a_line = c["target_A"]["line"]
        mine = next((s for s in per_var.get(var, [])
                     if s["line"] == a_line), None)
        if mine is None:
            continue
        rhs = mine["rhs"]
        earlier = [s for s in per_var.get(var, []) if s["line"] < a_line]
        later = [s for s in per_var.get(var, []) if s["line"] > a_line]
        same_rhs_earlier = [s for s in earlier
                            if s["rhs"] == rhs
                            and s["func_line"] == mine["func_line"]]
        same_rhs_later = [s for s in later
                          if s["rhs"] == rhs
                          and s["func_line"] == mine["func_line"]]
        a_guards = list(mine["guards"])
        same_block_earlier = [s for s in same_rhs_earlier
                              if s["func_line"] == mine["func_line"]]
        # a simple "unconditional" guess: the site's parent block is the
        # function body (block_type == FunctionDef)
        unconditional_earlier = [s for s in same_block_earlier
                                 if s["block_type"] in
                                 ("FunctionDef", "AsyncFunctionDef")]
        rows.append({
            "candidate_id": c["candidate_id"],
            "project_id": c["project_id"],
            "file": c["file"],
            "function": c["function"],
            "variable": var,
            "A_line": a_line,
            "A_rhs": rhs,
            "earlier_same_var": len(earlier),
            "later_same_var": len(later),
            "same_rhs_earlier": [s["line"] for s in same_rhs_earlier],
            "same_rhs_later": [s["line"] for s in same_rhs_later],
            "A_guards": a_guards,
            "earlier_guards": {str(s["line"]): s["guards"]
                               for s in same_rhs_earlier},
            "later_guards": {str(s["line"]): s["guards"]
                             for s in same_rhs_later},
            "same_rhs_earlier_unconditional":
                [s["line"] for s in unconditional_earlier],
            "A_block_type": mine["block_type"],
            "score": (3 * len(unconditional_earlier)
                      + 2 * len(same_rhs_earlier)
                      + 2 * len(same_rhs_later)),
        })

    rows.sort(key=lambda r: (-r["score"], r["candidate_id"]))
    out = DISC / "stage3_5"
    out.mkdir(parents=True, exist_ok=True)
    (out / "recompute_signals.json").write_text(
        json.dumps({"schema": "stage3_5_recompute/1",
                    "candidates": rows}, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    counts = Counter(r["score"] for r in rows)
    print(json.dumps({
        "candidates_analysed": len(rows),
        "with_same_rhs_earlier": sum(1 for r in rows if r["same_rhs_earlier"]),
        "with_same_rhs_later": sum(1 for r in rows if r["same_rhs_later"]),
        "with_unconditional_same_rhs_earlier": sum(
            1 for r in rows if r["same_rhs_earlier_unconditional"]),
        "score_distribution": dict(sorted(counts.items())),
        "top": rows[:15],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
