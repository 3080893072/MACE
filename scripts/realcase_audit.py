"""Research-feasibility audit on the ten real-project cases.

Runs every *non-model* method on ``realcases/cases.json``:

* ``pure``      -- symbolic derivation, helper summaries disabled;
* ``symbolic``  -- symbolic derivation, verified local helper summaries allowed;
* ``human``     -- the hand-reviewed guard (reference row, never a system score);
* ``induct_generic`` / ``induct_full`` -- bounded condition induction, reported
  as a diagnostic, not as one of the four comparison methods.

Direct Qwen and Full MACE are listed as ``not_run``: this phase forbids new
model calls and no stored runs exist for these programs.  Nothing is imputed.

Every guard is re-checked on the full declared finite domain with the existing
bounded verifier.  A pass is ``BOUNDED``, never ``PROVEN``.  Token cost is zero
for every row because no model is called; wall-clock seconds are measured here.

Usage
-----
    python scripts/realcase_audit.py
"""
from __future__ import annotations

import hashlib
import json
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mace.domain import build_domain, input_sorts  # noqa: E402
from mace.fixture import Fixture  # noqa: E402
from mace.induct import induce, verify_guard  # noqa: E402
from mace.symbolic import derive_guard, node_count, parse_expr  # noqa: E402

CASES_PATH = ROOT / "realcases" / "cases.json"


def make_fixture(case: Mapping[str, Any]) -> Fixture:
    config = {"id": case["id"], "source": case["source_file"],
              "domain": case["domain"]}
    return Fixture(config=config, source=case["source"],
                   domain=build_domain(case["domain"]),
                   arg_sorts=input_sorts(case["domain"]), functions={},
                   channels=1, entry="program")


def guard_nodes(guard: str | None) -> int:
    if not guard:
        return 0
    try:
        return node_count(parse_expr(guard))
    except (SyntaxError, ValueError):
        return 0


def check(fixture: Fixture, guard: str | None) -> Dict[str, Any]:
    start = time.perf_counter()
    result = verify_guard(fixture, guard)
    result["seconds"] = time.perf_counter() - start
    result["nodes"] = guard_nodes(guard)
    result["check_status"] = result.get("status")
    return result


def human_row(case: Mapping[str, Any], fixture: Fixture) -> Dict[str, Any]:
    result = check(fixture, case["human_guard"])
    return {"method": "human", "guard": case["human_guard"],
            "compact": bool(case.get("human_guard_compact", True)),
            "note": case.get("human_guard_note"), **result}


def symbolic_row(fixture: Fixture, use_summaries: bool) -> Dict[str, Any]:
    start = time.perf_counter()
    result = derive_guard(fixture, use_summaries=use_summaries)
    seconds = time.perf_counter() - start
    explanation = result.get("explanation") or []
    attribution = {
        "paths": len(explanation),
        "channel_rules": sum(len(item.get("channels") or [])
                             for item in explanation),
        "coverage": result.get("coverage") or {},
    }
    row: Dict[str, Any] = {
        "method": "symbolic" if use_summaries else "pure",
        "derivation_status": result.get("status"),
        "status": result.get("status"),
        "reason": result.get("reason"),
        "guard": result.get("guard"),
        "paths": result.get("paths"),
        "attribution": attribution,
        "tokens": 0, "model_calls": 0,
        "seconds": seconds,
    }
    if result.get("status") == "DERIVED":
        row.update(check(fixture, result["guard"]))
    else:
        row.update({"check_status": "NOT_DERIVED", "exact": False,
                    "unsound": None, "incomplete": None,
                    "nodes": 0})
    return row


def induction_row(fixture: Fixture, level: str) -> Dict[str, Any]:
    start = time.perf_counter()
    result = induce(fixture, level=level)
    seconds = time.perf_counter() - start
    sufficient = result["sufficient"]
    check_result = result["check"] or {}
    return {
        "method": f"induct_{level}", "token": 0, "model_calls": 0,
        "guard": sufficient["guard"],
        "fit_exact": sufficient["fit"]["exact"],
        "eval_exact": sufficient["eval"]["exact"],
        "full_exact": sufficient["full"]["exact"],
        "check_status": check_result.get("status"),
        "exact": bool(check_result.get("exact")),
        "unsound": check_result.get("unsound"),
        "incomplete": check_result.get("incomplete"),
        "nodes": guard_nodes(sufficient["guard"]),
        "witnesses": result["witnesses"]["total"],
        "masked": result["witnesses"]["masked"],
        "pool": result["pool"]["size"],
        "clauses": sufficient["clauses"],
        "failures": sufficient["failures"],
        "necessary_exact": bool(result["necessary_check"]
                                and result["necessary_check"].get("exact")),
        "attribution": {"kind": "witness-only",
                        "source_lines": 0,
                        "witnesses": result["witnesses"]["total"]},
        "seconds": seconds,
    }


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git(*args: str) -> str:
    out = subprocess.run(["git", *args], cwd=str(ROOT), capture_output=True,
                         text=True, timeout=20)
    return out.stdout.strip()


def analyse() -> Dict[str, Any]:
    payload = json.loads(CASES_PATH.read_text(encoding="utf-8"))
    rows: List[Dict[str, Any]] = []
    cases_out: List[Dict[str, Any]] = []
    for case in payload["cases"]:
        fixture = make_fixture(case)
        human = human_row(case, fixture)
        pure = symbolic_row(fixture, use_summaries=False)
        symbolic = symbolic_row(fixture, use_summaries=True)
        generic = induction_row(fixture, "generic")
        full = induction_row(fixture, "full")
        entry = {
            "id": case["id"], "project": case["project"],
            "version": case["version"], "license": case["license"],
            "source_path": case["source_path"], "function": case["function"],
            "target": case["target"], "extraction_note": case["extraction_note"],
            "domain_cases": len(fixture.domain),
            "domain_text": fixture.domain_text(),
            "human_guard": human,
            "pure": pure, "symbolic": symbolic,
            "induct_generic": generic, "induct_full": full,
            "direct": {"method": "direct", "status": "not_run",
                       "reason": "no model calls in this phase; no stored run",
                       "tokens": None, "seconds": None},
            "mace": {"method": "mace", "status": "not_run",
                     "reason": "no model calls in this phase; no stored run",
                     "tokens": None, "seconds": None},
        }
        cases_out.append(entry)
        for row in (human, pure, symbolic, generic, full):
            rows.append({"case": case["id"], **row})
    return {
        "frozen_m1_m6_commit": "94912c12466054dcfc809e3bf45224137501ad9b",
        "freeze_manifest_commit": "7b3d2f5",
        "git_head": git("rev-parse", "HEAD"),
        "git_dirty": bool(git("status", "--porcelain", "--untracked-files=no")),
        "post_freeze_changes": {
            "mace/symbolic.py": sha256(ROOT / "mace" / "symbolic.py"),
            "scripts/realcase_audit.py": sha256(ROOT / "scripts" / "realcase_audit.py"),
            "scripts/build_realcases.py": sha256(ROOT / "scripts" / "build_realcases.py"),
            "realcases/cases.json": sha256(CASES_PATH),
            "note": "The symbolic target lookup was extended to AugAssign and "
                    "AnnAssign after the M6 freeze. All 11 M6 fixtures use a "
                    "plain Assign, so no frozen M6 number changes.",
        },
        "cases": cases_out,
        "rows": rows,
    }


def aggregate(cases: Sequence[Mapping[str, Any]], key: str) -> Dict[str, Any]:
    field = "human_guard" if key == "human" else key
    rows = [c[field] for c in cases]
    if key in ("direct", "mace"):
        return {"cases": len(rows), "measured": 0,
                "exact": None, "sound": None, "complete": None,
                "unknown": None, "tokens": None, "wall": None}
    if key == "human":
        return {"cases": len(rows), "measured": len(rows),
                "exact": sum(1 for r in rows if r["exact"]),
                "sound": sum(1 for r in rows
                             if r.get("status") != "ERROR" and r["unsound"] == 0),
                "complete": sum(1 for r in rows
                                if r.get("status") != "ERROR" and r["incomplete"] == 0),
                "unknown": 0, "tokens": 0,
                "wall": round(sum(r["seconds"] for r in rows), 3)}
    derived = [r for r in rows if r.get("guard")]
    return {"cases": len(rows), "measured": len(rows),
            "derived": len(derived),
            "unknown": len(rows) - len(derived),
            "exact": sum(1 for r in rows if r.get("exact")),
            "sound": sum(1 for r in rows
                         if r.get("check_status") not in ("INVALID", "ERROR", None)
                         and r["unsound"] == 0),
            "complete": sum(1 for r in rows
                            if r.get("check_status") not in ("INVALID", "ERROR", None)
                            and r["incomplete"] == 0),
            "tokens": 0,
            "wall": round(sum(r["seconds"] for r in rows), 3)}


def markdown(data: Mapping[str, Any]) -> str:
    cases = data["cases"]
    parts = [
        "# Real-project case audit (CPU, no model calls)",
        "",
        f"* Frozen M1-M6 through commit `{data['frozen_m1_m6_commit']}` "
        f"(manifest commit `{data['freeze_manifest_commit']}`).",
        f"* Audit git HEAD: `{data['git_head']}`; tracked tree dirty: "
        f"**{data['git_dirty']}** (this audit adds post-freeze files).",
        "* Direct Qwen and Full MACE are **not run**: this phase forbids new "
        "model calls and there are no stored runs for these programs.",
        "* Every guard check is `BOUNDED` on the declared finite domain; "
        "`PROVEN` is never emitted.",
        "",
        "## Per-method totals",
        "",
        "| method | cases | measured | derived | exact | sound | complete | "
        "UNKNOWN | tokens | wall s |",
        "|---|---|---|---|---|---|---|---|---|---|",
    ]
    labels = [("direct", "Direct Qwen"), ("mace", "Full MACE"),
              ("pure", "Pure Symbolic"), ("symbolic", "Symbolic + summaries"),
              ("human", "Human reference (not a system score)"),
              ("induct_generic", "Induction (generic pool, diagnostic)"),
              ("induct_full", "Induction (full pool, diagnostic)")]
    for key, label in labels:
        agg = aggregate(cases, key)
        parts.append("| {l} | {c} | {m} | {d} | {e} | {s} | {k} | {u} | "
                     "{t} | {w} |".format(
                         l=label, c=agg["cases"],
                         m=agg.get("measured", 0),
                         d=agg.get("derived", "-"),
                         e="-" if agg["exact"] is None else agg["exact"],
                         s="-" if agg["sound"] is None else agg["sound"],
                         k="-" if agg["complete"] is None else agg["complete"],
                         u="-" if agg["unknown"] is None else agg["unknown"],
                         t="not run" if agg["tokens"] is None else agg["tokens"],
                         w="not run" if agg["wall"] is None else agg["wall"]))
    parts += ["",
              "* Symbolic + summaries is identical to Pure Symbolic on these ten "
              "cases: none has a user-defined helper with a declared signature "
              "that the summary builder could use. The blockers are builtins, "
              "recursion, control-flow divergence, and one `while` loop.",
              "* Direct Qwen and Full MACE are not run, so their rows are "
              "`not_run`, never zero-accuracy results.",
              "", "## Per-case results", "",
              "| case | domain | direct | full MACE | human | pure | symbolic | "
              "induct generic | induct full |",
              "|---|---|---|---|---|---|---|---|---|"]
    for case in cases:
        def cell(row: Mapping[str, Any]) -> str:
            if row.get("status") == "not_run":
                return "not run"
            if not row.get("guard"):
                return f"UNKNOWN ({row.get('reason') or '-'})"
            return (f"`{row['guard'][:70]}` {row.get('check_status')} "
                    f"u={row.get('unsound')} i={row.get('incomplete')}")
        parts.append(f"| {case['id']} | {case['domain_cases']} | "
                     f"{cell(case['direct'])} | {cell(case['mace'])} | "
                     f"{cell(case['human_guard'])} | {cell(case['pure'])} | "
                     f"{cell(case['symbolic'])} | "
                     f"{cell(case['induct_generic'])} | "
                     f"{cell(case['induct_full'])} |")
    necessary = sum(1 for case in cases if case["induct_full"]["necessary_exact"])
    parts += ["", f"Induction necessary direction: {necessary}/{len(cases)} exact "
                  "(full pool). The necessary direction overfits, as in M6.", ""]
    parts += ["", "## Source and cost", "",
              "| case | source | target | pure s | symbolic s | induction s | "
              "witnesses | pool |", "|---|---|---|---|---|---|---|---|"]
    for case in cases:
        pure, symbolic = case["pure"], case["symbolic"]
        parts.append(f"| {case['id']} | {case['source_path']} | "
                     f"`{case['target']}` | {pure['seconds']:.3f} | "
                     f"{symbolic['seconds']:.3f} | "
                     f"{case['induct_full']['seconds']:.2f} | "
                     f"{case['induct_full']['witnesses']} | "
                     f"{case['induct_full']['pool']} |")
    parts += ["", "## Notes", ""]
    for case in cases:
        notes = []
        if not case["human_guard"]["compact"]:
            notes.append("human condition is an output-equivalence restatement, "
                         "not a compact semantic predicate")
        if case["human_guard"]["note"]:
            notes.append(case["human_guard"]["note"])
        if case["extraction_note"]:
            notes.append(case["extraction_note"])
        parts.append(f"* **{case['id']}**: " + " ".join(notes))
    parts.append("")
    return "\n".join(parts)


def main() -> int:
    data = analyse()
    json_path = ROOT / "realcases" / "audit.json"
    md_path = ROOT / "realcases" / "audit.md"
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    text = markdown(data)
    md_path.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
