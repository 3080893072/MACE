"""Offline A/B/C/D replay of the core-logic repair.

This script makes *no* model calls.  It replaces Qwen with a fake client that
replays the exact ``raw_response`` strings already stored in the frozen M5 run
directory, then drives the four loop levels:

    A  legacy       historical Full MACE
    B  bugs         verifier/control-flow fixes only
    C  candidates   fixes + candidate retention
    D  full         fixes + retention + witness-gated composition

Every result is labelled ``FIXED_PROPOSAL_REPLAY``.  These are not new online
Qwen experiments and must not be reported as such.

The replay reads no reference guard and no offline exact label.  Every metric is
computed by the bounded checker on the fixture's finite domain.

Usage:
    python scripts/core_logic_replay.py [--only fixture ...] [--out runs/core_logic_replay]

Outputs:
    <out>/replay.json                  full per-cell evidence
    <out>/<level>/<fixture>/...        per-run loop artifacts
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mace import loop  # noqa: E402
from mace.core_logic import EXACT, classify_guard_report  # noqa: E402
from mace.fixture import load_fixture  # noqa: E402
from mace.qwen import Response  # noqa: E402

REPLAY_LABEL = "FIXED_PROPOSAL_REPLAY"
LEVELS = (("A", "legacy"), ("B", "bugs"), ("C", "candidates"), ("D", "full"))
A3_DIR = ROOT / "m5" / "A3"
H3_DIR = ROOT / "m5" / "H3"
FIXTURES = {
    "alt_masking": A3_DIR / "alt_masking" / "mace_seed42.json",
    "dead_flag": A3_DIR / "dead_flag" / "mace_seed42.json",
    "dedup_channel": A3_DIR / "dedup_channel" / "mace_seed42.json",
    "dict_slot": A3_DIR / "dict_slot" / "mace_seed42.json",
    "modulo_absorb": A3_DIR / "modulo_absorb" / "mace_seed42.json",
    "overwrite_channel": A3_DIR / "overwrite_channel" / "mace_seed42.json",
    "parity_snap": A3_DIR / "parity_snap" / "mace_seed42.json",
    "sort_channel": A3_DIR / "sort_channel" / "mace_seed42.json",
    "swap_channels": A3_DIR / "swap_channels" / "mace_seed42.json",
    "clamp_absorb": H3_DIR / "clamp_absorb" / "mace_seed42.json",
    "toggle_pair": H3_DIR / "toggle_pair" / "mace_seed42.json",
}


class FixedProposalClient:
    """A model-shaped client that only replays frozen proposal strings."""

    provider = REPLAY_LABEL
    model = "fixed-m5-proposals"

    def __init__(self, responses: List[str]):
        self.responses = list(responses)
        self.calls: List[Dict[str, Any]] = []

    def chat(self, messages, purpose: str = "", json_mode: bool = True):
        content = self.responses.pop(0)
        stats = {"prompt_tokens": 0, "completion_tokens": 0,
                 "wall_seconds": 0.0}
        self.calls.append({"purpose": purpose, "messages": messages,
                           "stats": stats, "response": content})
        return Response(content=content, stats=stats)


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_proposals(path: Path) -> List[str]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out = []
    for exchange in data.get("exchanges") or []:
        raw = exchange.get("raw_response")
        out.append(raw if isinstance(raw, str) else "")
    if not out:
        raise SystemExit(f"no stored exchanges in {path}")
    return out


def _guard_metrics(report: Dict[str, Any]) -> Dict[str, Any]:
    guard = (report or {}).get("guard") or {}
    classification = classify_guard_report({"guard": guard}) if guard else "UNKNOWN"
    return {
        "classification": classification,
        "exact": classification == EXACT,
        "sound": (guard.get("status") in ("BOUNDED", "TESTED")
                  and int(guard.get("unsound") or 0) == 0
                  and int(guard.get("evaluation_errors") or 0) == 0),
        "status": guard.get("status"),
        "unsound": int(guard.get("unsound") or 0),
        "incomplete": int(guard.get("incomplete") or 0),
        "evaluation_errors": int(guard.get("evaluation_errors") or 0),
        "invalid": classification == "INVALID_CONTRACT",
        "unknown": classification == "UNKNOWN",
        "checked": int(guard.get("checked") or 0),
    }


def _round_metrics(result: Dict[str, Any]) -> List[Dict[str, Any]]:
    return list(result.get("candidate_rounds") or [])


def _best_was_exact(rounds: List[Dict[str, Any]]) -> bool:
    for item in rounds:
        if item.get("qwen_classification") == EXACT:
            return True
        if item.get("derived_classification") == EXACT:
            return True
    return False


def run_cell(fixture_id: str, proposal_path: Path, level: str,
             out_root: Path) -> Dict[str, Any]:
    responses = _load_proposals(proposal_path)
    fixture = load_fixture(f"{fixture_id}.json", seed=42)
    client = FixedProposalClient(responses)
    cell_dir = out_root / level / fixture_id
    result = loop.run_mode(
        fixture, client, "mace", rounds=len(responses), seed=42,
        out_dir=cell_dir, guard_source="qwen", evidence_gate=False,
        core_logic=level,
    )
    rounds = _round_metrics(result)
    final = _guard_metrics(result.get("final_report") or {})
    best_exact = _best_was_exact(rounds)
    return {
        "replay_label": REPLAY_LABEL,
        "fixture": fixture_id,
        "level": level,
        "proposal_source": str(proposal_path.relative_to(ROOT)),
        "proposal_sha256": _sha256(proposal_path),
        "proposals_replayed": len(responses),
        "status": result.get("status"),
        "rounds_used": result.get("rounds_used"),
        "final_guard": result.get("final_guard"),
        "selection": result.get("candidate_selection"),
        "final": final,
        "best_round_exact": best_exact,
        "degraded": bool(best_exact and not final["exact"]),
        "unresolved": not final["exact"] and not best_exact,
        "rounds": rounds,
        "usage": result.get("usage"),
    }


def _summary(cells: List[Dict[str, Any]]) -> Dict[str, Any]:
    def count(level, key):
        return sum(1 for c in cells if c["level"] == level and c[key])

    levels = [name for _, name in LEVELS]
    return {
        "replay_label": REPLAY_LABEL,
        "fixtures": sorted({c["fixture"] for c in cells}),
        "note": ("Offline replay of frozen M5 proposal strings; no model was "
                 "called. Metrics come from the bounded checker only."),
        "levels": {
            level: {
                "exact": sum(1 for c in cells
                             if c["level"] == level and c["final"]["exact"]),
                "sound": sum(1 for c in cells
                             if c["level"] == level and c["final"]["sound"]),
                "invalid": sum(1 for c in cells
                               if c["level"] == level and c["final"]["invalid"]),
                "unknown": sum(1 for c in cells
                               if c["level"] == level and c["final"]["unknown"]),
                "degraded": count(level, "degraded"),
                "unresolved": count(level, "unresolved"),
            }
            for level in levels
        },
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--only", nargs="*", choices=sorted(FIXTURES),
                        help="restrict to these fixtures")
    parser.add_argument("--levels", nargs="*", choices=[n for n, _ in LEVELS],
                        default=[n for n, _ in LEVELS])
    parser.add_argument("--out", default=str(ROOT / "runs" / "core_logic_replay"))
    args = parser.parse_args(argv)

    out_root = Path(args.out)
    chosen = args.only or sorted(FIXTURES)
    level_map = dict(LEVELS)
    cells: List[Dict[str, Any]] = []
    for fixture_id in chosen:
        path = FIXTURES[fixture_id]
        if not path.exists():
            raise SystemExit(f"missing frozen proposal file: {path}")
        for short in args.levels:
            level = level_map[short]
            print(f"[{REPLAY_LABEL}] {fixture_id} {short}/{level}", flush=True)
            cells.append(run_cell(fixture_id, path, level, out_root))

    payload = {
        "replay_label": REPLAY_LABEL,
        "summary": _summary(cells),
        "cells": cells,
    }
    out_root.mkdir(parents=True, exist_ok=True)
    out_path = out_root / "replay.json"
    out_path.write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                        encoding="utf-8")
    print(json.dumps(payload["summary"], indent=2, ensure_ascii=False))
    print(f"wrote {out_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
