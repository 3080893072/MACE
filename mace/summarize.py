"""Cross-run summarizer.

Reads ``runs/*/*_seed*.json`` artifacts and prints one row per (run, mode) with
the quantities the experiments actually report:

* the final guard and its bounded verdict (soundness and completeness are
  separate columns, never merged),
* how many relations of each kind reached BOUNDED / TESTED / REFUTED / INVALID,
* round 1 versus the final round, so "did counterexample feedback help?" is a
  measured quantity and not an impression,
* token and wall-clock cost, so baselines can be compared at matched budget.

Usage:
    python -m mace.cli summarize --runs runs/m2_20261030_084711 ...
    python -m mace.cli summarize --runs runs --json out.json
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List

GOOD = ("BOUNDED", "TESTED")


def _guard_metrics(report: Dict[str, Any]) -> Dict[str, Any]:
    guard = (report or {}).get("guard") or {}
    return {
        "status": guard.get("status"),
        "unsound": guard.get("unsound"),
        "incomplete": guard.get("incomplete"),
        "expr": guard.get("expr"),
    }


def _relation_counts(report: Dict[str, Any]) -> Dict[str, int]:
    out: Dict[str, int] = {}
    for rel in (report or {}).get("relations") or []:
        key = f"{rel.get('kind')}:{rel.get('status')}"
        out[key] = out.get(key, 0) + 1
    return out


def _failing(report: Dict[str, Any]) -> int:
    return sum(1 for rel in (report or {}).get("relations") or []
               if rel.get("status") not in GOOD)


def _row(path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    report = data.get("final_report") or {}
    exchanges = data.get("exchanges") or []
    first = (exchanges[0].get("report") if exchanges else None) or {}
    first_guard = _guard_metrics(first)
    final_guard = _guard_metrics(report)
    usage = data.get("usage") or {}
    bad = (final_guard["unsound"] or 0) + (final_guard["incomplete"] or 0)
    first_bad = (first_guard["unsound"] or 0) + (first_guard["incomplete"] or 0)
    return {
        "run": path.parent.name,
        "fixture": data.get("fixture"),
        "model": data.get("model"),
        "mode": data.get("mode"),
        "status": data.get("status"),
        "rounds": data.get("rounds_used"),
        "parse_errors": sum(1 for e in exchanges if e.get("error")),
        "guard": final_guard["expr"],
        "guard_status": final_guard["status"],
        "guard_unsound": final_guard["unsound"],
        "guard_incomplete": final_guard["incomplete"],
        "guard_ok": (report.get("guard_ok") is True),
        "derived_status": (report.get("composition") or {}).get("status"),
        "relations": _relation_counts(report),
        "failing_relations": _failing(report),
        "first_guard_status": first_guard["status"],
        "first_guard_bad_rows": first_bad,
        "final_guard_bad_rows": bad,
        "guard_improved": (bad < first_bad) if first_guard["status"] else None,
        "prompt_tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "wall_seconds": round(usage.get("wall_seconds") or 0.0, 1),
    }


def collect(runs: Iterable[Path]) -> List[Dict[str, Any]]:
    rows = []
    for run in runs:
        if not run.is_dir():
            continue
        for path in sorted(run.glob("*_seed*.json")):
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            rows.append(_row(path, data))
    return rows


def markdown(rows: List[Dict[str, Any]]) -> str:
    head = ("| fixture | model | mode | guard ok | unsound/incomplete | round1 -> final | "
            "failing rels | parse err | prompt tok | out tok | s |")
    sep = "|" + "---|" * 11
    lines = [head, sep]
    for row in rows:
        lines.append(
            f"| {row['fixture']} | {row['model']} | {row['mode']} | "
            f"{'yes' if row['guard_ok'] else 'no'} | "
            f"{row['guard_unsound']}/{row['guard_incomplete']} | "
            f"{row['first_guard_bad_rows']} -> {row['final_guard_bad_rows']} | "
            f"{row['failing_relations']} | {row['parse_errors']} | "
            f"{row['prompt_tokens']} | {row['completion_tokens']} | "
            f"{row['wall_seconds']} |")
    return "\n".join(lines)
