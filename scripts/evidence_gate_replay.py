"""Evidence-gate replay: controlled evaluation of the Evidence-Gated Local Relations mechanism.

No model is called.  Each stored M5/M6 MACE run already contains the model's
final contract and the bounded verification report for it.  This script holds
those proposals fixed and compares:

* ``direct``   -- stored Direct Qwen final guard;
* ``mace``     -- stored Full MACE final guard (Qwen-written);
* ``compose``  -- deterministic composer over every relation the original
                  verifier accepted (the gate-OFF ablation);
* ``gated``    -- deterministic composer over WITNESS_VERIFIED relations only
                  (the gate-ON condition).

The last two differ only in the gate, so their difference is the mechanism's
independent effect at fixed proposals.  Every guard is checked on the full
declared finite domain; a pass is BOUNDED, never PROVEN.  The 11 fixtures were
already inspected during M5/M6, so this is exploratory evidence, not a held-out
test.

Usage: python scripts/evidence_gate_replay.py [--json evidence_gate/replay.json]
                                                [--md evidence_gate/replay.md]
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

from mace import evidence_gate as gate  # noqa: E402
from mace.contracts import parse_bundle  # noqa: E402
from mace.fixture import load_fixture  # noqa: E402
from scripts.m6_symbolic import ALL, SETS, STORED, check_guard  # noqa: E402

METHODS = ["direct", "mace", "compose", "gated"]
LABEL = {"direct": "Direct Qwen", "mace": "Full MACE",
         "compose": "Composer (gate OFF)", "gated": "Evidence-gated composer"}


def _load(path: Path) -> Dict[str, Any] | None:
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def _classify(check: Mapping[str, Any], guard: str | None) -> Dict[str, Any]:
    typed = bool(check.get("typed"))
    unsound = check.get("unsound")
    incomplete = check.get("incomplete")
    if not guard:
        outcome = "unknown"
    elif not typed:
        outcome = "invalid"
    elif (unsound or 0) > 0:
        outcome = "unsound"
    elif (incomplete or 0) > 0:
        outcome = "incomplete"
    else:
        outcome = "exact"
    return {"outcome": outcome, "sound": typed and (unsound or 0) == 0,
            "exact": outcome == "exact", "typed": typed,
            "unsound": unsound, "incomplete": incomplete}


def _guard_facts(fixture_id: str, guard: str | None) -> Dict[str, Any]:
    fixture = load_fixture(fixture_id + ".json")
    started = time.perf_counter()
    check = check_guard(fixture, guard)
    return {"guard": guard, "check": check, "wall_seconds": time.perf_counter() - started,
            "eval_executions": 2 * len(fixture.domain.cases),
            **_classify(check, guard)}


def _verification_calls(run: Mapping[str, Any]) -> int:
    return sum(1 for ex in run.get("exchanges") or [] if ex.get("report"))


def _program_executions(run: Mapping[str, Any]) -> int:
    total = 0
    for ex in run.get("exchanges") or []:
        report = ex.get("report") or {}
        total += 2 * int(report.get("domain_size") or report.get("usable_rows") or 0)
    return total


def analyse() -> Dict[str, Any]:
    rows: List[Dict[str, Any]] = []
    audit: List[Dict[str, Any]] = []
    for fixture_id in ALL:
        set_name = next(s for s, ids in SETS.items() if fixture_id in ids)
        fixture = load_fixture(fixture_id + ".json")
        direct = _load(ROOT / STORED[set_name]["direct"].format(f=fixture_id))
        mace = _load(ROOT / STORED[set_name]["mace"].format(f=fixture_id))
        if mace is None or not mace.get("final_bundle") or not mace.get("final_report"):
            rows.append({"fixture": fixture_id, "set": set_name, "error": "no stored MACE bundle"})
            continue
        bundle = parse_bundle(mace["final_bundle"])
        report = mace["final_report"]
        gated = gate.gate_report(report)
        composed = gate.compose_ungated(bundle, report, fixture.channels)
        gated_composed = gate.compose_gated(bundle, report, fixture.channels)

        guards = {
            "direct": (direct or {}).get("final_guard"),
            "mace": mace.get("final_guard"),
            "compose": composed.get("expr"),
            "gated": gated_composed.get("expr"),
        }
        facts = {name: _guard_facts(fixture_id, guards[name]) for name in METHODS}
        usage = mace.get("usage") or {}
        direct_usage = (direct or {}).get("usage") or {}
        rows.append({
            "fixture": fixture_id, "set": set_name, "channels": fixture.channels,
            "domain_size": len(fixture.domain), "domain_exhaustive": fixture.domain.exhaustive,
            "methods": facts,
            "mace_status": mace.get("status"),
            "rounds_used": mace.get("rounds_used"),
            "mace_tokens": int(usage.get("prompt_tokens") or 0)
                           + int(usage.get("completion_tokens") or 0),
            "mace_wall_seconds": float(usage.get("wall_seconds") or 0.0),
            "direct_tokens": int(direct_usage.get("prompt_tokens") or 0)
                             + int(direct_usage.get("completion_tokens") or 0),
            "verification_calls": _verification_calls(mace),
            "verification_executions": _program_executions(mace),
            "gate_counts": gated["evidence_gate"]["counts"],
            "compose_status": composed.get("status"),
            "gated_compose_status": gated_composed.get("status"),
            "composed_parts": composed.get("parts") or [],
            "gated_parts": gated_composed.get("parts") or [],
        })

        used_ungated = {p.get("relation") for p in composed.get("parts") or []}
        for record in gated["evidence_gate"]["records"]:
            audit.append({
                "fixture": fixture_id, "id": record["id"], "kind": record["kind"],
                "role": record["role"], "channel": record["channel"],
                "verifier_status": record["verifier_status"],
                "evidence_status": record["evidence_status"],
                "gate_reason": record["gate_reason"],
                "evidence": record["evidence"],
                "used_by_ungated_composer": record["id"] in used_ungated,
                "accepted_by_verifier": record["verifier_status"] in ("BOUNDED", "TESTED"),
                "accepted_by_gate": record["evidence_status"] == gate.WITNESS_VERIFIED,
            })
    return {"fixtures": ALL, "sets": SETS, "rows": rows, "relation_audit": audit}


def aggregate(rows: Sequence[Mapping[str, Any]], fixtures: Sequence[str]) -> List[Dict[str, Any]]:
    out = []
    for method in METHODS:
        subset = [r for r in rows if r.get("methods") and r["fixture"] in fixtures]
        if not subset:
            continue
        facts = [r["methods"][method] for r in subset]
        out.append({
            "method": LABEL[method], "cases": len(subset),
            "exact": sum(1 for f in facts if f["exact"]),
            "sound": sum(1 for f in facts if f["sound"]),
            "incomplete": sum(1 for f in facts if f["outcome"] == "incomplete"),
            "invalid": sum(1 for f in facts if f["outcome"] == "invalid"),
            "unknown": sum(1 for f in facts if f["outcome"] == "unknown"),
            "unsound": sum(1 for f in facts if f["outcome"] == "unsound"),
            "tokens": sum(r.get("direct_tokens" if method == "direct" else
                                "mace_tokens", 0) for r in subset)
                      if method in ("direct", "mace") else 0,
            "method_wall": round(sum(r.get("mace_wall_seconds", 0.0) for r in subset), 2)
                           if method == "mace" else 0.0,
            "eval_executions": sum(f["eval_executions"] for f in facts),
        })
    return out


def _delta(rows: Sequence[Mapping[str, Any]], a: str, b: str) -> Dict[str, List[str]]:
    gained = [r["fixture"] for r in rows if r.get("methods")
              and r["methods"][b]["exact"] and not r["methods"][a]["exact"]]
    lost = [r["fixture"] for r in rows if r.get("methods")
            and r["methods"][a]["exact"] and not r["methods"][b]["exact"]]
    return {"gained_exact": gained, "lost_exact": lost}


def markdown(data: Mapping[str, Any]) -> str:
    rows = data["rows"]
    audit = data["relation_audit"]
    parts = [
        "# Evidence-Gated Local Relations — controlled replay",
        "",
        "Stored M5/M6 proposals are held fixed; no model call is made. "
        "`compose` and `gated` use the same deterministic composer and differ "
        "only in whether unverified relations are admitted. Every guard is "
        "re-checked on the full declared finite domain (`BOUNDED`, never "
        "`PROVEN`). The 11 fixtures were inspected in M5/M6, so this is "
        "exploratory evidence, not a held-out test.",
        "",
    ]
    for set_name, fixtures in SETS.items():
        parts += [f"## {set_name}", "",
                  "| method | cases | exact | sound | incomplete | invalid | unknown | "
                  "unsound | tokens | wall s |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for line in aggregate(rows, fixtures):
            parts.append("| {method} | {cases} | {exact} | {sound} | {incomplete} | "
                         "{invalid} | {unknown} | {unsound} | {tokens} | {method_wall} |"
                         .format(**line))
        parts.append("")
    parts += ["## Overall", "",
              "| method | cases | exact | sound | incomplete | invalid | unknown | "
              "unsound | tokens |",
              "|---|---|---|---|---|---|---|---|---|"]
    for line in aggregate(rows, ALL):
        parts.append("| {method} | {cases} | {exact} | {sound} | {incomplete} | "
                     "{invalid} | {unknown} | {unsound} | {tokens} |".format(**line))
    parts.append("")

    compose_vs_gated = _delta(rows, "compose", "gated")
    parts += ["## Gate effect at fixed proposals", "",
              f"* gate ON gains exact guards: {compose_vs_gated['gained_exact'] or 'none'}",
              f"* gate ON loses exact guards: {compose_vs_gated['lost_exact'] or 'none'}",
              ""]

    rejected = [a for a in audit if a["accepted_by_verifier"] and not a["accepted_by_gate"]]
    used = [a for a in rejected if a["used_by_ungated_composer"]]
    parts += [f"* relations accepted by the original verifier: "
              f"{sum(1 for a in audit if a['accepted_by_verifier'])}/{len(audit)}",
              f"* rejected by the gate: {len(rejected)}",
              f"* rejected relations that the gate-off composer had used: {len(used)}",
              ""]
    if rejected:
        parts += ["| fixture | relation | kind | verifier | gate | reason | used by composer |",
                  "|---|---|---|---|---|---|---|"]
        for a in rejected:
            parts.append(f"| {a['fixture']} | {a['id']} | {a['kind']} | "
                         f"{a['verifier_status']} | {a['evidence_status']} | "
                         f"{a['gate_reason']} | {'yes' if a['used_by_ungated_composer'] else 'no'} |")
        parts.append("")

    parts += ["## Per-fixture guards", "",
              "| fixture | set | Direct | Full MACE | Composer (gate OFF) | Gated | "
              "gate counts (W/R/U) |",
              "|---|---|---|---|---|---|---|"]
    for r in rows:
        if not r.get("methods"):
            continue
        counts = r["gate_counts"]
        parts.append("| {f} | {s} | {d} | {m} | {c} | {g} | {w}/{rf}/{u} |".format(
            f=r["fixture"], s=r["set"],
            d=f"{r['methods']['direct']['outcome']}",
            m=f"{r['methods']['mace']['outcome']}",
            c=f"{r['methods']['compose']['outcome']}",
            g=f"{r['methods']['gated']['outcome']}",
            w=counts.get(gate.WITNESS_VERIFIED, 0),
            rf=counts.get(gate.REFUTED, 0),
            u=counts.get(gate.UNVERIFIED, 0)))
    parts += ["", "## Per-fixture guard strings", "",
              "| fixture | method | guard | status | unsound | incomplete |",
              "|---|---|---|---|---|---|"]
    for r in rows:
        if not r.get("methods"):
            continue
        for method in METHODS:
            f = r["methods"][method]
            check = f["check"]
            parts.append(f"| {r['fixture']} | {LABEL[method]} | `{f['guard'] or '-'}` | "
                         f"{check.get('status')} | {check.get('unsound')} | "
                         f"{check.get('incomplete')} |")
    parts += ["", "## Cost", "",
              "| fixture | method | tokens | model wall s | verification calls | "
              "verification program runs | evaluation program runs |",
              "|---|---|---|---|---|---|---|"]
    for r in rows:
        if not r.get("methods"):
            continue
        for method in METHODS:
            parts.append(f"| {r['fixture']} | {LABEL[method]} | "
                         f"{r.get('direct_tokens', 0) if method == 'direct' else (r.get('mace_tokens', 0) if method == 'mace' else 0)} | "
                         f"{r.get('mace_wall_seconds', 0.0) if method == 'mace' else 0.0} | "
                         f"{r.get('verification_calls', 0) if method == 'mace' else 0} | "
                         f"{r.get('verification_executions', 0) if method == 'mace' else 0} | "
                         f"{r['methods'][method]['eval_executions']} |")
    parts += ["",
              "The gate adds no model calls and no program executions: it reuses the "
              "counters and paired rows already produced by the bounded checker. "
              "Evaluation runs are the re-check of each candidate guard and are not "
              "part of the method's inference cost.",
              ""]
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="evidence_gate/replay.json")
    parser.add_argument("--md", default="evidence_gate/replay.md")
    args = parser.parse_args()
    data = analyse()
    json_path = ROOT / args.json
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    text = markdown(data)
    (ROOT / args.md).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
