"""Offline feasibility check for a Direct-First MACE variant.

No model is called and no reference guard is read.  The stored M5/M6 Direct and
Full MACE runs are re-used as fixed proposals.  For every fixture this script
asks whether the *runtime* evidence available to the verifier is enough to

* detect that the Direct guard G0 is wrong (false accepts / false rejects),
* decide among the existing candidates (G0, the MACE guard, the deterministic
  composer over MACE relations), and
* repair G0 without touching the fixtures where G0 is already exact.

Selection in the simulated policy uses only the bounded check of each candidate
on the declared finite domain (paired executions).  The reference bundles are
never loaded.  The 11 fixtures were already inspected in M5/M6, so this is an
exploratory replay, not a held-out experiment, and it is not an online run.

Usage: python scripts/direct_first_feasibility.py [--json direct_first/feasibility.json]
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Mapping

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.m6_symbolic import ALL, SETS, STORED  # noqa: E402

REPLAY = ROOT / "evidence_gate" / "replay.json"


def _stored(path: str) -> Dict[str, Any]:
    return json.loads((ROOT / path).read_text(encoding="utf-8"))


def _direct_facts(path: str) -> Dict[str, Any]:
    data = _stored(path)
    guard = (data.get("final_report") or {}).get("guard") or {}
    checked = guard.get("checked") or 0
    usable = (data.get("final_report") or {}).get("usable_rows") or 0
    return {
        "guard": data.get("final_guard"),
        "status": guard.get("status"),
        "unsound": guard.get("unsound") or 0,       # false accepts
        "incomplete": guard.get("incomplete") or 0, # false rejects (no eval errors when checked == usable)
        "checked": checked,
        "usable_rows": usable,
        "guard_eval_errors": max(0, usable - checked),
        "counterexamples": guard.get("counterexamples") or [],
        "contrasts": guard.get("contrasts") or [],
        "tokens": int((data.get("usage") or {}).get("prompt_tokens") or 0)
                  + int((data.get("usage") or {}).get("completion_tokens") or 0),
        "wall_seconds": float((data.get("usage") or {}).get("wall_seconds") or 0.0),
    }


def _relation_evidence(path: str) -> Dict[str, Any]:
    data = _stored(path)
    rows = (data.get("final_report") or {}).get("relations") or []
    refuted = [r["id"] for r in rows if r.get("status") == "REFUTED"]
    invalid = [r["id"] for r in rows if r.get("status") == "INVALID"]
    observer_fail = [
        {"id": r["id"], "invariance_checked": r.get("invariance_checked") or 0,
         "invariance_failures": r.get("invariance_failures") or 0,
         "faithful_failures": r.get("faithful_failures") or 0,
         "faithful_minus_failures": r.get("faithful_minus_failures") or 0,
         "evaluation_errors": r.get("evaluation_errors") or 0}
        for r in rows if r.get("kind") == "observer"
        and (r.get("invariance_failures") or r.get("faithful_failures")
             or r.get("faithful_minus_failures") or r.get("evaluation_errors"))
    ]
    return {"relations": len(rows), "refuted": refuted, "invalid": invalid,
            "observer_failures": observer_fail,
            "tokens": int((data.get("usage") or {}).get("prompt_tokens") or 0)
                      + int((data.get("usage") or {}).get("completion_tokens") or 0),
            "wall_seconds": float((data.get("usage") or {}).get("wall_seconds") or 0.0)}


def analyse() -> Dict[str, Any]:
    replay = json.loads(REPLAY.read_text(encoding="utf-8"))
    by_fixture = {r["fixture"]: r for r in replay["rows"]}
    rows: List[Dict[str, Any]] = []
    for fixture_id in ALL:
        set_name = next(s for s, ids in SETS.items() if fixture_id in ids)
        base = by_fixture[fixture_id]
        methods = base["methods"]
        direct = _direct_facts(STORED[set_name]["direct"].format(f=fixture_id))
        mace = _relation_evidence(STORED[set_name]["mace"].format(f=fixture_id))

        d_out, m_out = methods["direct"]["outcome"], methods["mace"]["outcome"]
        c_out, g_out = methods["compose"]["outcome"], methods["gated"]["outcome"]
        if methods["direct"]["exact"]:
            choice = "Direct"
        elif methods["compose"]["exact"]:
            choice = "Composer"
        elif methods["gated"]["exact"]:
            choice = "Gated"
        else:
            choice = "Direct (unrepaired)"
        chosen = {"Direct": methods["direct"], "Composer": methods["compose"],
                  "Gated": methods["gated"]}.get(choice, methods["direct"])
        rows.append({
            "fixture": fixture_id, "set": set_name,
            "direct": {"guard": direct["guard"], "outcome": d_out,
                       "unsound": direct["unsound"], "incomplete": direct["incomplete"],
                       "guard_eval_errors": direct["guard_eval_errors"],
                       "counterexamples": direct["counterexamples"][:3],
                       "contrasts": direct["contrasts"][:2]},
            "mace": {"guard": methods["mace"]["guard"], "outcome": m_out,
                     "unsound": methods["mace"]["check"].get("unsound"),
                     "incomplete": methods["mace"]["check"].get("incomplete"),
                     **mace},
            "composer": {"guard": methods["compose"]["guard"], "outcome": c_out},
            "gated": {"guard": methods["gated"]["guard"], "outcome": g_out},
            "choice": choice, "chosen_exact": bool(chosen["exact"]),
            "direct_tokens": direct["tokens"], "direct_wall": direct["wall_seconds"],
            "mace_tokens": mace["tokens"], "mace_wall": mace["wall_seconds"],
        })

    def cell(d_exact: bool, m_exact: bool) -> List[str]:
        return [r["fixture"] for r in rows
                if (r["direct"]["outcome"] == "exact") == d_exact
                and (r["mace"]["outcome"] == "exact") == m_exact]

    matrix = {
        "both_exact": cell(True, True),
        "direct_only": cell(True, False),
        "mace_only": cell(False, True),
        "both_wrong": cell(False, False),
    }
    union = sorted(set(matrix["both_exact"]) | set(matrix["direct_only"])
                   | set(matrix["mace_only"]))

    def policy(name: str, pick) -> Dict[str, Any]:
        out = []
        for r in rows:
            method = pick(r)
            exact = bool(r[method]["outcome"] == "exact")
            out.append({"fixture": r["fixture"], "method": method, "exact": exact})
        return {"policy": name, "exact": sum(1 for x in out if x["exact"]),
                "cases": out}

    policies = [
        policy("Direct only", lambda r: "direct"),
        policy("Full MACE only", lambda r: "mace"),
        policy("Composer only", lambda r: "composer"),
        policy("Direct-First (keep exact G0, else composer)", lambda r: (
            "direct" if r["direct"]["outcome"] == "exact" else "composer")),
        policy("Direct-First (keep exact G0, else gated composer)", lambda r: (
            "direct" if r["direct"]["outcome"] == "exact" else "gated")),
    ]

    refuted = [r for r in rows if r["direct"]["outcome"] != "exact"]
    cost = {
        "direct_tokens_all": sum(r["direct_tokens"] for r in rows),
        "direct_wall_all": round(sum(r["direct_wall"] for r in rows), 2),
        "mace_tokens_on_refuted": sum(r["mace_tokens"] for r in refuted),
        "mace_wall_on_refuted": round(sum(r["mace_wall"] for r in refuted), 2),
        "mace_tokens_all": sum(r["mace_tokens"] for r in rows),
        "mace_wall_all": round(sum(r["mace_wall"] for r in rows), 2),
    }
    cost["direct_first_tokens"] = cost["direct_tokens_all"] + cost["mace_tokens_on_refuted"]
    cost["direct_first_wall"] = round(cost["direct_wall_all"] + cost["mace_wall_on_refuted"], 2)
    return {"fixtures": ALL, "rows": rows, "matrix": matrix,
            "oracle_union": union, "policies": policies, "cost": cost,
            "note": ("Oracle union is a post-hoc ceiling scored with the reference "
                     "semantics; it is not a method result. Selection in the "
                     "Direct-First policies uses only the bounded check.")}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="direct_first/feasibility.json")
    args = parser.parse_args()
    data = analyse()
    path = ROOT / args.json
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")
    m = data["matrix"]
    print("both exact      :", m["both_exact"])
    print("Direct only     :", m["direct_only"])
    print("MACE only       :", m["mace_only"])
    print("both wrong      :", m["both_wrong"])
    print("oracle union    :", data["oracle_union"])
    for p in data["policies"]:
        print(f'{p["policy"]:48s} exact={p["exact"]}/11', [x["fixture"] for x in p["cases"] if x["exact"]])
    print("cost:", data["cost"])
    print("wrote", path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
