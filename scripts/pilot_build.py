"""Build the frozen pilot tasks, execution oracle, and intervention attribution.

Run from the repository root:

    python scripts/pilot_build.py

Every label written to ``oracle.json`` and ``attribution.json`` comes from
executing P+ and P- (and, for controlled tasks, every enable/disable
combination of the marked operations) on the frozen finite domain.  No
hand-written guard is stored as truth: the private guards in
``benchmark_pilot/private/controlled.py`` are used only as a design self-check
and the result of that check is logged.
"""
from __future__ import annotations

import ast
import inspect
import os
import sys
from pathlib import Path
from typing import Any, Dict, FrozenSet, List

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from benchmark_pilot import engine, generators, real_tasks, specs  # noqa: E402
from benchmark_pilot.private.controlled import CONTROLLED as PRIVATE  # noqa: E402

OUT = ROOT / "benchmark_pilot"
LOG = OUT / "logs" / "build.log"


def log(message: str) -> None:
    print(message)
    with open(LOG, "a", encoding="utf-8") as handle:
        handle.write(message + "\n")


def _signature_of(source: str, entry: str = "program") -> List[str]:
    tree = ast.parse(source)
    for node in tree.body:
        if isinstance(node, ast.FunctionDef) and node.name == entry:
            return [a.arg for a in node.args.args]
    raise engine.EngineError(f"entry {entry!r} not found")


def _program_call_args(source: str) -> List[tuple]:
    """Literal argument tuples of direct ``program(...)`` calls in a test.

    The controlled tests are single-call assertions with literal arguments, so
    this verifies that their declared ``input`` metadata is the input they
    actually exercise.  Non-literal or keyword calls are left unverified.
    """
    out = []
    for node in ast.walk(ast.parse(source)):
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Name)
                and node.func.id == "program"
                and not node.keywords):
            try:
                out.append(tuple(ast.literal_eval(arg) for arg in node.args))
            except (ValueError, SyntaxError):
                continue
    return out


def _target_text(source: str, line: int) -> str:
    raw = source.splitlines()[line - 1]
    return raw.split("# TARGET_A", 1)[0].strip()


def _args_description(task_id: str, case_id: str, args: Dict[str, Any]) -> Dict[str, Any]:
    if task_id == "real_formatdef":
        func = args["func"]
        return {"function": case_id,
                "signature": str(inspect.signature(func)),
                "name": func.__name__}
    if task_id == "real_setdiff":
        return {"declared": args["declared"], "provided": args["provided"]}
    return dict(args)


def _row_equal(row_plus: Dict[str, Any], row_minus: Dict[str, Any]) -> bool:
    return row_plus["observation"] == row_minus["observation"]


def _local_effect_snapshot(row_plus: Dict[str, Any], row_minus: Dict[str, Any]) -> bool | None:
    if row_plus.get("snap") is None or row_minus.get("snap") is None:
        return None
    return row_plus["snap"] != row_minus["snap"]


def _case_index(cases: List[tuple[str, Dict[str, Any]]]) -> Dict[str, str]:
    index = {}
    for cid, args in cases:
        key = engine.json_dumps_key(args) if hasattr(engine, "json_dumps_key") else repr(
            sorted((k, engine.canonical(v)) for k, v in args.items()))
        index[key] = cid
    return index


def _key(args: Dict[str, Any]) -> str:
    return repr(sorted((k, engine.canonical(v)) for k, v in args.items()))


CONTROLLED_ARG_DECL = {
    "ctrl_01": [
        {"name": "mode", "sort": "int", "legal_values": [0, 1]},
        {"name": "x", "sort": "int", "legal_values": [0, 1, 2]},
    ],
    "ctrl_02": [
        {"name": "x", "sort": "int", "legal_values": [1, 2, 3, 4, 5, 6]},
        {"name": "c", "sort": "int", "legal_values": [0, 1]},
        {"name": "d", "sort": "int", "legal_values": [0, 1]},
    ],
    "ctrl_03": [
        {"name": "p", "sort": "int", "legal_values": [0, 1]},
        {"name": "q", "sort": "int", "legal_values": [0, 1]},
        {"name": "x", "sort": "int", "legal_values": [3, 4, 5, 6]},
        {"name": "c", "sort": "int", "legal_values": [0, 1]},
        {"name": "d", "sort": "int", "legal_values": [0, 1]},
    ],
}

CONTROLLED_DOMAIN_NOTE = {
    "ctrl_01": "Full Cartesian product of the two argument domains.",
    "ctrl_02": "Full Cartesian product of the three argument domains.",
    "ctrl_03": ("The legal domain is the union of five control regimes, not "
                "the full Cartesian product; the 20 frozen cases are listed "
                "explicitly.  The restriction is part of the task definition "
                "and was fixed before any submission existed."),
}


def build_controlled(task_id: str) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    private = PRIVATE[task_id]
    public_spec = specs.CONTROLLED[task_id]
    source_plus = engine.strip_op_comments(private["source"])
    line = engine.target_line(source_plus)
    source_minus = engine.replace_target_with_pass(source_plus)
    op_lines = dict(private["ops"])
    ops = sorted(op_lines)

    cases = [(f"case_{i:04d}", dict(args))
             for i, args in enumerate(public_spec["domain_cases"])]
    case_lookup = {_key(args): cid for cid, args in cases}

    compiled_plus = engine.compile_source(source_plus, capture_line=line)
    compiled_minus = engine.compile_source(source_minus, capture_line=line)
    plus_rows = engine.run_source_cases(compiled_plus, "program", cases)
    minus_rows = engine.run_source_cases(compiled_minus, "program", cases)

    test_plus = engine.run_tests(source_plus, public_spec["tests"], capture_line=line)
    test_minus = engine.run_tests(source_minus, public_spec["tests"], capture_line=line)

    all_disabled = engine.subsets(ops)
    matrix = engine.run_variant_pairs(
        source_plus, source_minus, "program", op_lines, all_disabled, cases)

    per_case: List[Dict[str, Any]] = []
    absorber_global: Dict[FrozenSet[str], List[str]] = {}
    coexisting_global: Dict[FrozenSet[str], List[str]] = {}
    test_attribution: Dict[str, Any] = {}

    for cid, args in cases:
        base = matrix[frozenset()]
        masked = base["equal"][cid]
        case_absorbers: List[FrozenSet[str]] = []
        case_coexisting: List[FrozenSet[str]] = []
        individually_masking: List[str] = []
        if masked:
            # "Only M enabled" == disable the complement.  Minimal M that
            # masks is the absorber set for this input.
            masking_sets = []
            for m in engine.subsets(ops):
                disabled = frozenset(set(ops) - set(m))
                if matrix[disabled]["equal"][cid]:
                    masking_sets.append(frozenset(m))
            case_absorbers = engine.minimal_sets(masking_sets)
            individually_masking = sorted(
                op for op in ops if frozenset({op}) in case_absorbers)
            # "Disable U" == apply the intervention to the original program.
            unmasking = []
            for u in engine.subsets(ops):
                if u and not matrix[u]["equal"][cid]:
                    unmasking.append(frozenset(u))
            minimal_unmasking = engine.minimal_sets(unmasking)
            case_coexisting = [u for u in minimal_unmasking if len(u) >= 2]
            for s in case_absorbers:
                absorber_global.setdefault(s, []).append(cid)
            for u in case_coexisting:
                coexisting_global.setdefault(u, []).append(cid)

        per_case.append({
            "case_id": cid,
            "args": args,
            "masked": masked,
            "absorber_sets": engine.setlist(case_absorbers),
            "coexisting_unmasking_sets": engine.setlist(case_coexisting),
            "individually_masking_ops": individually_masking,
        })

    # Per-test attribution: which minimal absorber sets hold on the test input,
    # and whether the test's assertion can distinguish the two versions.
    test_arg_names = _signature_of(source_plus)
    for test in public_spec["tests"]:
        args = test["input"]
        cid = case_lookup.get(_key(args))
        if cid is None:
            raise engine.EngineError(
                f"{task_id}: test input {args!r} is outside the frozen domain")
        # The metadata input must be the input the test source actually calls.
        calls = _program_call_args(test["source"])
        expected_call = tuple(args[name] for name in test_arg_names)
        if calls and any(call != expected_call for call in calls):
            raise engine.EngineError(
                f"{task_id}/{test['name']}: test calls {calls!r} but its "
                f"declared input is {args!r}")
        row = next(r for r in per_case if r["case_id"] == cid)
        test_attribution[test["name"]] = {
            "input": args,
            "case_id": cid,
            "masked": row["masked"],
            "absorber_sets": row["absorber_sets"],
            "individually_masking_ops": row["individually_masking_ops"],
            "plus_test": test_plus[test["name"]],
            "minus_test": test_minus[test["name"]],
            "observable_equal": _row_equal(plus_rows[cid], minus_rows[cid]),
        }

    # Global claims with witnesses (first case where the minimal set appears).
    absorber_claims = []
    for s, cids in sorted(absorber_global.items(), key=lambda kv: (len(kv[0]), sorted(kv[0]))):
        if not s:
            continue
        absorber_claims.append({
            "ops": sorted(s),
            "kind": "independent" if len(s) == 1 else "cooperative",
            "witness": {"case_id": cids[0],
                        "args": dict(cases[int(cids[0].split("_")[1])][1])},
            "case_ids": cids,
        })
    coexisting_claims = []
    for s, cids in sorted(coexisting_global.items(), key=lambda kv: (len(kv[0]), sorted(kv[0]))):
        coexisting_claims.append({
            "ops": sorted(s),
            "kind": "coexisting",
            "witness": {"case_id": cids[0],
                        "args": dict(cases[int(cids[0].split("_")[1])][1])},
            "case_ids": cids,
        })

    # Self-check against the private design guard.  This is NOT the oracle;
    # the labels above are.  A mismatch means the task design is wrong.
    arg_names = _signature_of(source_plus)
    guard = private["guard"]
    mismatches = []
    for cid, args in cases:
        expected = _row_equal(plus_rows[cid], minus_rows[cid])
        got = engine.eval_guard(guard, arg_names, args)
        if got != expected:
            mismatches.append({"case_id": cid, "guard": got, "executed": expected})
    if mismatches:
        raise engine.EngineError(
            f"{task_id}: private design guard disagrees with execution: {mismatches}")

    # Required non-degeneracy: at least one masked input where A changes the
    # post-A local state.
    masked_with_local = 0
    for cid, _ in cases:
        local = _local_effect_snapshot(plus_rows[cid], minus_rows[cid])
        if _row_equal(plus_rows[cid], minus_rows[cid]) and local:
            masked_with_local += 1
    if masked_with_local == 0:
        raise engine.EngineError(
            f"{task_id}: no masked input with a real local effect (degenerate)")

    task_public = {
        "task_id": task_id,
        "kind": "controlled",
        "entry": "program",
        "program": {
            "language": "python",
            "source": source_plus,
            "target_A": {
                "line": line,
                "text": _target_text(source_plus, line),
                "kind": "assignment",
            },
        },
        "deletion": {
            "kind": "replace_statement_with_pass",
            "description": ("Delete the target assignment: replace the single "
                            "statement on the marked line with `pass`."),
            "p_minus_source": source_minus,
        },
        "existing_tests": [
            {
                "name": test["name"],
                "source": test["source"],
                "input": test["input"],
                "results": {
                    "plus": test_plus[test["name"]],
                    "minus": test_minus[test["name"]],
                },
            }
            for test in public_spec["tests"]
        ],
        "input_domain": {
            "kind": "explicit",
            "args": CONTROLLED_ARG_DECL[task_id],
            "cases": [dict(args) for _, args in cases],
            "generator": "benchmark_pilot.generators:controlled_cases",
            "generator_args": {"task_id": task_id},
            "note": CONTROLLED_DOMAIN_NOTE[task_id],
        },
        "observable_behavior": public_spec["observable"],
        "why_suspected_redundant": public_spec["why_suspected_redundant"],
        "provenance": public_spec["provenance"],
    }

    oracle = {
        "kind": "controlled",
        "domain_size": len(cases),
        "masked_count": sum(1 for cid, _ in cases
                            if _row_equal(plus_rows[cid], minus_rows[cid])),
        "exposed_count": sum(1 for cid, _ in cases
                             if not _row_equal(plus_rows[cid], minus_rows[cid])),
        "masked_with_local_effect_count": masked_with_local,
        "cases": [
            {
                "case_id": cid,
                "args": args,
                "observation_plus": plus_rows[cid]["observation"],
                "observation_minus": minus_rows[cid]["observation"],
                "observable_equal": _row_equal(plus_rows[cid], minus_rows[cid]),
                "a_has_local_effect": _local_effect_snapshot(
                    plus_rows[cid], minus_rows[cid]),
            }
            for cid, args in cases
        ],
        "existing_tests": {
            name: {
                "input": row["input"],
                "case_id": row["case_id"],
                "observable_equal": row["observable_equal"],
                "plus": row["plus_test"],
                "minus": row["minus_test"],
            }
            for name, row in test_attribution.items()
        },
    }

    attribution = {
        "ops": ops,
        "op_lines": op_lines,
        "per_case": per_case,
        "absorber_sets": absorber_claims,
        "coexisting_sets": coexisting_claims,
        "existing_tests": test_attribution,
        "design_guard_self_check": {
            "guard": guard,
            "agrees_with_execution_on_all_cases": True,
            "note": ("Private design check only; the scorer never compares a "
                     "submission to this guard."),
        },
    }
    return task_public, oracle, attribution


def build_real(task_id: str) -> tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    public_spec = specs.REAL[task_id]
    source_plus = public_spec["source_plus"]
    source_minus = public_spec["source_minus"]
    line = engine.target_line(source_plus)
    cases = real_tasks.cases_with_args(task_id)
    plus_rows = engine.run_source_cases(
        engine.compile_source(source_plus), "program", cases)
    minus_rows = engine.run_source_cases(
        engine.compile_source(source_minus), "program", cases)
    test_plus = engine.run_tests(source_plus, public_spec["tests"])
    test_minus = engine.run_tests(source_minus, public_spec["tests"])
    local_effects = real_tasks.local_effect(task_id)

    case_rows = []
    for cid, args in cases:
        equal = _row_equal(plus_rows[cid], minus_rows[cid])
        case_rows.append({
            "case_id": cid,
            "args": _args_description(task_id, cid, args),
            "observation_plus": plus_rows[cid]["observation"],
            "observation_minus": minus_rows[cid]["observation"],
            "observable_equal": equal,
            "a_has_local_effect": local_effects[cid]["local_effect"],
            "local_effect_detail": local_effects[cid],
        })

    # Per-test verdict.
    test_rows = {}
    for test in public_spec["tests"]:
        input_ids = test["input"].get("case_ids") or [test["input"].get("case_id")]
        equal_all = all(row["observable_equal"] for row in case_rows
                        if row["case_id"] in input_ids)
        if not test_plus[test["name"]]["passed"]:
            verdict = "test_broken"
        elif not test_minus[test["name"]]["passed"]:
            verdict = "would_be_caught"
        elif equal_all:
            verdict = "masked"
        else:
            verdict = "assertion_gap"
        test_rows[test["name"]] = {
            "input": test["input"],
            "observable_equal": equal_all,
            "plus": test_plus[test["name"]],
            "minus": test_minus[test["name"]],
            "gold_verdict": verdict,
        }
    if public_spec["tests"]:
        verdicts = {row["gold_verdict"] for row in test_rows.values()}
        if "would_be_caught" in verdicts:
            global_verdict = "would_be_caught"
        elif verdicts == {"masked"}:
            global_verdict = "masked"
        elif "assertion_gap" in verdicts and "masked" in verdicts:
            global_verdict = "mixed"
        elif verdicts == {"assertion_gap"}:
            global_verdict = "assertion_gap"
        else:
            global_verdict = "test_broken"
    else:
        global_verdict = "not_covered"

    task_public = {
        "task_id": task_id,
        "kind": "real",
        "entry": "program",
        "program": {
            "language": "python",
            "source": source_plus,
            "target_A": {
                "line": line,
                "text": _target_text(source_plus, line),
                "kind": "call" if task_id == "real_formatdef" else "assignment",
            },
        },
        "deletion": {
            "kind": "reverse_commit_patch",
            "description": (
                "P+ is the pre-deletion source at the stated parent commit; "
                "P- applies the developer's real one-line deletion from the "
                "stated child commit."
            ),
            "diff": public_spec["provenance"]["diff"],
            "p_minus_source": source_minus,
        },
        "existing_tests": [
            {
                "name": test["name"],
                "source": test["source"],
                "input": test["input"],
                "extraction": test.get("extraction"),
                "results": {
                    "plus": test_plus[test["name"]],
                    "minus": test_minus[test["name"]],
                },
            }
            for test in public_spec["tests"]
        ],
        "existing_test_suite": public_spec.get("suite_result"),
        "input_domain": {
            "kind": "explicit",
            "args": (["func"] if task_id == "real_formatdef"
                     else ["declared", "provided"]),
            "cases": public_spec["domain_cases"],
            "generator": public_spec["generator"],
            "note": ("The program's legal input space is not finite.  The "
                     "declared domain is a frozen finite set of representative "
                     "inputs; every claim is BOUNDED to this set, never a "
                     "proof over all legal inputs."),
        },
        "observable_behavior": public_spec["observable"],
        "why_suspected_redundant": public_spec["why_suspected_redundant"],
        "provenance": public_spec["provenance"],
    }

    oracle = {
        "kind": "real",
        "domain_size": len(cases),
        "masked_count": sum(1 for row in case_rows if row["observable_equal"]),
        "exposed_count": sum(1 for row in case_rows if not row["observable_equal"]),
        "masked_with_local_effect_count": sum(
            1 for row in case_rows
            if row["observable_equal"] and row["a_has_local_effect"]),
        "cases": case_rows,
        "existing_tests": test_rows,
        "global_test_verdict": global_verdict,
    }

    if task_id == "real_formatdef":
        real_attr = {
            "status": "unconfirmed",
            "confirmed_claims": [],
            "observed_absorption": (
                "The outer `%s` formatting converts both str(signature) and "
                "the Signature object to the same string.  A changes the type "
                "of the intermediate value (str vs Signature) but not the "
                "final string."
            ),
            "why_unconfirmed": (
                "There is no separately controllable operation in the "
                "extraction whose removal can be intervened on without "
                "changing the function's contract; the absorption is an "
                "implicit conversion, not an independent source operation.  "
                "The mechanism is therefore recorded as unconfirmed."
            ),
        }
    else:
        real_attr = {
            "status": "no_masking_relation",
            "confirmed_claims": [],
            "observed_absorption": (
                "A has no local effect: `set(declared) - set(keys)` and "
                "`set(declared) - keys` are value-identical for every frozen "
                "input."
            ),
            "why_unconfirmed": (
                "There is no behavior to mask: deleting A changes neither the "
                "assigned value nor the observable.  This is a fully redundant "
                "deletion, not a masking relation."
            ),
        }

    attribution = {
        "real": True,
        "local_effect": local_effects,
        "tests": test_rows,
        "global_test_verdict": global_verdict,
        "masking": real_attr,
    }
    return task_public, oracle, attribution


def main() -> int:
    if LOG.exists():
        LOG.unlink()
    log("pilot build: every label below is produced by execution")
    log(f"python: {sys.version.split()[0]}")
    log(f"root: {ROOT}")

    tasks = []
    oracle_tasks = {}
    attribution_tasks = {"controlled": {}, "real": {}}

    for task_id in ("ctrl_01", "ctrl_02", "ctrl_03"):
        task, oracle, attribution = build_controlled(task_id)
        tasks.append(task)
        oracle_tasks[task_id] = oracle
        attribution_tasks["controlled"][task_id] = attribution
        log(f"{task_id}: domain={oracle['domain_size']} "
            f"masked={oracle['masked_count']} exposed={oracle['exposed_count']} "
            f"masked_with_local_effect={oracle['masked_with_local_effect_count']} "
            f"absorbers={[c['ops'] for c in attribution['absorber_sets']]} "
            f"coexisting={[c['ops'] for c in attribution['coexisting_sets']]}")
        log(f"  self-check guard agrees on all cases: "
            f"{attribution['design_guard_self_check']['agrees_with_execution_on_all_cases']}")

    for task_id in ("real_formatdef", "real_setdiff"):
        task, oracle, attribution = build_real(task_id)
        tasks.append(task)
        oracle_tasks[task_id] = oracle
        attribution_tasks["real"][task_id] = attribution
        log(f"{task_id}: domain={oracle['domain_size']} "
            f"masked={oracle['masked_count']} exposed={oracle['exposed_count']} "
            f"masked_with_local_effect={oracle['masked_with_local_effect_count']} "
            f"test_verdict={oracle['global_test_verdict']} "
            f"masking_status={attribution['masking']['status']}")

    tasks_doc = {
        "schema": "mace-benchmark-pilot/1",
        "frozen_at": "2026-11-01",
        "public_only": True,
        "notes": (
            "The solver receives only this file.  Masking roles, intervention "
            "tables, and per-input labels are in oracle.json / "
            "attribution.json and are never passed to the solver."
        ),
        "tasks": tasks,
    }
    oracle_doc = {
        "schema": "mace-benchmark-pilot-oracle/1",
        "evidence_level": "BOUNDED",
        "generation": (
            "Each case was executed on P+ and P- (and on every enable/disable "
            "combination of the marked operations for controlled tasks) by "
            "scripts/pilot_build.py using benchmark_pilot.engine.  Equality "
            "is equality of the specified observable, with exception type and "
            "message as the observation when a version raises.  This is a "
            "complete enumeration of the frozen finite domain, not a proof "
            "over all legal inputs."
        ),
        "domain_status": (
            "BOUNDED on the explicitly listed frozen cases.  No PROVEN claim "
            "is made anywhere in this file."
        ),
        "tasks": oracle_tasks,
    }
    attribution_doc = {
        "schema": "mace-benchmark-pilot-attribution/1",
        "generation": (
            "Controlled attribution is computed by executing both versions "
            "under every subset of disabled operations.  An absorber set is a "
            "minimal set of operations that, when enabled alone, masks A on "
            "some frozen input.  A coexisting set is a minimal set of at "
            "least two operations whose simultaneous disabling is needed to "
            "unmask A on some input.  Real tasks have no safe intervention and "
            "are recorded as unconfirmed."
        ),
        "evidence_level": "BOUNDED",
        **attribution_tasks,
    }

    engine.write_json(str(OUT / "tasks.json"), tasks_doc)
    engine.write_json(str(OUT / "oracle.json"), oracle_doc)
    engine.write_json(str(OUT / "attribution.json"), attribution_doc)
    log("wrote tasks.json, oracle.json, attribution.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
