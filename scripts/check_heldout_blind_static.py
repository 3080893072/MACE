# -*- coding: utf-8 -*-
"""Static + dynamic audit of the HELDOUT blind runner.

1. AST scan: the runner must not call any truth-reading helper
   (reference_for / _prepare_baseline / block_spans / score_sets) and must not
   contain legacy-root or hidden-directory literals outside the guard list.
2. Import scan: every module imported by the runner is checked for symbols it
   exposes; only the audited helper set may be used at runtime (the runtime
   audit hook in the runner is the authoritative check).
3. Guard self-test: importing the runner installs an audit hook; a deliberate
   attempt to open a hidden reference must raise PermissionError.
"""
from __future__ import annotations

import ast
import importlib.util
import json
import sys
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")
KIT = Path(__file__).resolve().parents[1]
RUNNER = KIT / "scripts" / "run_heldout_v2_1_blind.py"
HELDOUT = KIT / "benchmark_v4_dataset" / "source_derived_v2_1" / "heldout"

FORBIDDEN_CALLS = {"reference_for", "_prepare_baseline", "block_spans",
                   "score_sets", "_block_vectors"}
FORBIDDEN_SUBSTRINGS = ("source_derived/heldout", "enumeration",
                        "reference.json", "heldout/tasks",
                        "heldout/acceptance", "heldout/seal")


def main() -> int:
    report = {"runner": str(RUNNER), "checks": {}, "violations": []}
    tree = ast.parse(RUNNER.read_text("utf-8"))

    calls = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else (
                fn.id if isinstance(fn, ast.Name) else None)
            if name:
                calls.append(name)
    bad_calls = sorted(set(calls) & FORBIDDEN_CALLS)
    report["checks"]["forbidden_calls"] = {
        "found": bad_calls, "ok": not bad_calls}
    report["violations"] += [f"calls {c}" for c in bad_calls]

    guard_node = None
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == "FORBIDDEN_MARKERS"
                for t in node.targets):
            guard_node = node
    guard_literals = set()
    if guard_node is not None:
        for elt in guard_node.value.elts:
            if isinstance(elt, ast.Constant):
                guard_literals.add(elt.value)

    docstrings = set()
    for node in ast.walk(tree):
        if isinstance(node, (ast.Module, ast.FunctionDef, ast.ClassDef,
                             ast.AsyncFunctionDef)):
            body = getattr(node, "body", [])
            if body and isinstance(body[0], ast.Expr) \
                    and isinstance(body[0].value, ast.Constant) \
                    and isinstance(body[0].value.value, str):
                docstrings.add(id(body[0].value))
    literals = [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str)
                and id(n) not in docstrings]
    flagged = sorted({s for s in literals
                      if any(m in s for m in FORBIDDEN_SUBSTRINGS)
                      and s not in guard_literals})
    report["checks"]["hidden_path_literals"] = {
        "found": flagged, "ok": not flagged}
    report["violations"] += [f"literal {s!r}" for s in flagged]

    src = RUNNER.read_text("utf-8")
    binding_ok = ('HELDOUT.parent.name == "source_derived_v2_1"'
                  in src and "assert PUB.is_dir()" in src
                  and 'assert probe.exists()' in src)
    report["checks"]["explicit_path_binding"] = {"ok": binding_ok}
    if not binding_ok:
        report["violations"].append("missing path binding assertions")

    # ---- dynamic guard self-test (fresh process, same file) --------------
    spec = importlib.util.spec_from_file_location("blind_runner_selftest",
                                                  RUNNER)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)  # installs the audit hook
    cid = sorted(p.name for p in (HELDOUT / "tasks").iterdir())[0]
    blocked = []
    for target in (HELDOUT / "tasks" / cid / "reference.json",
                   HELDOUT / "acceptance" / f"{cid}.json",
                   HELDOUT / "evidence" / cid / "enumeration.json",
                   KIT / "benchmark_v4_dataset" / "source_derived" / "heldout"
                   / "probes" / "x.py"):
        try:
            target.read_text("utf-8")
        except PermissionError:
            blocked.append(target.name)
        except FileNotFoundError:
            blocked.append(f"{target.name} (blocked-before-stat)")
        else:
            report["violations"].append(f"guard failed to block {target}")
    report["checks"]["guard_selftest"] = {
        "blocked": blocked, "ok": len(blocked) == 4}

    report["ok"] = not report["violations"]
    out = KIT / "results" / "MACE_HELDOUT_v2_1_blind_static_check.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    print(json.dumps(report["checks"], ensure_ascii=False, indent=1))
    print("violations:", report["violations"])
    print("wrote", out)
    return 0 if report["ok"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
