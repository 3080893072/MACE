"""Independent scorer for the MACE benchmark pilot.

    python scripts/pilot_evaluate.py --submission sub.json --out report.json
    python scripts/pilot_evaluate.py --self-test

The scorer never asks a model for a verdict and never compares a submission to
a hand-written reference guard.  Every label is recomputed by executing P+ and
P- on the frozen finite domain; attribution is recomputed by executing the
program under every enable/disable combination of the marked operations.
"""
from __future__ import annotations

import argparse
import ast
import importlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmark_pilot import engine, real_tasks  # noqa: E402

TASKS_PATH = ROOT / "benchmark_pilot" / "tasks.json"
ORACLE_PATH = ROOT / "benchmark_pilot" / "oracle.json"
ATTRIBUTION_PATH = ROOT / "benchmark_pilot" / "attribution.json"
SUB_DIR = ROOT / "benchmark_pilot" / "submissions"
LOG_DIR = ROOT / "benchmark_pilot" / "logs"


class ScorerError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Frozen-data loading and independent re-execution
# ---------------------------------------------------------------------------

def _load(path: Path) -> Any:
    with open(path, "r", encoding="utf-8") as handle:
        return json.load(handle)


def _resolve_generator(name: str):
    module_name, func_name = name.split(":", 1)
    module = importlib.import_module(module_name)
    return getattr(module, func_name)


def _case_key(args: Dict[str, Any]) -> str:
    return repr(sorted((k, engine.canonical(v)) for k, v in args.items()))


def _case_args_for_real(task_id: str, task: Dict[str, Any],
                        case_id: str, generated: Dict[str, Any]) -> Dict[str, Any]:
    if task_id == "real_formatdef":
        return {"func": generated[case_id]}
    if task_id == "real_setdiff":
        declared, provided = generated[case_id]
        return {"declared": list(declared), "provided": dict(provided)}
    raise ScorerError(f"unknown real task {task_id}")


def _arg_names(task: Dict[str, Any]) -> List[str]:
    args = task["input_domain"]["args"]
    return [a["name"] if isinstance(a, dict) else a for a in args]


def _test_verdict(plus: Dict[str, Any], minus: Dict[str, Any],
                  observable_equal: bool) -> str:
    if not plus.get("passed"):
        return "test_broken"
    if not minus.get("passed"):
        return "would_be_caught"
    if observable_equal:
        return "masked"
    return "assertion_gap"


def _same_test_result(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return (a.get("passed") == b.get("passed")
            and a.get("error") == b.get("error"))


def _global_test_verdict(verdicts: Iterable[str]) -> str:
    values = set(verdicts)
    if not values:
        return "not_covered"
    if "would_be_caught" in values:
        return "would_be_caught"
    if values == {"masked"}:
        return "masked"
    if "assertion_gap" in values and "masked" in values:
        return "mixed"
    if values == {"assertion_gap"}:
        return "assertion_gap"
    return "test_broken"


def build_ground(tasks_doc: Dict[str, Any], oracle_doc: Dict[str, Any],
                 attribution_doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    """Re-execute the frozen tasks and verify the stored oracle/attribution."""
    ground: Dict[str, Dict[str, Any]] = {}
    for task in tasks_doc["tasks"]:
        tid = task["task_id"]
        kind = task["kind"]
        oracle = oracle_doc["tasks"][tid]
        g: Dict[str, Any] = {"task": task, "task_id": tid, "kind": kind,
                             "arg_names": _arg_names(task)}

        if kind == "controlled":
            attr = attribution_doc["controlled"][tid]
            ops = list(attr["ops"])
            op_lines = dict(attr["op_lines"])
            source_plus = task["program"]["source"]
            source_minus = task["deletion"]["p_minus_source"]
            line = task["program"]["target_A"]["line"]
            cases = [(f"case_{i:04d}", dict(args))
                     for i, args in enumerate(task["input_domain"]["cases"])]
            plus = engine.run_source_cases(
                engine.compile_source(source_plus, capture_line=line),
                "program", cases)
            minus = engine.run_source_cases(
                engine.compile_source(source_minus, capture_line=line),
                "program", cases)
            matrix = engine.run_variant_pairs(
                source_plus, source_minus, "program", op_lines,
                engine.subsets(ops), cases)
            g.update({"ops": ops, "op_lines": op_lines, "matrix": matrix,
                      "source_plus": source_plus, "source_minus": source_minus,
                      "target_line": line})

            per_case_expected = {row["case_id"]: row
                                 for row in attr["per_case"]}
        else:
            generated = _resolve_generator(task["input_domain"]["generator"])()
            cases = []
            for case in task["input_domain"]["cases"]:
                cid = case["id"]
                cases.append((cid, _case_args_for_real(tid, task, cid, generated)))
            source_plus = task["program"]["source"]
            source_minus = task["deletion"]["p_minus_source"]
            plus = engine.run_source_cases(
                engine.compile_source(source_plus), "program", cases)
            minus = engine.run_source_cases(
                engine.compile_source(source_minus), "program", cases)
            g.update({"ops": [], "op_lines": {}, "matrix": {},
                      "source_plus": source_plus, "source_minus": source_minus,
                      "target_line": task["program"]["target_A"]["line"]})

        masked = {}
        local_effect = {}
        derived_abs: Dict[str, set] = {}
        derived_ind: Dict[str, List[str]] = {}
        derived_co: Dict[str, set] = {}
        oracle_cases = {row["case_id"]: row for row in oracle["cases"]}
        real_effects = (real_tasks.local_effect(tid)
                        if kind == "real" else {})
        for cid, args in cases:
            if cid not in oracle_cases:
                raise ScorerError(f"{tid}: case {cid} missing from oracle")
            expected = oracle_cases[cid]
            if plus[cid]["observation"] != expected["observation_plus"]:
                raise ScorerError(
                    f"{tid}/{cid}: oracle drift in P+ observation")
            if minus[cid]["observation"] != expected["observation_minus"]:
                raise ScorerError(
                    f"{tid}/{cid}: oracle drift in P- observation")
            equal = plus[cid]["observation"] == minus[cid]["observation"]
            if equal != expected["observable_equal"]:
                raise ScorerError(f"{tid}/{cid}: oracle drift in equality")
            masked[cid] = equal
            if kind == "controlled":
                local_effect[cid] = (plus[cid].get("snap") != minus[cid].get("snap"))
            else:
                local_effect[cid] = real_effects[cid]["local_effect"]
            if local_effect[cid] != expected.get("a_has_local_effect"):
                raise ScorerError(
                    f"{tid}/{cid}: oracle drift in local-effect flag")

        g.update({"cases": cases, "case_ids": [cid for cid, _ in cases],
                  "rows_plus": plus, "rows_minus": minus,
                  "masked": masked, "local_effect": local_effect,
                  "case_by_key": {_case_key(args): cid for cid, args in cases}
                  if kind == "controlled" else {}})

        # Verify attribution against re-execution, and collect gold claims.
        if kind == "controlled":
            gold_abs: Dict[FrozenSet[str], Dict[str, Any]] = {}
            gold_co: Dict[FrozenSet[str], Dict[str, Any]] = {}
            for cid, _ in cases:
                expected_row = per_case_expected[cid]
                base = matrix[frozenset()]
                case_masked = base["equal"][cid]
                if case_masked:
                    masking_sets = []
                    for m in engine.subsets(ops):
                        if matrix[frozenset(set(ops) - set(m))]["equal"][cid]:
                            masking_sets.append(frozenset(m))
                    absorbers = {tuple(x) for x in engine.setlist(
                        engine.minimal_sets(masking_sets))}
                    unmasking = [frozenset(u) for u in engine.subsets(ops)
                                 if u and not matrix[u]["equal"][cid]]
                    coexisting = {tuple(x) for x in engine.setlist(
                        [u for u in engine.minimal_sets(unmasking) if len(u) >= 2])}
                else:
                    absorbers, coexisting = set(), set()
                if absorbers != {tuple(x) for x in expected_row["absorber_sets"]}:
                    raise ScorerError(
                        f"{tid}/{cid}: attribution drift in absorber sets")
                if coexisting != {tuple(x) for x in expected_row["coexisting_unmasking_sets"]}:
                    raise ScorerError(
                        f"{tid}/{cid}: attribution drift in coexisting sets")
                derived_abs[cid] = absorbers
                derived_co[cid] = coexisting
                derived_ind[cid] = sorted(
                    op for op in ops if (op,) in absorbers)
            expected_global_abs = set().union(*derived_abs.values())
            expected_global_co = set().union(*derived_co.values())
            stored_global_abs = {
                tuple(c["ops"])
                for c in attribution_doc["controlled"][tid]["absorber_sets"]}
            stored_global_co = {
                tuple(c["ops"])
                for c in attribution_doc["controlled"][tid]["coexisting_sets"]}
            if stored_global_abs != expected_global_abs:
                raise ScorerError(
                    f"{tid}: attribution drift in global absorber sets")
            if stored_global_co != expected_global_co:
                raise ScorerError(
                    f"{tid}: attribution drift in global coexisting sets")
            for claim in attribution_doc["controlled"][tid]["absorber_sets"]:
                gold_abs[frozenset(claim["ops"])] = claim
            for claim in attribution_doc["controlled"][tid]["coexisting_sets"]:
                gold_co[frozenset(claim["ops"])] = claim
            g["gold_absorbers"] = gold_abs
            g["gold_coexisting"] = gold_co
            for ops, claim in gold_abs.items():
                ev = _evidence_for_claim(g, ops, claim["kind"], claim["witness"])
                if not ev.get("valid"):
                    raise ScorerError(
                        f"{tid}: stored absorber witness is invalid: {ev}")
            for ops, claim in gold_co.items():
                ev = _evidence_for_claim(g, ops, "coexisting", claim["witness"])
                if not ev.get("valid"):
                    raise ScorerError(
                        f"{tid}: stored coexisting witness is invalid: {ev}")

            # Re-run the existing tests on both versions instead of trusting
            # the stored results, then derive the per-test labels again.
            test_plus = engine.run_tests(
                source_plus, task["existing_tests"], "program")
            test_minus = engine.run_tests(
                source_minus, task["existing_tests"], "program")
            test_gold = {}
            attr_tests = attribution_doc["controlled"][tid]["existing_tests"]
            for name, row in oracle["existing_tests"].items():
                if not (_same_test_result(test_plus[name], row["plus"])
                        and _same_test_result(test_minus[name], row["minus"])):
                    raise ScorerError(
                        f"{tid}/{name}: oracle drift in test execution")
                cid = row["case_id"]
                observable_equal = masked[cid]
                if observable_equal != row["observable_equal"]:
                    raise ScorerError(
                        f"{tid}/{name}: oracle drift in test observable")
                attr_row = attr_tests[name]
                expected_abs = {tuple(x)
                                for x in attr_row["absorber_sets"]}
                if expected_abs != derived_abs[cid]:
                    raise ScorerError(
                        f"{tid}/{name}: attribution drift in test absorber sets")
                expected_ind = sorted(attr_row["individually_masking_ops"])
                if expected_ind != derived_ind[cid]:
                    raise ScorerError(
                        f"{tid}/{name}: attribution drift in test single ops")
                verdict = _test_verdict(test_plus[name], test_minus[name],
                                        observable_equal)
                test_gold[name] = {
                    "verdict": verdict,
                    "absorber_sets": [frozenset(x)
                                      for x in sorted(derived_abs[cid])],
                    "individually_masking_ops": list(derived_ind[cid]),
                    "input": row["input"],
                    "case_id": cid,
                    "observable_equal": observable_equal,
                    "plus": test_plus[name],
                    "minus": test_minus[name],
                }
            global_verdict = _global_test_verdict(
                v["verdict"] for v in test_gold.values())
            g["test_gold"] = test_gold
            g["global_test_gold"] = global_verdict
            if global_verdict != oracle.get("global_test_verdict", global_verdict):
                raise ScorerError(
                    f"{tid}: oracle drift in global test verdict")
        else:
            attr = attribution_doc["real"][tid]
            test_plus = engine.run_tests(
                source_plus, task["existing_tests"], "program")
            test_minus = engine.run_tests(
                source_minus, task["existing_tests"], "program")
            test_gold = {}
            for name, row in oracle["existing_tests"].items():
                if not (_same_test_result(test_plus[name], row["plus"])
                        and _same_test_result(test_minus[name], row["minus"])):
                    raise ScorerError(
                        f"{tid}/{name}: oracle drift in test execution")
                input_ids = (row["input"].get("case_ids")
                             or [row["input"].get("case_id")])
                input_ids = [cid for cid in input_ids if cid is not None]
                if any(cid not in masked for cid in input_ids):
                    raise ScorerError(
                        f"{tid}/{name}: test input outside the frozen domain")
                observable_equal = all(masked[cid] for cid in input_ids)
                if observable_equal != row["observable_equal"]:
                    raise ScorerError(
                        f"{tid}/{name}: oracle drift in test observable")
                verdict = _test_verdict(test_plus[name], test_minus[name],
                                        observable_equal)
                if verdict != row["gold_verdict"]:
                    raise ScorerError(
                        f"{tid}/{name}: oracle drift in gold verdict")
                test_gold[name] = {
                    "verdict": verdict,
                    "absorber_sets": [],
                    "individually_masking_ops": [],
                    "input": row["input"],
                    "observable_equal": observable_equal,
                    "plus": test_plus[name],
                    "minus": test_minus[name],
                }
            global_verdict = _global_test_verdict(
                v["verdict"] for v in test_gold.values())
            stored_global = oracle.get("global_test_verdict")
            if stored_global is not None and global_verdict != stored_global:
                raise ScorerError(
                    f"{tid}: oracle drift in global test verdict")
            g["test_gold"] = test_gold
            g["global_test_gold"] = global_verdict
            g["masking_status"] = attr["masking"]["status"]

        g["oracle"] = oracle
        ground[tid] = g
    return ground


# ---------------------------------------------------------------------------
# Submission helpers
# ---------------------------------------------------------------------------

def _as_dict(value: Any) -> Dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _submissions(doc: Dict[str, Any]) -> Dict[str, Dict[str, Any]]:
    if not isinstance(doc, dict):
        return {}
    rows = doc.get("submissions")
    if not isinstance(rows, list):
        rows = [doc]
    return {row["task_id"]: row for row in rows
            if isinstance(row, dict) and row.get("task_id")}


def resolve_case(g: Dict[str, Any], witness: Any) -> Optional[str]:
    if not isinstance(witness, dict):
        return None
    if "case_id" in witness:
        cid = witness["case_id"]
        return cid if cid in g["case_ids"] else None
    args = witness.get("args", witness)
    if g["kind"] != "controlled":
        return None
    return g["case_by_key"].get(_case_key(args))


def _claims(block: Any) -> List[Dict[str, Any]]:
    if not isinstance(block, list):
        return []
    out = []
    for item in block:
        if isinstance(item, dict):
            out.append(item)
    return out


def _claim_set(claim: Dict[str, Any]) -> FrozenSet[str]:
    return frozenset(claim.get("ops") or [])


def _kind_ok(claimed: Optional[str], expected: str) -> bool:
    if claimed == expected:
        return True
    if expected == "coexisting" and claimed == "fallback":
        return True
    return False


# ---------------------------------------------------------------------------
# Score A: guard / deletion risk
# ---------------------------------------------------------------------------

def score_A(g: Dict[str, Any], sub: Dict[str, Any]) -> Dict[str, Any]:
    guard = _as_dict(sub.get("guard"))
    expr = guard.get("expr")
    status = guard.get("status")
    result: Dict[str, Any] = {
        "present": bool(expr is not None or status in ("UNKNOWN", "INVALID")),
        "expr": expr,
        "status": status,
        "status_valid": False,
        "proof_machine_checked": False,
        "evidence_level": "BOUNDED",
        "domain_size": len(g["case_ids"]),
        "masked": sum(1 for v in g["masked"].values() if v),
        "exposed": sum(1 for v in g["masked"].values() if not v),
        "a_has_local_effect": sum(1 for v in g["local_effect"].values() if v),
        "guard_true": 0,
        "guard_false": 0,
        "false_accept": [],
        "false_reject": [],
        "sound": None,
        "complete": None,
        "exact": None,
    }
    if expr is None:
        result["valid"] = False
        result["reason"] = "no guard expression supplied"
        if status in ("UNKNOWN", "INVALID"):
            result["valid"] = True
            result["abstained"] = True
            result["status_valid"] = True
            result["reason"] = f"abstained with status {status}"
        return result

    values: Dict[str, bool] = {}
    try:
        for cid, args in g["cases"]:
            values[cid] = engine.eval_guard(expr, g["arg_names"], args)
    except engine.GuardError as exc:
        result["valid"] = False
        result["reason"] = f"guard rejected: {exc}"
        return result
    except Exception as exc:  # arithmetic errors such as 1 // 0
        result["valid"] = False
        result["reason"] = f"guard raised {type(exc).__name__}: {exc}"
        return result

    false_accept = [cid for cid, val in values.items()
                    if val and not g["masked"][cid]]
    false_reject = [cid for cid, val in values.items()
                    if not val and g["masked"][cid]]
    result.update({
        "valid": True,
        "guard_true": sum(1 for v in values.values() if v),
        "guard_false": sum(1 for v in values.values() if not v),
        "false_accept": false_accept,
        "false_reject": false_reject,
        "sound": not false_accept,
        "complete": not false_reject,
        "exact": not false_accept and not false_reject,
    })

    if status == "BOUNDED":
        result["status_valid"] = True
    elif status == "PROVEN":
        proof = guard.get("formal_proof")
        assumptions = guard.get("assumptions")
        result["status_valid"] = bool(proof and assumptions)
        result["proof_machine_checked"] = False
        result["proof_review_required"] = True
        result["status_note"] = (
            "PROVEN is accepted only as an external claim: the scorer cannot "
            "machine-check a proof, and a finite enumeration is never a proof "
            "over all inputs.")
    elif status in ("UNKNOWN", "INVALID"):
        result["status_valid"] = False
        result["status_note"] = (
            "Abstaining status supplied together with a guard expression; "
            "the expression is scored on the frozen domain but the claim "
            "status is inconsistent.")
    else:
        result["status_note"] = "missing or unsupported status"
    return result


# ---------------------------------------------------------------------------
# Score B: masking operations and composition
# ---------------------------------------------------------------------------

def _variant_masked(g: Dict[str, Any], disabled: FrozenSet[str], cid: str) -> bool:
    return g["matrix"][disabled]["equal"][cid]


def _evidence_for_claim(g: Dict[str, Any], ops: FrozenSet[str], kind: str,
                        witness: Any) -> Dict[str, Any]:
    cid = resolve_case(g, witness)
    if cid is None:
        return {"valid": False, "reason": "witness is not in the frozen domain"}
    all_ops = frozenset(g["ops"])
    if not ops <= all_ops:
        return {"valid": False, "reason": "claim names an unknown operation",
                "case_id": cid}
    if kind == "independent" and len(ops) != 1:
        return {"valid": False, "reason": "an independent claim must name one operation",
                "case_id": cid}
    if kind in ("cooperative", "coexisting") and len(ops) < 2:
        return {"valid": False,
                "reason": f"a {kind} claim must name at least two operations",
                "case_id": cid}
    only_claim = all_ops - ops
    if kind == "independent":
        combined = _variant_masked(g, only_claim, cid)
        none = _variant_masked(g, all_ops, cid)
        valid = combined and not none
        return {"valid": valid, "case_id": cid,
                "only_claim_masks": combined, "none_masks": none}
    if kind == "cooperative":
        singles = {}
        for op in sorted(ops):
            singles[op] = _variant_masked(g, all_ops - frozenset({op}), cid)
        combined = _variant_masked(g, only_claim, cid)
        valid = (combined and all(not v for v in singles.values()))
        return {"valid": valid, "case_id": cid,
                "only_claim_masks": combined, "single_op_masks": singles}
    if kind == "coexisting":
        combined = _variant_masked(g, only_claim, cid)
        singles = {}
        for op in sorted(ops):
            # Disable this op, keep the rest of the claimed sources enabled.
            disabled = frozenset(set(only_claim) | {op})
            singles[op] = _variant_masked(g, disabled, cid)
        # The definition is "every proper subset still masks", not just the
        # one-element removals: a smaller subset may already unmask A.
        proper = {
            "+".join(sorted(sub)): _variant_masked(g, sub, cid)
            for sub in engine.subsets(sorted(ops))
            if 0 < len(sub) < len(ops)
        }
        none = _variant_masked(g, all_ops, cid)
        valid = (combined and all(proper.values()) and not none)
        return {"valid": valid, "case_id": cid, "only_claim_masks": combined,
                "disable_one_still_masks": singles,
                "disable_proper_subset_still_masks": proper,
                "disable_all_masks": none}
    return {"valid": False, "reason": f"unknown claim kind {kind!r}"}


def score_B(g: Dict[str, Any], sub: Dict[str, Any]) -> Dict[str, Any]:
    if g["kind"] != "controlled":
        masking = _as_dict(sub.get("masking"))
        claims = _claims(masking.get("absorber_sets"))
        claims += _claims(masking.get("coexisting"))
        return {
            "applicable": False,
            "reason": ("No safely controllable operation exists in this real "
                       "task; causal attribution is recorded as unconfirmed."),
            "unconfirmed_claims": [sorted(_claim_set(c)) for c in claims],
            "gold_status": g.get("masking_status"),
        }

    masking = _as_dict(sub.get("masking"))
    abs_claims = _claims(masking.get("absorber_sets"))
    co_claims = _claims(masking.get("coexisting"))
    gold_abs = g["gold_absorbers"]
    gold_co = g["gold_coexisting"]

    def evaluate_claims(claims, gold, bucket):
        rows = []
        claimed_sets = set()
        for claim in claims:
            ops = _claim_set(claim)
            kind = claim.get("kind")
            claimed_sets.add(ops)
            expected = gold.get(ops)
            kind_expected = expected["kind"] if expected else None
            # Validate the claim with the *bucket's* semantics, not with the
            # kind the submission chose.  Otherwise a one-operation claim
            # dropped into the coexisting bucket would be checked as an
            # independent claim and could collect evidence credit.
            evidence_kind = ("coexisting" if bucket == "coexisting"
                             else ("independent" if len(ops) == 1
                                   else "cooperative"))
            evidence = _evidence_for_claim(
                g, ops, evidence_kind, claim.get("witness"))
            rows.append({
                "ops": sorted(ops),
                "claimed_kind": kind,
                "gold_kind": kind_expected,
                "in_gold": expected is not None,
                "kind_ok": (_kind_ok(kind, kind_expected)
                            if kind_expected else False),
                "evidence": evidence,
                "evidence_valid": evidence["valid"],
                "bucket": bucket,
            })
        return rows, claimed_sets

    abs_rows, abs_claimed = evaluate_claims(abs_claims, gold_abs, "absorber")
    co_rows, co_claimed = evaluate_claims(co_claims, gold_co, "coexisting")

    # An absorber claim with kind=coexisting and a coexisting claim with
    # kind=cooperative are both evidence-validated by the bucket's rule, but
    # the kind can still be wrong against gold; keep that distinction.

    def pr(claimed: set, gold: dict) -> Tuple[float, float, List[List[str]], List[List[str]]]:
        gold_sets = set(gold)
        tp = claimed & gold_sets
        precision = len(tp) / len(claimed) if claimed else (1.0 if not gold_sets else 0.0)
        recall = len(tp) / len(gold_sets) if gold_sets else 1.0
        fp = sorted((sorted(s) for s in claimed - gold_sets), key=lambda x: (len(x), x))
        fn = sorted((sorted(s) for s in gold_sets - claimed), key=lambda x: (len(x), x))
        return precision, recall, fp, fn

    abs_p, abs_r, abs_fp, abs_fn = pr(abs_claimed, gold_abs)
    co_p, co_r, co_fp, co_fn = pr(co_claimed, gold_co)

    matched_kind = [row for row in abs_rows + co_rows
                    if row["in_gold"]]
    kind_accuracy = (sum(1 for row in matched_kind if row["kind_ok"])
                     / len(matched_kind)) if matched_kind else 1.0
    evidence_rows = abs_rows + co_rows
    evidence_accuracy = (sum(1 for row in evidence_rows if row["evidence"]["valid"])
                         / len(evidence_rows)) if evidence_rows else 1.0

    return {
        "applicable": True,
        "gold_absorber_sets": engine.setlist(gold_abs),
        "gold_coexisting_sets": engine.setlist(gold_co),
        "absorber": {
            "claimed": engine.setlist(abs_claimed),
            "precision": abs_p,
            "recall": abs_r,
            "exact": abs_claimed == set(gold_abs),
            "false_positive": abs_fp,
            "missed": abs_fn,
            "claims": abs_rows,
        },
        "coexisting": {
            "claimed": engine.setlist(co_claimed),
            "precision": co_p,
            "recall": co_r,
            "exact": co_claimed == set(gold_co),
            "false_positive": co_fp,
            "missed": co_fn,
            "claims": co_rows,
        },
        "kind_accuracy": kind_accuracy,
        "evidence_accuracy": evidence_accuracy,
        "missed_coexisting_relations": co_fn,
        "false_positive_sets": abs_fp + co_fp,
        "all_sets_exact": abs_claimed == set(gold_abs) and co_claimed == set(gold_co),
    }


# ---------------------------------------------------------------------------
# Score C: regression counterexamples
# ---------------------------------------------------------------------------

def score_C(g: Dict[str, Any], sub: Dict[str, Any]) -> Dict[str, Any]:
    claimed = sub.get("witness_claim")
    submitted = sub.get("witnesses") or []
    rows = []
    valid = 0
    invalid = 0
    for witness in submitted:
        cid = resolve_case(g, witness)
        if cid is None:
            rows.append({"witness": witness, "valid": False,
                         "reason": "witness is not in the frozen domain"})
            invalid += 1
            continue
        equal = g["masked"][cid]
        row = {
            "witness": witness,
            "case_id": cid,
            "args": (dict(g["cases"][g["case_ids"].index(cid)][1])
                     if g["kind"] == "controlled" else {"case_id": cid}),
            "observation_plus": g["rows_plus"][cid]["observation"],
            "observation_minus": g["rows_minus"][cid]["observation"],
            "observable_equal": equal,
            "valid": not equal,
        }
        if equal:
            row["reason"] = "both versions have the same observable"
            invalid += 1
        else:
            valid += 1
        rows.append(row)

    exposed = sum(1 for v in g["masked"].values() if not v)
    if claimed == "none_exists" and exposed > 0:
        verdict = "wrong_none_exists_claim"
    elif claimed == "none_exists" and submitted:
        verdict = "claim_witness_conflict"
    elif claimed == "exists" and valid == 0:
        verdict = "claimed_exists_without_valid_witness"
    elif exposed == 0:
        if invalid:
            verdict = "invalid_witnesses_only"
        elif claimed == "none_exists":
            verdict = "correctly_none_exists"
        elif claimed is None:
            verdict = "none_exists_not_stated"
        else:
            verdict = "none_found_but_none_exists"
    elif valid:
        verdict = "valid_witnesses_found"
    elif invalid:
        verdict = "invalid_witnesses_only"
    else:
        verdict = "none_found_but_exists"
    correct = verdict in ("valid_witnesses_found", "correctly_none_exists")
    return {
        "gold_exposed_inputs": exposed,
        "gold_no_counterexample_exists": exposed == 0,
        "claimed": claimed,
        "submitted": len(submitted),
        "valid_count": valid,
        "invalid_count": invalid,
        "witnesses": rows,
        "verdict": verdict,
        "correct": correct,
    }


# ---------------------------------------------------------------------------
# Score D: why existing tests missed the deletion
# ---------------------------------------------------------------------------

def _named_ops_valid(g: Dict[str, Any], test_gold: Dict[str, Any],
                     named: Iterable[str]) -> Dict[str, Any]:
    ops = frozenset(named)
    minimal = set(test_gold["absorber_sets"])
    individually = set(test_gold["individually_masking_ops"])
    if not ops:
        return {"valid": False, "reason": "no masking operation named"}
    # No controllable operations (real task): only an empty set is meaningful.
    if not g["ops"]:
        return {"valid": False, "reason": "task has no controllable operations"}
    if ops in minimal:
        valid = True
        is_minimal = True
        reason = "named set is a minimal absorber set for this input"
    elif all(op in individually for op in ops) and any(ms <= ops for ms in minimal):
        valid = True
        is_minimal = False
        reason = ("every named operation masks alone on this input; the set "
                  "also contains a minimal absorber set, but is not minimal")
    else:
        is_minimal = False
        valid = False
        reason = ("named set is not a minimal absorber set and contains an "
                  "operation that does not mask alone")
    cid = test_gold["case_id"]
    all_ops = frozenset(g["ops"])
    only_named = all_ops - ops
    evidence = {
        "case_id": cid,
        "only_named_ops_enabled_masks": _variant_masked(g, only_named, cid),
        "single_op_masks": {
            op: _variant_masked(g, all_ops - frozenset({op}), cid)
            for op in sorted(ops)
        },
    }
    if valid and not evidence["only_named_ops_enabled_masks"]:
        valid = False
        reason = "execution with only the named operations enabled did not mask A"
    return {"valid": valid, "minimal": is_minimal, "reason": reason,
            "evidence": evidence}


def score_D(g: Dict[str, Any], sub: Dict[str, Any]) -> Dict[str, Any]:
    block = _as_dict(sub.get("test_gap"))
    submitted_global = block.get("verdict")
    submitted_tests = {row.get("name"): row
                       for row in _claims(block.get("tests"))}
    gold_tests = g["test_gold"]
    gold_global = g["global_test_gold"]

    rows = []
    matches = 0
    for name, gold in gold_tests.items():
        submitted = submitted_tests.get(name)
        if submitted is None:
            rows.append({"name": name, "gold_verdict": gold["verdict"],
                         "submitted_verdict": None, "agree": False,
                         "reason": "test not analysed"})
            continue
        verdict = submitted.get("verdict")
        agree = verdict == gold["verdict"]
        matches += 1 if agree else 0
        row: Dict[str, Any] = {
            "name": name,
            "gold_verdict": gold["verdict"],
            "submitted_verdict": verdict,
            "agree": agree,
            "observable_equal": gold["observable_equal"],
            "plus_test": gold["plus"],
            "minus_test": gold["minus"],
            "gold_absorber_sets": engine.setlist(gold["absorber_sets"]),
            "gold_individually_masking_ops": gold["individually_masking_ops"],
        }
        named = submitted.get("masking_ops") or []
        if gold["verdict"] == "masked" and g["ops"]:
            validity = _named_ops_valid(g, gold, named)
            row["named_ops"] = sorted(named)
            row["named_ops_valid"] = validity["valid"]
            row["named_ops_minimal"] = validity.get("minimal", False)
            row["named_ops_reason"] = validity["reason"]
            row["named_ops_evidence"] = validity.get("evidence")
        elif gold["verdict"] == "masked" and not g["ops"]:
            # Real task, masking cause unconfirmed: the honest answer names no
            # controllable operation.
            row["named_ops"] = sorted(named)
            row["named_ops_valid"] = not named
            row["named_ops_reason"] = (
                "no controllable operation exists; naming none is the only "
                "execution-supported answer")
        rows.append(row)

    per_test_accuracy = (matches / len(gold_tests)) if gold_tests else (
        1.0 if submitted_global == gold_global else 0.0)
    named_rows = [row for row in rows if "named_ops_valid" in row]
    minimal_rows = [row for row in named_rows if g["ops"]]
    return {
        "gold_global_verdict": gold_global,
        "submitted_global_verdict": submitted_global,
        "global_agree": submitted_global == gold_global,
        "tests": rows,
        "per_test_accuracy": per_test_accuracy,
        "named_ops_evidence": named_rows,
        "all_named_ops_valid": all(row["named_ops_valid"] for row in named_rows),
        "named_ops_minimality_accuracy": (
            sum(1 for row in minimal_rows if row.get("named_ops_minimal"))
            / len(minimal_rows) if minimal_rows else None),
    }


# ---------------------------------------------------------------------------
# Full evaluation
# ---------------------------------------------------------------------------

def evaluate(submission_doc: Dict[str, Any],
             ground: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    subs = _submissions(submission_doc)
    report: Dict[str, Any] = {
        "schema": "mace-benchmark-pilot-score/1",
        "scoring_method": (
            "Ground truth is recomputed by executing P+ and P- on the frozen "
            "domain, and attribution by executing every enable/disable "
            "combination.  No hand-written reference guard is used."),
        "tasks": {},
        "missing_tasks": [],
        "summary": {},
    }
    for tid, g in ground.items():
        sub = subs.get(tid)
        missing = sub is None
        if missing:
            report["missing_tasks"].append(tid)
            sub = {}
        a = score_A(g, sub)
        b = score_B(g, sub)
        c = score_C(g, sub)
        d = score_D(g, sub)
        if missing:
            a.update({"valid": False, "reason": "no submission for this task",
                      "sound": None, "complete": None, "exact": None,
                      "status_valid": False})
            c.update({"correct": False, "verdict": "no_submission"})
            d.update({"global_agree": False, "per_test_accuracy": 0.0})
            if b.get("applicable"):
                b.update({"all_sets_exact": False, "evidence_accuracy": 0.0})
        report["tasks"][tid] = {
            "kind": g["kind"],
            "missing": missing,
            "score_A_guard": a,
            "score_B_masking": b,
            "score_C_witness": c,
            "score_D_test_gap": d,
        }

    controlled = [t for t, g in ground.items() if g["kind"] == "controlled"]
    real = [t for t, g in ground.items() if g["kind"] == "real"]

    def agg(ids: List[str]) -> Dict[str, Any]:
        rows = [report["tasks"][t] for t in ids]
        return {
            "tasks": len(ids),
            "guard_exact": sum(1 for r in rows
                               if r["score_A_guard"].get("exact") is True),
            "guard_sound": sum(1 for r in rows
                               if r["score_A_guard"].get("sound") is True),
            "guard_complete": sum(1 for r in rows
                                  if r["score_A_guard"].get("complete") is True),
            "masking_sets_exact": sum(1 for r in rows
                                      if r["score_B_masking"].get("all_sets_exact")),
            "witness_correct": sum(1 for r in rows
                                   if r["score_C_witness"].get("correct")),
            "test_gap_global_agree": sum(1 for r in rows
                                         if r["score_D_test_gap"].get("global_agree")),
            "test_gap_per_test_accuracy_mean": (
                sum(r["score_D_test_gap"]["per_test_accuracy"] for r in rows) / len(rows)
                if rows else 0.0),
        }

    report["summary"] = {
        "controlled": agg(controlled),
        "real": agg(real),
        "note": ("Controlled and real tasks are reported separately; the "
                 "aggregate must not be presented as real-project "
                 "generalization."),
    }
    return report


def format_report(report: Dict[str, Any]) -> str:
    lines = []
    for tid, row in report["tasks"].items():
        a, b, c, d = (row["score_A_guard"], row["score_B_masking"],
                      row["score_C_witness"], row["score_D_test_gap"])
        lines.append(f"== {tid} ({row['kind']})")
        if a.get("valid"):
            lines.append(
                f"  A guard={a.get('expr')!r} status={a.get('status')} "
                f"sound={a.get('sound')} complete={a.get('complete')} "
                f"exact={a.get('exact')} false_accept={len(a.get('false_accept', []))} "
                f"false_reject={len(a.get('false_reject', []))}")
        else:
            lines.append(f"  A INVALID: {a.get('reason')}")
        if not b.get("applicable"):
            lines.append(f"  B not applicable: {b.get('reason')}")
        else:
            lines.append(
                f"  B absorbers claimed={b['absorber']['claimed']} "
                f"gold={b['gold_absorber_sets']} P={b['absorber']['precision']:.2f} "
                f"R={b['absorber']['recall']:.2f} exact={b['absorber']['exact']}")
            lines.append(
                f"  B coexisting claimed={b['coexisting']['claimed']} "
                f"gold={b['gold_coexisting_sets']} exact={b['coexisting']['exact']} "
                f"kind_acc={b['kind_accuracy']:.2f} "
                f"evidence_acc={b['evidence_accuracy']:.2f}")
        lines.append(f"  C verdict={c['verdict']} valid={c['valid_count']} "
                     f"invalid={c['invalid_count']} "
                     f"exposed={c['gold_exposed_inputs']}")
        lines.append(f"  D global={d['submitted_global_verdict']} "
                     f"gold={d['gold_global_verdict']} agree={d['global_agree']} "
                     f"per_test={d['per_test_accuracy']:.2f} "
                     f"named_ops_all_valid={d['all_named_ops_valid']}")
    if report["missing_tasks"]:
        lines.append(f"missing submissions: {report['missing_tasks']}")
    lines.append("summary: " + json.dumps(report["summary"], ensure_ascii=False))
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# Self-test: perfect and sabotaged submissions
# ---------------------------------------------------------------------------

def _lookup_guard(g: Dict[str, Any]) -> str:
    masked_cases = [args for cid, args in g["cases"] if g["masked"][cid]]
    if not masked_cases:
        return "False"
    if len(masked_cases) == len(g["cases"]):
        return "True"
    terms = []
    for args in masked_cases:
        conj = " and ".join(
            f"{name} == {args[name]!r}" for name in g["arg_names"])
        terms.append(f"({conj})")
    return " or ".join(terms)


def perfect_submission(ground: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    rows = []
    for tid, g in ground.items():
        tests = []
        for name, gold in g["test_gold"].items():
            named: List[str] = []
            if gold["verdict"] == "masked" and gold["absorber_sets"]:
                named = sorted(next(iter(sorted(
                    gold["absorber_sets"], key=lambda s: (len(s), sorted(s))))))
            tests.append({"name": name, "verdict": gold["verdict"],
                          "masking_ops": named})
        witnesses = [{"case_id": cid} for cid in g["case_ids"]
                     if not g["masked"][cid]][:2]
        witness_claim = "exists" if witnesses else "none_exists"
        abs_claims = []
        co_claims = []
        if g["kind"] == "controlled":
            for ops, claim in g["gold_absorbers"].items():
                abs_claims.append({"ops": sorted(ops), "kind": claim["kind"],
                                   "witness": claim["witness"]})
            for ops, claim in g["gold_coexisting"].items():
                co_claims.append({"ops": sorted(ops), "kind": "coexisting",
                                  "witness": claim["witness"]})
        rows.append({
            "task_id": tid,
            "guard": {"expr": _lookup_guard(g), "status": "BOUNDED"},
            "masking": {"absorber_sets": abs_claims,
                        "coexisting": co_claims},
            "witnesses": witnesses,
            "witness_claim": witness_claim,
            "test_gap": {"verdict": g["global_test_gold"], "tests": tests},
        })
    return {"submissions": rows}


def sabotaged_submission(perfect: Dict[str, Any]) -> Dict[str, Any]:
    doc = json.loads(json.dumps(perfect))
    by_id = {row["task_id"]: row for row in doc["submissions"]}
    by_id["ctrl_01"]["guard"]["expr"] = "mode == 1"
    by_id["ctrl_02"]["masking"]["absorber_sets"] = [{
        "ops": ["C"], "kind": "independent",
        "witness": {"case_id": "case_0000"},
    }]
    by_id["ctrl_03"]["masking"]["coexisting"] = []
    by_id["real_formatdef"]["guard"]["expr"] = "False"
    by_id["real_setdiff"]["witnesses"] = [{"case_id": "ab_ab"}]
    by_id["real_setdiff"]["witness_claim"] = "exists"
    by_id["ctrl_01"]["test_gap"]["tests"][0]["verdict"] = "assertion_gap"
    return doc


def self_test() -> int:
    tasks_doc = _load(TASKS_PATH)
    oracle_doc = _load(ORACLE_PATH)
    attribution_doc = _load(ATTRIBUTION_PATH)
    ground = build_ground(tasks_doc, oracle_doc, attribution_doc)

    perfect = perfect_submission(ground)
    sabotaged = sabotaged_submission(perfect)
    SUB_DIR.mkdir(parents=True, exist_ok=True)
    engine.write_json(str(SUB_DIR / "perfect.json"), perfect)
    engine.write_json(str(SUB_DIR / "sabotaged.json"), sabotaged)

    perfect_report = evaluate(perfect, ground)
    sab_report = evaluate(sabotaged, ground)

    checks: List[Dict[str, Any]] = []

    def check(name: str, ok: bool, detail: Any = None) -> None:
        checks.append({"check": name, "pass": bool(ok), "detail": detail})

    for tid, row in perfect_report["tasks"].items():
        check(f"perfect/{tid}/guard_exact",
              row["score_A_guard"].get("exact") is True,
              row["score_A_guard"])
        check(f"perfect/{tid}/witness_correct",
              row["score_C_witness"].get("correct") is True,
              row["score_C_witness"]["verdict"])
        check(f"perfect/{tid}/test_gap_global",
              row["score_D_test_gap"].get("global_agree") is True,
              (row["score_D_test_gap"]["submitted_global_verdict"],
               row["score_D_test_gap"]["gold_global_verdict"]))

    for tid in ("ctrl_01", "ctrl_02", "ctrl_03"):
        check(f"perfect/{tid}/masking_exact",
              perfect_report["tasks"][tid]["score_B_masking"].get("all_sets_exact") is True,
              perfect_report["tasks"][tid]["score_B_masking"])
        check(f"perfect/{tid}/per_test",
              perfect_report["tasks"][tid]["score_D_test_gap"]["per_test_accuracy"] == 1.0,
              perfect_report["tasks"][tid]["score_D_test_gap"]["per_test_accuracy"])

    check("sabotage/ctrl_01/guard_not_exact",
          sab_report["tasks"]["ctrl_01"]["score_A_guard"].get("exact") is not True,
          sab_report["tasks"]["ctrl_01"]["score_A_guard"])
    check("sabotage/ctrl_02/cooperative_missed",
          sab_report["tasks"]["ctrl_02"]["score_B_masking"]["absorber"]["recall"] < 1.0,
          sab_report["tasks"]["ctrl_02"]["score_B_masking"]["absorber"])
    check("sabotage/ctrl_03/coexisting_missed",
          bool(sab_report["tasks"]["ctrl_03"]["score_B_masking"]
               ["missed_coexisting_relations"]),
          sab_report["tasks"]["ctrl_03"]["score_B_masking"]["missed_coexisting_relations"])
    check("sabotage/real_formatdef/guard_incomplete",
          sab_report["tasks"]["real_formatdef"]["score_A_guard"].get("complete") is False,
          sab_report["tasks"]["real_formatdef"]["score_A_guard"])
    check("sabotage/real_setdiff/invalid_witness",
          sab_report["tasks"]["real_setdiff"]["score_C_witness"]["invalid_count"] >= 1,
          sab_report["tasks"]["real_setdiff"]["score_C_witness"])
    check("sabotage/ctrl_01/test_verdict_detected",
          sab_report["tasks"]["ctrl_01"]["score_D_test_gap"]["per_test_accuracy"] < 1.0,
          sab_report["tasks"]["ctrl_01"]["score_D_test_gap"]["per_test_accuracy"])

    out = {
        "schema": "mace-benchmark-pilot-selftest/1",
        "checks": checks,
        "perfect_report": perfect_report,
        "sabotaged_report": sab_report,
        "all_checks_pass": all(c["pass"] for c in checks),
    }
    engine.write_json(str(SUB_DIR / "self_test.json"), out)
    log = LOG_DIR / "self_test.log"
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    with open(log, "w", encoding="utf-8") as handle:
        handle.write(format_report(perfect_report) + "\n\n")
        handle.write(format_report(sab_report) + "\n\n")
        for c in checks:
            handle.write(f"{'PASS' if c['pass'] else 'FAIL'} {c['check']}\n")
    print(format_report(perfect_report))
    print()
    for c in checks:
        print(f"{'PASS' if c['pass'] else 'FAIL'} {c['check']}")
    print(f"\nwrote {SUB_DIR / 'perfect.json'}, "
          f"{SUB_DIR / 'sabotaged.json'}, {SUB_DIR / 'self_test.json'}")
    return 0 if out["all_checks_pass"] else 1


def main(argv: Optional[Sequence[str]] = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--submission")
    parser.add_argument("--out")
    parser.add_argument("--log")
    parser.add_argument("--self-test", action="store_true")
    args = parser.parse_args(argv)

    if args.self_test:
        return self_test()
    if not args.submission:
        parser.error("--submission is required unless --self-test is used")

    tasks_doc = _load(TASKS_PATH)
    oracle_doc = _load(ORACLE_PATH)
    attribution_doc = _load(ATTRIBUTION_PATH)
    ground = build_ground(tasks_doc, oracle_doc, attribution_doc)
    submission = _load(Path(args.submission))
    report = evaluate(submission, ground)

    if args.out:
        engine.write_json(args.out, report)
    if args.log:
        log_path = Path(args.log)
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with open(log_path, "w", encoding="utf-8") as handle:
            handle.write(format_report(report) + "\n")
            for tid, g in ground.items():
                for cid, args in g["cases"]:
                    handle.write(
                        f"execute {tid} {cid} args={args!r} "
                        f"plus={g['rows_plus'][cid]['observation']!r} "
                        f"minus={g['rows_minus'][cid]['observation']!r} "
                        f"equal={g['masked'][cid]}\n")
    print(format_report(report))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
