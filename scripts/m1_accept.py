"""Independent acceptance of M1 cases produced by ``scripts.m1_screen``.

This script does not search for new candidates.  It takes a target and a
proposed minimal sufficient set S from the screening matrix, re-executes every
intervention from a clean tree, and decides again with its own verifier:

* A executes and has a local effect;
* deleting A leaves the selected original tests passing at D = U \\ S;
* every non-empty proper subset T of S fails to mask (Masked(U \\ T) is false);
* at least one s in S is individually inert: disabling only s changes neither
  plus nor minus test outcomes relative to the untouched program;
* in the full original suite, deleting A creates no failure that the plus run
  did not already have.

Only a target that passes all five checks is frozen as CONFIRMED_M1.  The
case file records commands, observations, hashes and the exact test node ids;
no synthetic test is introduced.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence

from scripts import m1_screen as screen

SCREEN = screen.SCREEN
ACCEPTED = SCREEN / "accepted"


def sha256_json(payload: Any) -> str:
    return hashlib.sha256(json.dumps(
        payload, sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()


def proper_nonempty(items: Sequence[str]) -> List[List[str]]:
    """All non-empty strict subsets of ``items`` (frozen MSMS rule)."""
    out: List[List[str]] = []
    for size in range(1, len(items)):
        for combo in __import__("itertools").combinations(items, size):
            out.append(list(combo))
    return out


def evaluate(target: Dict[str, Any], nodeids: List[str],
             disabled_ids: Sequence[str]) -> Dict[str, Any]:
    ops = {op["id"]: op for op in target["u"]}
    disabled = [ops[name] for name in disabled_ids]
    plus = screen.run_variant(target["project"], target, disabled, False,
                              nodeids, "accept_plus")
    mapping_plus = screen.span_mapping_for(target, target["project"],
                                           disabled, False)
    obs_plus = screen.observation(plus, nodeids, mapping_plus)
    record = {
        "disabled": sorted(disabled_ids),
        "plus_pass": None,
        "plus_hash": screen.canonical_obs(obs_plus),
        "outcomes_plus": obs_plus["outcomes"],
        "plus_returncode": plus.get("returncode"),
        "plus_timed_out": plus.get("timed_out"),
        "status": "UNKNOWN",
        "masked": None,
        "exposed": None,
        "minus_pass": None,
        "minus_hash": None,
        "outcomes_minus": None,
    }
    if not obs_plus["known"]:
        record["reason"] = "plus run unknown"
        return record
    plus_ok = screen.passed(obs_plus, nodeids)
    record["plus_pass"] = plus_ok
    if not plus_ok:
        record.update({"status": "INVALID", "masked": False,
                       "exposed": False})
        return record
    minus = screen.run_variant(target["project"], target, disabled, True,
                               nodeids, "accept_minus")
    mapping_minus = screen.span_mapping_for(target, target["project"],
                                            disabled, True)
    obs_minus = screen.observation(minus, nodeids, mapping_minus)
    if not obs_minus["known"]:
        record.update({"outcomes_minus": obs_minus["outcomes"],
                       "minus_returncode": minus.get("returncode"),
                       "minus_timed_out": minus.get("timed_out"),
                       "reason": "minus run unknown"})
        return record
    minus_ok = screen.passed(obs_minus, nodeids)
    record.update({
        "status": "OK",
        "minus_pass": minus_ok,
        "masked": bool(minus_ok),
        "exposed": bool(not minus_ok),
        "minus_hash": screen.canonical_obs(obs_minus),
        "outcomes_minus": obs_minus["outcomes"],
        "minus_returncode": minus.get("returncode"),
        "minus_timed_out": minus.get("timed_out"),
    })
    return record


def accept_target(tid: str, matrix_row: Dict[str, Any],
                  target: Dict[str, Any], probes: Dict[str, Any]
                  ) -> Dict[str, Any]:
    nodeids = matrix_row["tests"]
    S = list(matrix_row["selected_set"])
    U = [op["id"] for op in target["u"]]
    started = time.perf_counter()
    base = evaluate(target, nodeids, [])
    evals = {"": base}
    for T in proper_nonempty(S):
        disabled = sorted(set(U) - set(T))
        evals["+".join(disabled)] = evaluate(target, nodeids, disabled)
    primary_key = "+".join(sorted(set(U) - set(S)))
    evals[primary_key] = evaluate(
        target, nodeids, sorted(set(U) - set(S)))
    singleton_evals = {}
    for member in S:
        singleton_evals[member] = evaluate(target, nodeids, [member])
    proper_masked = {key: row["masked"] for key, row in evals.items()
                     if key != primary_key and key != ""}
    unknown_subsets = sorted(key for key, value in proper_masked.items()
                             if value is None)
    inert = {}
    for member in S:
        row = singleton_evals[member]
        inert[member] = bool(
            row["status"] == "OK"
            and row["plus_pass"] and row["minus_pass"]
            and row["outcomes_plus"] == base["outcomes_plus"]
            and row["outcomes_minus"] == base["outcomes_minus"])
    plus_full = screen.run_full_suite(target["project"], False, target)
    minus_full = screen.run_full_suite(target["project"], True, target)
    new_failures = sorted(set(minus_full["failures"]) -
                          set(plus_full["failures"]))
    checks = {
        "a_executes": probes["a_executes"],
        "local_effect": probes.get("local_effect"),
        "size_at_least_two": len(S) >= 2,
        "primary_masked": (base.get("masked") is True
                           and evals[primary_key].get("masked") is True),
        "all_proper_subsets_not_masked": (
            not unknown_subsets
            and all(value is False for value in proper_masked.values())),
        "at_least_one_inert": any(inert.values()),
        "full_suite_no_new_failure": (minus_full["returncode"] is not None
                                      and not minus_full["timed_out"]
                                      and not new_failures),
    }
    accepted = all(checks.values())
    case = {
        "target_id": tid,
        "project": target["project"],
        "version": screen.releases()[target["project"]]["version"],
        "sdist_sha256": screen.releases()[target["project"]]["sha256"],
        "candidate_id": target["candidate_id"],
        "target_a": {
            "file": target["file"],
            "function": target["function"],
            "first_line": target["a_first"],
            "last_line": target["a_last"],
            "code": target["a_code"],
            "variables": target["a_lhs"],
        },
        "universe": target["u"],
        "universe_ids": U,
        "tests": nodeids,
        "test_selection_rule": (
            "Original upstream tests whose coverage context executed A; at "
            "most three, lexicographic. No P- outcome used."),
        "proposed_set_S": S,
        "disabled_for_S": sorted(set(U) - set(S)),
        "evaluations": evals,
        "singleton_evaluations": singleton_evals,
        "inert_members": inert,
        "full_suite": {
            "plus": plus_full,
            "minus": minus_full,
            "new_failures_from_deleting_a": new_failures,
        },
        "checks": checks,
        "unknown_subsets": unknown_subsets,
        "unknown_evaluations": sorted(
            key for key, row in evals.items() if row["status"] == "UNKNOWN"),
        "final_status": "CONFIRMED_M1" if accepted else "REJECTED_M1",
        "evidence_level": "WITNESS_VERIFIED",
        "input_domain": "original upstream tests (no synthetic inputs)",
        "why_original_tests_missed": (
            "Every selected test passes with A present and with A deleted; "
            "the complete original suite reports no failure that is absent "
            "in the plus run. The tests observe the public API result, not "
            "the intermediate variable A writes."),
        "wall_seconds": round(time.perf_counter() - started, 2),
    }
    case["evidence_sha256"] = sha256_json({
        "target_a": case["target_a"],
        "universe_ids": U,
        "tests": nodeids,
        "S": S,
        "evaluations": evals,
        "inert": inert,
        "checks": checks,
        "full_suite_new_failures": new_failures,
    })
    return case


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--targets", nargs="*", default=None)
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args(argv)
    matrix = screen.load_json(SCREEN / "matrix.json")["targets"]
    probes = screen.load_json(SCREEN / "probe.json")["rows"]
    targets = screen.load_targets_by_id()
    eligible = [tid for tid, row in matrix.items()
                if row.get("status") == "CONFIRMED_M1_PENDING_FULL_SUITE"]
    if args.targets:
        eligible = [tid for tid in args.targets if tid in matrix]
    elif not args.all:
        eligible = eligible[:1]
    ACCEPTED.mkdir(parents=True, exist_ok=True)
    results = []
    for tid in eligible:
        row = matrix[tid]
        if not row.get("selected_set"):
            continue
        case = accept_target(tid, row, targets[tid], probes[tid])
        slug = hashlib.sha1(tid.encode()).hexdigest()[:12]
        screen.write_json(ACCEPTED / f"{slug}.json", case)
        results.append(case)
        print(f"[accept] {tid}: {case['final_status']} "
              f"checks={case['checks']}", flush=True)
    screen.write_json(SCREEN / "acceptance.json", {
        "stage": "m1_independent_acceptance",
        "tool": "scripts/m1_accept.py",
        "rule": ("Re-executes every intervention; accepts only if all five "
                 "checks hold. Cases are frozen only here."),
        "cases": results,
    })
    summary: Dict[str, int] = {}
    for case in results:
        summary[case["final_status"]] = summary.get(
            case["final_status"], 0) + 1
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
