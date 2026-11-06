"""M6 phase 2: replay the stored M5 rounds under four guard-retention policies.

The M5 loop keeps the *last* guard each round.  On these fixtures that is
sometimes worse than an earlier guard: a round can be exact and later rounds can
replace it.  This script does not call the model.  It reads the per-round guards
already stored in ``m5/`` and re-checks each one on two disjoint halves of the
declared finite domain:

* ``fit``   -- the only half an online policy is allowed to look at;
* ``eval``  -- disjoint inputs used only to measure the policy afterwards.

Policies compared
-----------------
first       round-1 guard (the first non-empty candidate)
final       last-round guard (what M5 reports today)
online      keep a fit-valid guard; replace it only when it has been revoked by
            a fit counterexample or when no valid guard is held yet
best-ever   offline diagnostic ceiling: the candidate with the best *eval*
            score, which is not an implementable online policy

Usage: python scripts/m6_repair.py [--json m6/repair.json] [--md m6/repair.md]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping, Sequence

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mace import sandbox  # noqa: E402
from mace.contracts import ContractError, parse_bundle  # noqa: E402
from mace.fixture import Fixture, load_fixture  # noqa: E402
from mace.loop import _guard_only_bundle  # noqa: E402

DEV6 = ["alt_masking", "dedup_channel", "modulo_absorb",
        "overwrite_channel", "sort_channel", "swap_channels"]
HELD1 = ["dead_flag", "dict_slot", "parity_snap"]
HELD2 = ["clamp_absorb", "toggle_pair"]
SETS = {"dev6": DEV6, "held1": HELD1, "held2": HELD2}
METHOD_LABEL = {
    "A3/qwen": "MACE A (Qwen guard)",
    "A3/derived": "MACE B (composition)",
    "H2/qwen": "MACE A (held-out rerun)",
    "H2/derived": "MACE B (held-out rerun)",
    "H3/qwen": "MACE A (held-out batch 2)",
    "H3/derived": "MACE B (held-out batch 2)",
    "base/direct": "direct prompt",
    "base/generic": "generic prompt",
    "base/fixed": "fixed template",
    "T/direct": "direct prompt, 12 rounds",
    "C/qwen": "C reviewed contract + Qwen guard",
    "C/derived": "D reviewed contract + composition",
}


def split_cases(cases: Sequence[Mapping[str, Any]], seed: int = 20261030
                ) -> tuple[List[Mapping[str, Any]], List[Mapping[str, Any]]]:
    """Deterministic half/half split keyed by the input, independent of order."""
    digest = [hashlib.sha256((str(seed) + repr(case)).encode("utf-8")).hexdigest()
              for case in cases]
    order = sorted(range(len(cases)), key=lambda index: digest[index])
    return ([cases[i] for i in order[::2]],
            [cases[i] for i in order[1::2]])


def check_guard(fixture: Fixture, cases: Sequence[Mapping[str, Any]], guard: str
                ) -> Dict[str, Any]:
    """Bounded check of one guard on one input set (level TESTED: it is a subset)."""
    if not guard:
        return {"status": "ABSENT", "typed": False, "unsound": None,
                "incomplete": None, "exact": False, "error": "no guard"}
    try:
        bundle = parse_bundle(_guard_only_bundle(guard), allow_guard_only=True)
        report = sandbox.analyze(
            fixture.source, list(cases), bundle.to_dict(),
            arg_sorts=fixture.arg_sorts, functions=fixture.functions,
            channels=fixture.channels, level="TESTED", entry=fixture.entry,
            timeout=180.0)
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


def rounds_of(path: Path) -> List[Dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    out: List[Dict[str, Any]] = []
    for exchange in data.get("exchanges") or []:
        report = exchange.get("report") or {}
        qwen = exchange.get("guard")
        if qwen is None:
            bundle = exchange.get("bundle") or {}
            qwen = (bundle.get("mask_guard") or {}).get("expr")
        derived = (((report.get("composition") or {}).get("derived_guard")) or {}).get("expr")
        out.append({"round": exchange.get("round"), "qwen": qwen, "derived": derived})
    return out


def collect_runs() -> List[Dict[str, Any]]:
    runs: List[Dict[str, Any]] = []
    for directory in ("A3", "H", "H2", "H3", "base", "T", "C"):
        base = ROOT / "m5" / directory
        if not base.exists():
            continue
        for path in sorted(base.glob("*/*_seed*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            fixture = data.get("fixture")
            mode = data.get("mode")
            guard_source = data.get("guard_source") or "qwen"
            if mode == "mace":
                source = "derived" if guard_source == "derived" else "qwen"
                method = f"{directory}/{source}"
            elif mode == "oracle":
                source = "derived" if guard_source == "derived" else "qwen"
                method = f"{directory}/{source}"
            else:
                source = "qwen"
                method = f"{directory}/{mode}"
            runs.append({"path": path, "fixture": fixture, "mode": mode,
                         "source": source, "method": method,
                         "rounds": rounds_of(path)})
    return runs


class OnlineRetention:
    """Keep a validated guard; replace it only on revocation or first validity.

    ``recheck`` is called on the incumbent before every offer, so a domain that
    grows can revoke an old guard with a concrete counterexample.  A valid
    incumbent is never replaced by an invalid candidate.
    """

    def __init__(self, recheck):
        self.recheck = recheck
        self.incumbent = None
        self.history: List[Dict[str, Any]] = []

    def offer(self, candidate: Dict[str, Any]) -> Dict[str, Any] | None:
        revoked = False
        if self.incumbent is not None and not self.recheck(self.incumbent):
            self.incumbent = None
            revoked = True
        if self.incumbent is None:
            self.incumbent = candidate
        else:
            old_ok = self.recheck(self.incumbent)
            new_ok = self.recheck(candidate)
            if not old_ok and new_ok:
                self.incumbent = candidate
            elif not old_ok and not new_ok:
                # No validated guard exists; keep the latest for final reporting.
                self.incumbent = candidate
            # old_ok and new_ok: keep the earlier validated guard.
        self.history.append({"round": candidate.get("round"), "revoked": revoked,
                             "kept": self.incumbent.get("round")})
        return self.incumbent


def pick_first(rounds: Sequence[Dict[str, Any]]) -> Dict[str, Any] | None:
    for item in rounds:
        if item.get("guard"):
            return item
    return None


def pick_final(rounds: Sequence[Dict[str, Any]]) -> Dict[str, Any] | None:
    for item in reversed(rounds):
        if item.get("guard"):
            return item
    return None


def pick_best_ever(rounds: Sequence[Dict[str, Any]]) -> Dict[str, Any] | None:
    """Offline ceiling: uses eval labels, so it is diagnostic only."""
    scored = [item for item in rounds if item.get("guard")]
    if not scored:
        return None

    def key(item):
        ev = item["eval"]
        return (bool(ev["exact"]), -(ev["unsound"] or 0) - (ev["incomplete"] or 0),
                len(item["guard"]), -(item.get("round") or 0))
    return max(scored, key=key)


def size_of(expr: str | None) -> int:
    if not expr:
        return 0
    return len(expr)


def run_policy(rounds: Sequence[Dict[str, Any]], name: str) -> Dict[str, Any] | None:
    if name == "first":
        return pick_first(rounds)
    if name == "final":
        return pick_final(rounds)
    if name == "best-ever":
        return pick_best_ever(rounds)
    if name == "online":
        policy = OnlineRetention(lambda item: bool(item["fit"]["exact"]))
        chosen = None
        for item in rounds:
            if item.get("guard"):
                chosen = policy.offer(item)
        return chosen
    raise ValueError(name)


def evaluate_round(fixture: Fixture, cases_fit, cases_eval, guard: str) -> Dict[str, Any]:
    return {"guard": guard,
            "fit": check_guard(fixture, cases_fit, guard),
            "eval": check_guard(fixture, cases_eval, guard),
            "length": size_of(guard)}


def analyse() -> Dict[str, Any]:
    fixtures = {path.stem: load_fixture(path)
                for path in sorted((ROOT / "experiments").glob("*.json"))
                if path.stem != "hidden"}
    splits = {}
    for name, fixture in fixtures.items():
        fit, ev = split_cases(fixture.domain.cases)
        splits[name] = (fit, ev)
    cache: Dict[tuple, Dict[str, Any]] = {}

    def evaluated(fixture_id: str, guard: str) -> Dict[str, Any]:
        key = (fixture_id, guard)
        if key not in cache:
            fit, ev = splits[fixture_id]
            cache[key] = {"guard": guard,
                          "fit": check_guard(fixtures[fixture_id], fit, guard),
                          "eval": check_guard(fixtures[fixture_id], ev, guard),
                          "length": size_of(guard)}
        return cache[key]

    rows = []
    for run in collect_runs():
        fixture_id = run["fixture"]
        if fixture_id not in splits:
            continue
        items = []
        for item in run["rounds"]:
            guard = item.get(run["source"])
            if not guard:
                continue
            checked = evaluated(fixture_id, guard)
            items.append({**item, **checked})
        if not items:
            continue
        policies = {name: run_policy(items, name)
                    for name in ("first", "final", "online", "best-ever")}
        rows.append({
            "method": run["method"],
            "fixture": fixture_id,
            "rounds": len(items),
            "fit_size": len(splits[fixture_id][0]),
            "eval_size": len(splits[fixture_id][1]),
            "guards": [{"round": i.get("round"), "guard": i.get("guard"),
                        "fit": i["fit"], "eval": i["eval"]} for i in items],
            "policies": {name: (None if item is None else {
                "round": item.get("round"), "guard": item.get("guard"),
                "fit": item["fit"], "eval": item["eval"], "length": item["length"]})
                for name, item in policies.items()},
        })
    return {"split_seed": 20261030, "rows": rows}


def _aggregate(rows, methods, set_name):
    fixtures = SETS[set_name]
    out = []
    for method in methods:
        subset = [r for r in rows if r["method"] == method and r["fixture"] in fixtures]
        if not subset:
            continue
        line = {"method": METHOD_LABEL.get(method, method), "cases": len(subset)}
        for policy in ("first", "final", "online", "best-ever"):
            picks = [r["policies"][policy] for r in subset]
            exact = sum(1 for p in picks if p and p["eval"]["exact"])
            fit_ok = sum(1 for p in picks if p and p["fit"]["exact"])
            unsound = sum((p["eval"]["unsound"] or 0) if p else 0 for p in picks)
            incomplete = sum((p["eval"]["incomplete"] or 0) if p else 0 for p in picks)
            line[policy] = {"exact": exact, "fit_exact": fit_ok,
                            "eval_unsound": unsound, "eval_incomplete": incomplete}
        out.append(line)
    return out


def markdown(data: Mapping[str, Any]) -> str:
    rows = data["rows"]
    methods = sorted({r["method"] for r in rows},
                     key=lambda m: (m.split("/")[0], m))
    parts = ["# M6 phase 2: guard-retention replay", "",
             f"Split seed {data['split_seed']}; fit and eval are disjoint halves of the "
             "declared finite domain. `best-ever` uses eval labels and is a ceiling, "
             "not an online policy.", ""]
    for set_name in ("dev6", "held1", "held2"):
        table = _aggregate(rows, methods, set_name)
        if not table:
            continue
        parts += [f"## {set_name}", "",
                  "| method | cases | first | final | online | best-ever | online fit-valid |",
                  "|---|---|---|---|---|---|---|"]
        for line in table:
            parts.append("| {m} | {c} | {f} | {fi} | {o} | {b} | {of} |".format(
                m=line["method"], c=line["cases"],
                f=line["first"]["exact"], fi=line["final"]["exact"],
                o=line["online"]["exact"], b=line["best-ever"]["exact"],
                of=line["online"]["fit_exact"]))
        parts.append("")
    parts += ["## Runs where the final guard is worse than an earlier fit-valid guard", ""]
    lost = []
    for row in rows:
        guards = row["guards"]
        valid_early = [g for g in guards if g["fit"]["exact"]]
        final = row["policies"]["final"]
        if valid_early and final and not final["eval"]["exact"]:
            lost.append(row)
    if lost:
        parts += ["| method | fixture | valid rounds (fit) | final eval | online eval |",
                  "|---|---|---|---|---|"]
        for row in lost:
            valid = ", ".join(str(g["round"]) for g in row["guards"] if g["fit"]["exact"])
            fin = row["policies"]["final"]["eval"]
            on = row["policies"]["online"]["eval"]
            parts.append(f"| {row['method']} | {row['fixture']} | {valid} | "
                         f"{'exact' if fin['exact'] else 'wrong'} "
                         f"(u={fin['unsound']}, i={fin['incomplete']}) | "
                         f"{'exact' if on['exact'] else 'wrong'} "
                         f"(u={on['unsound']}, i={on['incomplete']}) |")
    else:
        parts.append("None.")
    parts.append("")
    return "\n".join(parts)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", default="m6/repair.json")
    parser.add_argument("--md", default="m6/repair.md")
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
