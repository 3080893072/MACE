"""Cross-run summary for the M5 diagnosis.

For every stored run: the final guard verdict, the best guard verdict seen in
any round, and whether the repair loop ended worse than its best round.  The
last column is what distinguishes "the model cannot solve this" from "the loop
threw away a solved case".

Usage: python scripts/m5_report.py RUN_DIR [RUN_DIR ...]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path


def rank(guard: dict | None) -> int:
    if not guard:
        return 0
    status = guard.get("status")
    if status == "INVALID" or status is None:
        return 1
    if status in ("BOUNDED", "TESTED") and not guard.get("unsound") and not guard.get("incomplete"):
        return 4
    if not guard.get("unsound"):
        return 3          # sound, but rejects masked inputs
    return 2              # typed, but accepts exposed inputs


def verdict(guard: dict | None) -> str:
    if not guard:
        return "-"
    status = guard.get("status")
    if status == "INVALID":
        return "INVALID"
    if status in ("BOUNDED", "TESTED") and not guard.get("unsound") and not guard.get("incomplete"):
        return "exact"
    if not guard.get("unsound"):
        return "sound-incomplete"
    return "unsound"


def main(paths: list[str]) -> int:
    rows = []
    for directory in paths:
        for path in sorted(Path(directory).glob("*/[a-z]*_seed42.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            report = data.get("final_report") or {}
            rounds = [(e.get("report") or {}).get("guard") for e in data.get("exchanges") or []]
            best = max(rounds, key=rank) if rounds else None
            final = report.get("guard")
            rows.append({
                "run": Path(directory).name,
                "fixture": data.get("fixture"),
                "mode": data.get("mode"),
                "status": data.get("status"),
                "rounds": data.get("rounds_used"),
                "final": verdict(final),
                "final_expr": (final or {}).get("expr"),
                "best": verdict(best),
                "best_expr": (best or {}).get("expr"),
                "regressed": rank(best) > rank(final),
                "tokens": (data.get("usage") or {}).get("prompt_tokens"),
                "seconds": round((data.get("usage") or {}).get("wall_seconds") or 0, 1),
            })
    head = ("| run | fixture | mode | final | best round | regressed | tokens | s |")
    print(head)
    print("|" + "---|" * 8)
    for r in rows:
        print(f"| {r['run']} | {r['fixture']} | {r['mode']} | {r['final']} | {r['best']} | "
              f"{'YES' if r['regressed'] else ''} | {r['tokens']} | {r['seconds']} |")
    exact = sum(r["final"] == "exact" for r in rows)
    lost = sum(r["regressed"] and r["best"] == "exact" for r in rows)
    print(f"\ncases {len(rows)}, final exact {exact}, regressed-from-exact {lost}")
    for r in rows:
        if r["regressed"]:
            print(f"  {r['fixture']}: best {r['best']} {r['best_expr']!r} -> final {r['final']} {r['final_expr']!r}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
