"""Aggregate the stored M5 runs into the tables used by docs/M5_diagnosis.md.

Reads the ``cells_*.json`` snapshots (one row per stored run, with both the
model's guard and the deterministic composer's guard re-checked under the
current checker) and groups them by fixture set and method.  No model calls and
no re-verification happen here: this only counts.

Usage: python scripts/m5_tables.py [OUT.md]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
M5 = ROOT / "m5"

DEV6 = ["alt_masking", "dedup_channel", "modulo_absorb",
        "overwrite_channel", "sort_channel", "swap_channels"]
HELD1 = ["dead_flag", "dict_slot", "parity_snap"]
HELD2 = ["clamp_absorb", "toggle_pair"]

# (directory, display label) for the main methods
METHODS = {
    ("A3", "A"): "MACE A (Qwen contract + Qwen guard)",
    ("A3", "B"): "MACE B (Qwen contract + deterministic composition)",
    ("base", "qwen-direct"): "direct guard prompt, 3 rounds",
    ("base", "qwen-generic"): "generic masking prompt, 3 rounds",
    ("base", "qwen-fixed"): "fixed guard template, 3 rounds",
    ("T", "qwen-direct"): "direct guard prompt, 12 rounds (token-matched)",
    ("C", "C"): "C reviewed contract + Qwen guard (diagnostic only)",
    ("C", "D"): "D reviewed contract + composition (diagnostic only)",
}


def entries(directory: str):
    rows = json.loads((M5 / f"cells_{directory}.json").read_text(encoding="utf-8"))
    out = []
    for row in rows:
        cell = row.get("cell")
        sources = ["qwen"]
        if cell in ("A", "C"):
            sources.append("derived")
        for source in sources:
            if source == "qwen":
                label = {"A": "A", "C": "C"}.get(cell, f"qwen-{cell}")
            else:
                label = "B" if cell == "A" else "D"
            guard = row[f"guard_{source}"]
            out.append({
                "fixture": row["fixture"],
                "key": (directory, label),
                "guard": guard,
                "contract_verified": bool(row["contract"]["verified"]),
                "attn_ok": bool(row["attribution"]["relations_on_reference_lines"]),
                "attn_cited": row["attribution"]["relations_cited"],
                "attn_hit": row["attribution"]["relations_on_reference_lines"],
                "tokens": row["tokens"] or 0,
                "wall": row["wall_seconds"] or 0.0,
            })
    return out


def fmt(name: str, members):
    n = len(members)
    typed = sum(1 for m in members if m["guard"]["typecheck_ok"])
    sound = sum(1 for m in members if m["guard"]["sound"])
    complete = sum(1 for m in members if m["guard"]["complete"])
    exact = sum(1 for m in members if m["guard"]["exact"])
    contract = sum(1 for m in members if m["contract_verified"])
    cited = sum(m["attn_cited"] for m in members)
    hit = sum(m["attn_hit"] for m in members)
    attn = f"{hit}/{cited}" if cited else "n/a"
    tokens = sum(m["tokens"] for m in members)
    wall = sum(m["wall"] for m in members)
    return (f"| {name} | {n} | {typed} | {sound} | {complete} | {exact} | "
            f"{contract} | {attn} | {tokens} | {wall:.0f} |")


HEAD = ("| method | cases | typed | sound | complete | exact | "
        "contract all-pass | attribution | tokens | s |")
SEP = "|" + "---|" * 10


def table(title: str, fixtures, dirs, extra_methods=()):
    pool = [e for d in dirs for e in entries(d) if e["fixture"] in fixtures]
    lines = [f"### {title}", "", HEAD, SEP]
    seen = set()
    for key, name in list(METHODS.items()) + list(extra_methods):
        members = [m for m in pool if m["key"] == key]
        if not members or key in seen:
            continue
        seen.add(key)
        lines.append(fmt(name, members))
    return "\n".join(lines)


def main(out: str | None) -> int:
    parts = [
        table("Dev set: the six original fixtures", DEV6, ["A3", "base", "T", "C"]),
        table("Held-out batch 1 (used during the parser-fix diagnosis)", HELD1,
              ["H", "H2", "C"],
              [(("H", "A"), "MACE (pre parser fix)"),
               (("H", "qwen-direct"), "direct guard prompt, 3 rounds (pre fix)"),
               (("H", "qwen-generic"), "generic masking prompt, 3 rounds (pre fix)"),
               (("H", "qwen-fixed"), "fixed guard template, 3 rounds (pre fix)"),
               (("H2", "A"), "MACE A, rerun after parser fix"),
               (("H2", "B"), "MACE B, rerun after parser fix")]),
        table("Held-out batch 2 (never used before this evaluation)", HELD2,
              ["H3"],
              [(("H3", "A"), "MACE A (Qwen contract + Qwen guard)"),
               (("H3", "qwen-direct"), "direct guard prompt, 3 rounds"),
               (("H3", "qwen-generic"), "generic masking prompt, 3 rounds"),
               (("H3", "qwen-fixed"), "fixed guard template, 3 rounds")]),
    ]
    text = "\n\n".join(parts) + """
Notes
-----
* ``typed`` = guard parsed and type-checked; ``sound`` = typed and accepts no
  exposed input; ``complete`` = typed and rejects no masked input; ``exact`` =
  bounded-domain equality with the true mask.  Sound/complete are one-sided and
  are reported even when the overall verdict is REFUTED.
* ``contract all-pass`` means every non-guard relation reached BOUNDED/TESTED.
* ``attribution`` counts relations whose cited lines intersect the reviewed
  contract's cited lines.  It measures source-line overlap, not logical
  support; it is n/a where no relations were produced.
* Tokens are prompt tokens as reported by Ollama; s is model wall time, not
  including verification.
* Cells C/D are diagnostics on human-reviewed contracts, never system scores.
"""
    if out:
        Path(out).write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1] if len(sys.argv) > 1 else None))
