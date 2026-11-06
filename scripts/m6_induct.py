"""M6 phase 4: bounded condition induction on the A-masking obligation.

Runs ``mace.induct`` on a chosen fixture set, re-checks every learned guard on
the full declared finite domain, and compares it with the stored Direct Qwen
and Full MACE guards from ``m6/symbolic.json``.  Nothing here reads a reference
guard.  The eval half of each domain is never used for candidate selection.

The script records SHA-256 hashes of the implementation files so a held-out run
can be tied to the frozen code.

Usage
-----
    python scripts/m6_induct.py --sets dev6 --pool both \
        --json m6/induct_dev.json --md m6/induct_dev.md
    python scripts/m6_induct.py --sets held1,held2 --pool full \
        --json m6/induct_held.json --md m6/induct_held.md
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mace.fixture import load_fixture  # noqa: E402
from mace.induct import induce  # noqa: E402
from mace.symbolic import node_count, parse_expr  # noqa: E402

DEV6 = ["alt_masking", "dedup_channel", "modulo_absorb",
        "overwrite_channel", "sort_channel", "swap_channels"]
HELD1 = ["dead_flag", "dict_slot", "parity_snap"]
HELD2 = ["clamp_absorb", "toggle_pair"]
SETS = {"dev6": DEV6, "held1": HELD1, "held2": HELD2}


def file_hash(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def git_head() -> str | None:
    try:
        out = subprocess.run(["git", "rev-parse", "HEAD"], cwd=str(ROOT),
                             capture_output=True, text=True, timeout=10)
        return out.stdout.strip() or None
    except (OSError, subprocess.SubprocessError):
        return None


def guard_size(guard: str | None) -> int:
    if not guard:
        return 0
    try:
        return node_count(parse_expr(guard))
    except (SyntaxError, ValueError):
        return 0


def reference_rows() -> Dict[str, Dict[str, Any]]:
    path = ROOT / "m6" / "symbolic.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    out: Dict[str, Dict[str, Any]] = {}
    for row in data.get("rows") or []:
        if row["method"] in ("direct", "mace"):
            out.setdefault(row["fixture"], {})[row["method"]] = row
    return out


def run_set(fixtures: Sequence[str], levels: Sequence[str]) -> Dict[str, Any]:
    results: Dict[str, Any] = {}
    for name in fixtures:
        fixture = load_fixture(name + ".json")
        for level in levels:
            result = induce(fixture, level=level)
            results[f"{name}/{level}"] = result
    return results


def summarise(results: Mapping[str, Any], references: Mapping[str, Any],
              fixtures: Sequence[str], levels: Sequence[str]) -> List[Dict[str, Any]]:
    rows = []
    for method in ("direct", "mace"):
        picked = [references.get(f, {}).get(method) for f in fixtures]
        picked = [p for p in picked if p]
        checks = [p["check"] for p in picked]
        rows.append({"method": "Direct Qwen" if method == "direct" else "Full MACE (A)",
                     "cases": len(picked),
                     "exact": sum(1 for c in checks if c["exact"]),
                     "sound": sum(1 for c in checks
                                  if c.get("typed") and c["unsound"] == 0),
                     "complete": sum(1 for c in checks
                                     if c.get("typed") and c["incomplete"] == 0),
                     "tokens": sum(p["tokens"] for p in picked),
                     "wall": round(sum(p["wall_seconds"] for p in picked), 2),
                     "nodes": 0})
    for level in levels:
        for direction in ("sufficient", "necessary"):
            picked = [results.get(f"{name}/{level}") for name in fixtures]
            picked = [p for p in picked if p]
            if not picked:
                continue
            rows.append({
                "method": f"Induction ({level}, {direction})",
                "cases": len(picked),
                "exact": sum(1 for p in picked if p[direction]["eval"]["exact"]),
                "sound": sum(1 for p in picked if p[direction]["eval"]["sound"]),
                "complete": sum(1 for p in picked if p[direction]["eval"]["complete"]),
                "tokens": 0,
                "wall": round(sum(p["seconds"] for p in picked), 2),
                "nodes": 0,
            })
    return rows


def markdown(data: Mapping[str, Any]) -> str:
    results = data["results"]
    references = data["references"]
    parts = ["# M6 phase 4: bounded condition induction", "",
             f"Implementation SHA-256: `{data['implementation_sha256']}`; "
             f"git HEAD: `{data['git_head']}`. Sets: {', '.join(data['sets'])}; "
             f"pool levels: {', '.join(data['levels'])}.", "",
             "The guard predicts whether replacing A by `pass` leaves every "
             "returned channel unchanged. Selection uses the fit half only; "
             "the eval half is disjoint and is not used for candidate choice. "
             "All verdicts are bounded (`BOUNDED`/`TESTED`), never `PROVEN`.", ""]
    for set_name in data["sets"]:
        fixtures = SETS[set_name]
        table = summarise(results, references, fixtures, data["levels"])
        parts += [f"## {set_name}", "",
                  "| method | cases | exact | sound | complete | tokens | wall s |",
                  "|---|---|---|---|---|---|---|"]
        for row in table:
            parts.append("| {m} | {c} | {e} | {s} | {k} | {t} | {w} |".format(
                m=row["method"], c=row["cases"], e=row["exact"], s=row["sound"],
                k=row["complete"], t=row["tokens"], w=row["wall"]))
        parts.append("")
        parts += ["| fixture | direction | guard | check | unsound | incomplete | "
                  "nodes | clauses | eval kind | seconds |",
                  "|---|---|---|---|---|---|---|---|---|---|"]
        for name in fixtures:
            for level in data["levels"]:
                result = results.get(f"{name}/{level}")
                if not result:
                    continue
                for direction, check_key in (("sufficient", "check"),
                                             ("necessary", "necessary_check")):
                    entry = result[direction]
                    check = result[check_key]
                    parts.append(
                        f"| {name}/{level} | {direction} | `{entry['guard']}` | "
                        f"{check['status']} | {check['unsound']} | "
                        f"{check['incomplete']} | "
                        f"{guard_size(entry['guard'])} | {entry['clauses']} | "
                        f"{entry['kind']} | {round(result['seconds'], 2)} |")
        parts.append("")
    parts += ["## Witness and repair totals", "",
              "| fixture/level | witnesses | masked | unmasked | pool | clauses | "
              "learn failures | repair steps |",
              "|---|---|---|---|---|---|---|---|"]
    for key, result in results.items():
        w = result["witnesses"]
        repair_steps = len(result["sufficient"]["repair"])
        parts.append(f"| {key} | {w['total']} | {w['masked']} | {w['unmasked']} | "
                     f"{result['pool']['size']} | {result['sufficient']['clauses']} | "
                     f"{result['sufficient']['failures']} | {repair_steps} |")
    parts.append("")
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--sets", default="dev6",
                        help="comma list of dev6, held1, held2")
    parser.add_argument("--pool", default="full", choices=["full", "generic", "both"])
    parser.add_argument("--json", default=None)
    parser.add_argument("--md", default=None)
    args = parser.parse_args()

    sets = [s.strip() for s in args.sets.split(",") if s.strip()]
    levels = ["generic", "full"] if args.pool == "both" else [args.pool]
    fixtures = [name for s in sets for name in SETS[s]]
    results = run_set(fixtures, levels)
    implementation = "".join(file_hash(ROOT / p) for p in
                             ("mace/induct.py", "scripts/m6_induct.py"))
    data = {
        "sets": sets, "levels": levels, "fixtures": fixtures,
        "implementation_sha256": hashlib.sha256(implementation.encode()).hexdigest(),
        "git_head": git_head(),
        "results": results,
        "references": reference_rows(),
    }
    json_path = ROOT / (args.json or f"m6/induct_{'-'.join(sets)}.json")
    md_path = ROOT / (args.md or f"m6/induct_{'-'.join(sets)}.md")
    json_path.parent.mkdir(parents=True, exist_ok=True)
    json_path.write_text(json.dumps(data, indent=2, ensure_ascii=False),
                         encoding="utf-8")
    text = markdown(data)
    md_path.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
