"""Stage-by-stage diagnosis of a MACE run.

The question this module answers is not "was the guard right" but *where* a
run first went wrong.  Every run is decomposed into four stages

    target_effect  ->  upstream  ->  observer  ->  guard

and each stage is classified from the stored report.  A failure in an early
stage makes every later stage uninformative, so the first bad stage is the one
that matters.

It also separates the two reasons a guard can be unusable:

* ``INVALID``  -- it never type-checked (a notation problem),
* ``REFUTED``  -- it type-checked and is wrong on real inputs (a semantic
  problem).

Confusing those two would overstate how much of the failure is semantic.
"""
from __future__ import annotations

import json
import re
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

GOOD = ("BOUNDED", "TESTED")
BAD_ORDER = {"BOUNDED": 0, "TESTED": 0, "ABSENT": 0, "UNKNOWN": 2, "REFUTED": 3,
             "INVALID": 4, "VACUOUS": 4}
STAGES = ("target_effect", "upstream", "observer", "guard")


def classify_invalid(reason: Optional[str], expr: Optional[str] = None) -> str:
    """Name the *kind* of type error, so `_post` misuse can be counted apart.

    Only the first unknown name appears in the error, so an expression such as
    ``a == b_post and b == a_post`` reports ``a`` -- a local.  Whenever the
    expression itself is available, any ``*_post`` in it decides the category.
    """
    if expr and re.search(r"\b[A-Za-z_]\w*_post\b", str(expr)):
        return "post_reference"
    if not reason:
        return "other"
    text = str(reason)
    if "unknown variable" in text:
        tail = text.split("unknown variable:")[-1].strip()
        name = re.split(r"[\s,.;:()]+", tail, maxsplit=1)[0]
        if name.endswith("_post"):
            return "post_reference"
        if "entry arguments only" in text or "not in scope" in text:
            return "local_out_of_scope"
        return "unknown_name"
    if "entry arguments only" in text:
        return "post_reference"
    if "syntax" in text:
        return "syntax"
    if "sort" in text or re.search(r"expected \w+, got \w+", text):
        return "sort"
    return "other"


def _worst(statuses: Iterable[str]) -> str:
    statuses = [s for s in statuses if s]
    if not statuses:
        return "ABSENT"
    return max(statuses, key=lambda s: BAD_ORDER.get(s, 3))


def stage_status(report: Dict[str, Any]) -> Dict[str, str]:
    rels = (report or {}).get("relations") or []
    return {
        "target_effect": _worst(r["status"] for r in rels if r["kind"] == "target_effect"),
        "upstream": _worst(r["status"] for r in rels if r["kind"] == "upstream"),
        "observer": _worst(r["status"] for r in rels if r["kind"] == "observer"),
        "guard": ((report or {}).get("guard") or {}).get("status") or "ABSENT",
    }


def first_bad_stage(status: Dict[str, str]) -> str:
    for stage in STAGES:
        value = status.get(stage)
        if value == "ABSENT":
            continue          # no relation of that kind was written: nothing to fail
        if value not in GOOD:
            return stage
    return "none"


def _guard_metrics(report: Dict[str, Any]) -> Dict[str, Any]:
    guard = (report or {}).get("guard") or {}
    ok = guard.get("status") in GOOD
    unsound = guard.get("unsound") or 0
    incomplete = guard.get("incomplete") or 0
    return {
        "parsed": guard.get("status") != "INVALID",
        "typecheck_ok": guard.get("status") != "INVALID",
        "status": guard.get("status"),
        "sound": ok and unsound == 0,
        "complete": ok and incomplete == 0,
        "exact": ok and unsound == 0 and incomplete == 0,
        "unsound_rows": unsound,
        "incomplete_rows": incomplete,
        "invalid_kind": (classify_invalid(guard.get("reason"), guard.get("expr"))
                         if guard.get("status") == "INVALID" else ""),
        "expr": guard.get("expr"),
    }


def case_rows(path: Path, data: Dict[str, Any]) -> Dict[str, Any]:
    report = data.get("final_report") or {}
    exchanges = data.get("exchanges") or []
    first = (exchanges[0].get("report") if exchanges else None) or {}
    usage = data.get("usage") or {}
    status = stage_status(report)
    first_status = stage_status(first)
    invalid = [(r["id"], classify_invalid(r.get("reason"), r.get("expr")))
               for r in (report.get("relations") or []) if r["status"] == "INVALID"]
    return {
        "run": path.parent.name,
        "fixture": data.get("fixture"),
        "model": data.get("model"),
        "mode": data.get("mode"),
        "guard_source": data.get("guard_source") or "qwen",
        "diagnostic_only": bool(data.get("diagnostic_only")),
        "status": data.get("status"),
        "rounds": data.get("rounds_used"),
        "parse_errors": sum(1 for e in exchanges if e.get("error")),
        "stages_final": status,
        "stages_round1": first_status,
        "first_bad": first_bad_stage(status),
        "first_bad_round1": first_bad_stage(first_status),
        "invalid_relations": invalid,
        "invalid_kinds": sorted({k for _, k in invalid}),
        "guard": _guard_metrics(report),
        "qwen_guard": report.get("qwen_guard"),
        "witness_found": bool(report.get("witnesses")),
        "relations": {r["id"]: {"kind": r["kind"], "status": r["status"],
                                "expr": r["expr"], "condition": r["condition"],
                                "role": r.get("role"), "reason": r.get("reason")}
                      for r in (report.get("relations") or [])},
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
            rows.append(case_rows(path, data))
    return rows


def proportions(rows: List[Dict[str, Any]]) -> Dict[str, Any]:
    """The two ratios that keep notation failures from being read as reasoning."""
    invalid = [r for r in rows if r["guard"]["status"] == "INVALID"]
    invalid_post = [r for r in invalid if r["guard"]["invalid_kind"] == "post_reference"]
    invalid_local = [r for r in invalid if r["guard"]["invalid_kind"] == "local_out_of_scope"]
    invalid_other = [r for r in invalid
                     if r["guard"]["invalid_kind"] not in ("post_reference", "local_out_of_scope")]
    parsed = [r for r in rows if r["guard"]["typecheck_ok"]]
    semantic_bad = [r for r in parsed if not r["guard"]["exact"]]
    return {
        "cells": len(rows),
        "guard_typecheck_fail": len(invalid),
        "guard_typecheck_fail_post": len(invalid_post),
        "guard_typecheck_fail_local": len(invalid_local),
        "guard_typecheck_fail_other": len(invalid_other),
        "guard_typecheck_ok": len(parsed),
        "guard_correct_among_typed": len(parsed) - len(semantic_bad),
        "semantic_bad_among_typed": len(semantic_bad),
        "invalid_relation_ids": sorted({i for r in rows for i, _ in r["invalid_relations"]}),
    }


def markdown(rows: List[Dict[str, Any]]) -> str:
    head = ("| fixture | mode | guard src | first bad stage | target | upstream | observer | "
            "guard | guard status | unsound/inc | tokens | s |")
    lines = [head, "|" + "---|" * 12]
    for r in rows:
        s = r["stages_final"]
        lines.append(
            f"| {r['fixture']} | {r['mode']} | {r['guard_source']} | {r['first_bad']} | "
            f"{s['target_effect']} | {s['upstream']} | {s['observer']} | {s['guard']} | "
            f"{r['guard']['status']} | {r['guard']['unsound_rows']}/{r['guard']['incomplete_rows']} | "
            f"{r['prompt_tokens']} | {r['wall_seconds']} |")
    return "\n".join(lines)


def stage_markdown(rows: List[Dict[str, Any]]) -> str:
    """Aggregate: where the first error sits, and INVALID vs semantic guard errors."""
    counts: Dict[str, int] = {}
    groups: Dict[tuple, List[Dict[str, Any]]] = {}
    for r in rows:
        counts[r["first_bad"]] = counts.get(r["first_bad"], 0) + 1
        groups.setdefault((r["mode"], r["guard_source"]), []).append(r)

    lines = ["First bad stage over all cases: " + ", ".join(
        f"{k} {v}" for k, v in sorted(counts.items())), ""]
    head = ("| mode | guard src | cases | exact guard | contract all-pass | "
            "invalid guard | `_post` | local out of scope | other type | "
            "semantic errors (typed) | tokens | s |")
    lines += [head, "|" + "---|" * 11]
    for (mode, source), members in sorted(groups.items()):
        typed = [m for m in members if m["guard"]["typecheck_ok"]]
        invalid = [m for m in members if not m["guard"]["typecheck_ok"]]
        post = [m for m in invalid if m["guard"]["invalid_kind"] == "post_reference"]
        local = [m for m in invalid if m["guard"]["invalid_kind"] == "local_out_of_scope"]
        other = [m for m in invalid
                 if m["guard"]["invalid_kind"] not in ("post_reference", "local_out_of_scope")]
        semantic = [m for m in typed if not m["guard"]["exact"]]
        contract_ok = [m for m in members
                       if all(v in GOOD for k, v in m["stages_final"].items() if k != "guard")]
        tokens = sum(m["prompt_tokens"] or 0 for m in members)
        wall = sum(m["wall_seconds"] or 0 for m in members)
        lines.append(
            f"| {mode} | {source} | {len(members)} | "
            f"{sum(1 for m in members if m['guard']['exact'])} | {len(contract_ok)} | "
            f"{len(invalid)} | {len(post)} | {len(local)} | {len(other)} | "
            f"{len(semantic)} | {tokens} | {round(wall, 1)} |")
    return "\n".join(lines)
