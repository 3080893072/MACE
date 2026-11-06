"""M6 phase 3: evaluate the source-level symbolic engine.

The symbolic engine (``mace/symbolic.py``) derives a mask guard directly from
the fixture source by enumerating control-flow paths in the function with the
target assignment kept (P+) and deleted (P-), then asking, per path, which
condition makes every returned channel equal.  It never calls a model and never
reads a reference guard.

Four methods are compared on the same fixtures:

* ``direct``    -- stored Direct Qwen final guard (``m5/base`` or ``m5/H3``);
* ``mace``      -- stored Full MACE final guard (``m5/A3``, ``m5/H2`` or ``m5/H3``);
* ``pure``      -- symbolic derivation with helper summaries disabled;
* ``symbolic``  -- symbolic derivation with verified local helper summaries.

Every guard is re-checked on the *full declared finite domain* with the existing
bounded checker (level ``BOUNDED``); a pass is a bounded result, not a proof.
Token counts and wall-clock time come from the stored runs; symbolic runtime is
measured here.

Usage: python scripts/m6_symbolic.py [--json m6/symbolic.json] [--md m6/symbolic.md]
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mace import sandbox  # noqa: E402
from mace.contracts import ContractError, parse_bundle  # noqa: E402
from mace.fixture import Fixture, load_fixture  # noqa: E402
from mace.loop import _guard_only_bundle  # noqa: E402
from mace.symbolic import derive_guard, node_count, parse_expr, SymbolicError  # noqa: E402

DEV6 = ["alt_masking", "dedup_channel", "modulo_absorb",
        "overwrite_channel", "sort_channel", "swap_channels"]
HELD1 = ["dead_flag", "dict_slot", "parity_snap"]
HELD2 = ["clamp_absorb", "toggle_pair"]
SETS = {"dev6": DEV6, "held1": HELD1, "held2": HELD2}
ALL = DEV6 + HELD1 + HELD2
STORED = {
    "dev6": {"direct": "m5/base/{f}/direct_seed42.json",
             "mace": "m5/A3/{f}/mace_seed42.json"},
    "held1": {"direct": "m5/base/{f}/direct_seed42.json",
              "mace": "m5/H2/{f}/mace_seed42.json"},
    "held2": {"direct": "m5/H3/{f}/direct_seed42.json",
              "mace": "m5/H3/{f}/mace_seed42.json"},
}


def check_guard(fixture: Fixture, guard: str | None) -> Dict[str, Any]:
    """Re-check a guard on every case of the declared finite domain."""
    if not guard:
        return {"status": "ABSENT", "typed": False, "unsound": None,
                "incomplete": None, "exact": False, "error": "no guard"}
    try:
        bundle = parse_bundle(_guard_only_bundle(guard), allow_guard_only=True)
        report = sandbox.analyze(
            fixture.source, list(fixture.domain.cases), bundle.to_dict(),
            arg_sorts=fixture.arg_sorts, functions=fixture.functions,
            channels=fixture.channels, level="BOUNDED", entry=fixture.entry,
            timeout=300.0)
    except (ContractError, sandbox.SandboxError, ValueError) as exc:
        return {"status": "ERROR", "typed": False, "unsound": None,
                "incomplete": None, "exact": False,
                "error": f"{type(exc).__name__}: {exc}"}
    guard_report = report.get("guard") or {}
    unsound = guard_report.get("unsound")
    incomplete = guard_report.get("incomplete")
    typed = guard_report.get("status") not in ("INVALID", "ERROR", None)
    exact = typed and unsound == 0 and incomplete == 0
    return {"status": guard_report.get("status"), "typed": typed,
            "unsound": unsound, "incomplete": incomplete, "exact": exact,
            "error": guard_report.get("reason")}


def guard_nodes(guard: str | None) -> int:
    if not guard:
        return 0
    try:
        return node_count(parse_expr(guard))
    except (SyntaxError, ValueError):
        return 0


def stored_run(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    usage = data.get("usage") or {}
    bundle = data.get("final_bundle") or {}
    relations = [r for r in (bundle.get("relations") or [])
                 + (bundle.get("target_effects") or [])
                 + (bundle.get("upstream") or [])
                 + (bundle.get("observers") or [])
                 if isinstance(r, dict)]
    source_lines = sum(len(r.get("source_lines") or []) for r in relations)
    rationales = sum(1 for r in relations if (r.get("rationale") or "").strip())
    return {"guard": data.get("final_guard"),
            "status": data.get("status"),
            "tokens": int(usage.get("prompt_tokens") or 0)
                      + int(usage.get("completion_tokens") or 0),
            "wall_seconds": float(usage.get("wall_seconds") or 0.0),
            "explain": {"relations": len(relations), "rationales": rationales,
                        "source_lines": source_lines}}


def symbolic_run(fixture: Fixture, use_summaries: bool) -> Dict[str, Any]:
    start = time.perf_counter()
    try:
        result = derive_guard(fixture, use_summaries=use_summaries)
        error = None
    except SymbolicError as exc:  # derive_guard normally catches these
        result = {"status": "UNKNOWN", "guard": None, "reason": str(exc),
                  "paths": 0, "node_count": 0, "explanation": [],
                  "coverage": {"ratio": 0.0, "covered": 0, "total": 0}}
        error = str(exc)
    elapsed = time.perf_counter() - start
    explanation = result.get("explanation") or []
    rules = sum(len(item.get("channels") or []) for item in explanation)
    return {"guard": result.get("guard"), "status": result.get("status"),
            "reason": result.get("reason"), "paths": result.get("paths", 0),
            "nodes": result.get("node_count", 0),
            "coverage": result.get("coverage") or {},
            "wall_seconds": elapsed, "tokens": 0,
            "explain": {"paths": len(explanation), "channel_rules": rules},
            "error": error}


def method_row(fixture_id: str, fixture: Fixture, name: str,
               guard: str | None, meta: Mapping[str, Any]) -> Dict[str, Any]:
    checked = check_guard(fixture, guard)
    return {"fixture": fixture_id, "method": name, "guard": guard,
            "check": checked, "nodes": guard_nodes(guard),
            "chars": len(guard or ""), **meta}


def analyse() -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    for fixture_id in ALL:
        fixture = load_fixture(fixture_id + ".json")
        set_name = next(s for s, ids in SETS.items() if fixture_id in ids)
        for method in ("direct", "mace"):
            path = ROOT / STORED[set_name][method].format(f=fixture_id)
            if not path.exists():
                continue
            data = stored_run(path)
            rows.append(method_row(fixture_id, fixture, method, data["guard"], {
                "set": set_name, "stored_status": data["status"],
                "tokens": data["tokens"], "wall_seconds": data["wall_seconds"],
                "explain": data["explain"], "paths": None, "coverage": None}))
        for name, use_summaries in (("pure", False), ("symbolic", True)):
            data = symbolic_run(fixture, use_summaries)
            rows.append(method_row(fixture_id, fixture, name, data["guard"], {
                "set": set_name, "stored_status": data["status"],
                "tokens": 0, "wall_seconds": data["wall_seconds"],
                "explain": data["explain"], "paths": data["paths"],
                "coverage": data["coverage"], "reason": data.get("reason")}))
    return {"fixtures": ALL, "sets": SETS, "rows": rows}


METHOD_LABEL = {"direct": "Direct Qwen", "mace": "Full MACE (A)",
                "pure": "Pure Symbolic", "symbolic": "Symbolic + summaries"}
ORDER = ["direct", "mace", "pure", "symbolic"]


def aggregate(rows: Sequence[Mapping[str, Any]], fixtures: Sequence[str]
              ) -> List[Dict[str, Any]]:
    out = []
    for method in ORDER:
        subset = [r for r in rows if r["method"] == method
                  and r["fixture"] in fixtures]
        if not subset:
            continue
        checks = [r["check"] for r in subset]
        nodes = sorted(r["nodes"] for r in subset)
        line = {
            "method": METHOD_LABEL[method],
            "cases": len(subset),
            "derived": sum(1 for r in subset if r["guard"]),
            "unknown": sum(1 for r in subset if not r["guard"]),
            "exact": sum(1 for c in checks if c["exact"]),
            "sound": sum(1 for c in checks
                         if c["typed"] and c["unsound"] == 0),
            "complete": sum(1 for c in checks
                            if c["typed"] and c["incomplete"] == 0),
            "nodes_median": nodes[len(nodes) // 2] if nodes else 0,
            "nodes_max": nodes[-1] if nodes else 0,
            "tokens": sum(r["tokens"] for r in subset),
            "wall": round(sum(r["wall_seconds"] for r in subset), 2),
        }
        out.append(line)
    return out


def markdown(data: Mapping[str, Any]) -> str:
    rows = data["rows"]
    parts = ["# M6 phase 3: symbolic engine vs stored Qwen/MACE guards", "",
             "Every guard is re-checked on the full declared finite domain; a pass "
             "is `BOUNDED`, never `PROVEN`. `pure` disables helper summaries and "
             "therefore has no way to model the helper functions. Symbolic "
             "runtime is wall-clock on this machine (CPU, no model).", ""]
    for set_name, fixtures in SETS.items():
        table = aggregate(rows, fixtures)
        parts += [f"## {set_name}", "",
                  "| method | cases | derived | UNKNOWN | exact | sound | complete | "
                  "median nodes | max nodes | tokens | wall s |",
                  "|---|---|---|---|---|---|---|---|---|---|---|"]
        for line in table:
            parts.append("| {method} | {cases} | {derived} | {unknown} | {exact} | "
                         "{sound} | {complete} | {nodes_median} | {nodes_max} | "
                         "{tokens} | {wall} |".format(**line))
        parts.append("")
    parts += ["## Per-fixture checks", "",
              "| fixture | method | guard | status | exact | unsound | incomplete | "
              "nodes | paths | coverage | wall s |",
              "|---|---|---|---|---|---|---|---|---|---|---|"]
    for row in rows:
        check = row["check"]
        coverage = row.get("coverage") or {}
        parts.append("| {f} | {m} | `{g}` | {s} | {e} | {u} | {i} | {n} | {p} | "
                     "{c} | {w} |".format(
                         f=row["fixture"], m=METHOD_LABEL[row["method"]],
                         g=(row["guard"] or "-"),
                         s=check["status"],
                         e="yes" if check["exact"] else "no",
                         u=check["unsound"], i=check["incomplete"],
                         n=row["nodes"], p=row.get("paths") or "-",
                         c=coverage.get("ratio", "-"),
                         w=round(row["wall_seconds"], 3)))
    parts += ["", "## Explanation and cost", "",
              "| fixture | method | explanation units | tokens | source stmts covered |",
              "|---|---|---|---|---|"]
    for row in rows:
        explain = row.get("explain") or {}
        units = []
        for key in ("paths", "channel_rules", "relations", "rationales",
                    "source_lines"):
            if explain.get(key):
                units.append(f"{key}={explain[key]}")
        coverage = row.get("coverage") or {}
        parts.append(f"| {row['fixture']} | {METHOD_LABEL[row['method']]} | "
                     f"{', '.join(units) or '-'} | {row['tokens']} | "
                     f"{coverage.get('covered', '-')}/{coverage.get('total', '-')} |")
    parts.append("")
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="m6/symbolic.json")
    parser.add_argument("--md", default="m6/symbolic.md")
    args = parser.parse_args()
    data = analyse()
    json_path = ROOT / args.json
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    text = markdown(data)
    (ROOT / args.md).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
