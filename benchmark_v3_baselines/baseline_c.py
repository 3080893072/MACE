"""Baseline C: deterministic AST + intervention, no language model.

Pipeline
--------
1. ``ast_discovery`` proposes operations from the public source.
2. A fixed public input grid is executed against every single-operation
   deletion; operations with no observable effect are dropped.
3. Every subset of the remaining (at most six) operations is enumerated for
   each input, producing masked/exposed maps and minimal sufficient/breaking
   sets, exactly the benchmark's public definitions restricted to the
   discovered universe.
4. Only relations that a witness supports are emitted.  A set is emitted as
   MSMS/MMBS only when every member is causally active on that input (deleting
   it alone changes P+).  Anything else is recorded as UNKNOWN, never as a
   claimed relation.

No model is called.  The output is a normal submission envelope.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Sequence

from benchmark_v3_baselines import claims as claim_io
from benchmark_v3_baselines import graph_search
from benchmark_v3_baselines.ast_discovery import discover, rank_and_prune
from benchmark_v3_baselines.config import BUDGET
from benchmark_v3_baselines.execution import Executor
from benchmark_v3_baselines.inputs import grid_for
from benchmark_v3_baselines.public_io import load_task

BASELINE_VERSION = "C-ast-intervention-1.0"

PROBES = {
    "jinja2_bytecode_cache_read": "probe_jinja_bytecode_cache.py",
    "werkzeug_bind_server_name_lower": "probe_werkzeug_bind_server_name.py",
    "werkzeug_filestorage_stream_name": "probe_werkzeug_filestorage.py",
    "werkzeug_get_host_default_empty": "probe_werkzeug_get_host.py",
    "werkzeug_secure_filename_ascii_filter": "probe_werkzeug_secure_filename.py",
}


def _payload_key(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


def emission_allowed(sets: Sequence[Sequence[str]], active: Sequence[str],
                     emission_mode: str = "active_filtered") -> List[List[str]]:
    """EXP-1 emission layer, exposed for direct unit testing.

    Under ``active_filtered`` a set is emitted only when every member is
    individually active.  Under ``minimality_only`` all sets are emitted;
    by the time a set reaches this layer it has already passed intervention
    legality, A execution/local effect, the masking predicate, and strict
    subset minimality.  No causal claim is added or removed by this switch
    beyond the original member-activity filter.
    """
    if emission_mode not in {"active_filtered", "minimality_only"}:
        raise ValueError(f"unknown emission_mode: {emission_mode!r}")
    if emission_mode == "minimality_only":
        return [list(item) for item in sets]
    active_set = set(active)
    return [list(item) for item in sets if set(item) <= active_set]


def _active_ops(executor: Executor, payload: Dict[str, Any]) -> List[str]:
    """Operations whose deletion changes an observation on this input.

    A masking operation is typically inert while A is present and only runs
    once A is deleted, so both sides are checked.  An operation that is inert
    on both sides (a branch not taken on this input) cannot explain masking
    or breaking and is excluded from the witness's set.
    """
    base_plus = executor.observation([], "plus", payload)
    base_minus = executor.observation([], "minus", payload)
    active = []
    for op_id in executor.universe:
        if (executor.observation([op_id], "plus", payload) != base_plus
                or executor.observation([op_id], "minus", payload) != base_minus):
            active.append(op_id)
    return active


def run(task_id: str, *, max_ops: int | None = None,
        max_inputs: int | None = None,
        emission_mode: str = "active_filtered",
        candidate_ops: Sequence[Dict[str, Any]] | None = None,
        candidate_source: str = "ast",
        search: str = "exhaustive",
        graph_scores: Dict[str, float] | None = None,
        msms_scores: Dict[str, float] | None = None,
        mmbs_scores: Dict[str, float] | None = None,
        hypotheses: Dict[str, Any] | None = None,
        max_hypothesis_probes_per_role: int = 3,
        probe_budget: int | None = None,
        graph_meta: Dict[str, Any] | None = None,
        record_diagnostics: bool = False) -> Dict[str, Any]:
    """Run one task under a selected emission/search configuration.

    ``emission_mode="active_filtered"`` is the frozen C behaviour: only
    relations whose every member is individually active are emitted.
    ``emission_mode="minimality_only"`` removes that extra filter while
    keeping intervention legality, A-execution/local-effect checks, the
    masking predicate, strict-subset minimality, and UNKNOWN/INVALID
    classification.  It is a defect fix, not a new masking algorithm.

    ``candidate_ops`` replaces AST discovery (and its effect pruning) with an
    externally supplied candidate set.  ``search="graph"`` replaces complete
    enumeration with graph-ordered, three-valued evidence search.
    """
    if emission_mode not in {"active_filtered", "minimality_only"}:
        raise ValueError(f"unknown emission_mode: {emission_mode!r}")
    if search not in {"exhaustive", "graph", "role_separated"}:
        raise ValueError(f"unknown search mode: {search!r}")
    diagnostics = (record_diagnostics or emission_mode != "active_filtered"
                   or candidate_ops is not None or search != "exhaustive")
    max_ops = max_ops or BUDGET["max_candidate_ops"]
    max_inputs = max_inputs or BUDGET["max_inputs"]
    loaded = load_task(task_id)
    task = loaded["task"]
    inputs = grid_for(task_id, max_inputs)
    executor = Executor(task_id, task["project_id"], PROBES[task_id],
                        task["target_operation"], f"c_{task_id}")

    if candidate_ops is None:
        discovered = discover(task, loaded["source_text"])
        executor.set_universe(discovered["candidate_ops"])
        pruning = rank_and_prune(executor, discovered, inputs, max_ops)
        universe = pruning["universe"]
    else:
        universe = list(candidate_ops)
        discovered = {
            "candidate_ops": universe,
            "candidate_ids": [op["id"] for op in universe],
            "discovery_rule": "injected_candidates",
            "candidate_source": candidate_source,
        }
        pruning = {
            "universe": universe,
            "kept": len(universe),
            "dropped": [],
            "mode": "injected_candidates",
        }
    executor.set_universe(universe)

    per_input: List[Dict[str, Any]] = []
    search_runs: List[Dict[str, Any]] = []
    universe_ids = [op["id"] for op in universe]
    for payload in inputs:
        executes = executor.a_executes(payload)
        plus = executor.observation([], "plus", payload)
        minus = executor.observation([], "minus", payload)
        executable = (not plus.get("__probe_error__")
                      and not minus.get("__probe_error__"))
        masked_empty = bool(executable and plus.get("outcome") == "return"
                            and plus == minus)
        exposed_empty = bool(executable and plus != minus)
        # Minimal-set enumeration is only meaningful on a masked input; an
        # exposing input has no masking relation to minimise (the public
        # scorer treats it the same way).
        active: List[str] = []
        rel = {"msms_ids": [], "mmbs_ids": []}
        metrics: Dict[str, Any] | None = None
        if executes and masked_empty:
            # Isolation is computed under every mode so probe accounting is
            # comparable; only emission eligibility changes with EXP-1.
            active = _active_ops(executor, payload)
            if search == "graph":
                rel = graph_search.search_relations(
                    executor, payload, universe_ids,
                    graph_scores=graph_scores, mode="graph",
                    budget=probe_budget)
                metrics = {
                    key: rel[key] for key in (
                        "evaluations", "subsets_total", "complete",
                        "evidence_complete",
                        "cache_hits", "executor_cache_hits",
                        "unknown_subsets", "invalid_subsets",
                        "first_msms", "first_mmbs", "wall_seconds",
                        "search_mode")
                }
                metrics["msms_unknown"] = rel["msms_unknown"]
                metrics["mmbs_unknown"] = rel["mmbs_unknown"]
            elif search == "role_separated":
                rel = graph_search.search_relations_role_separated(
                    executor, payload, universe_ids,
                    msms_scores=msms_scores, mmbs_scores=mmbs_scores,
                    budget=probe_budget, hypotheses=hypotheses,
                    max_hypothesis_probes_per_role=(
                        max_hypothesis_probes_per_role))
                metrics = {
                    key: rel[key] for key in (
                        "evaluations", "subsets_total", "complete",
                        "evidence_complete", "cache_hits",
                        "executor_cache_hits", "unknown_subsets",
                        "invalid_subsets", "first_msms", "first_mmbs",
                        "search_mode", "reused_evidence",
                        "duplicate_probes", "hypotheses", "schedule")
                }
                metrics["msms_unknown"] = rel["msms_unknown"]
                metrics["mmbs_unknown"] = rel["mmbs_unknown"]
                metrics["wall_seconds"] = None
            else:
                rel = executor.relations(payload, universe_ids)
                if diagnostics:
                    profile = graph_search.profile_from_maps(
                        rel["masked"], rel["exposed"], universe_ids)
                    metrics = {
                        "evaluations": profile["evaluations"],
                        "subsets_total": profile["subsets_total"],
                        "complete": profile["complete"],
                        # Exhaustive C collapses probe failures into
                        # not-masked/not-exposed; it has no three-valued
                        # evidence, so do not claim evidence completeness.
                        "evidence_complete": None,
                        "cache_hits": 0,
                        "executor_cache_hits": None,
                        "unknown_subsets": 0,
                        "invalid_subsets": 0,
                        "first_msms": profile["first_msms"],
                        "first_mmbs": profile["first_mmbs"],
                        "wall_seconds": None,
                        "search_mode": "exhaustive",
                    }
            if diagnostics:
                search_runs.append({
                    "input": payload,
                    "mode": search,
                    "metrics": metrics,
                })
        row = {
            "input": payload,
            "a_executes": executes,
            "active_ops": active,
            "masked_empty": masked_empty,
            "exposed_empty": exposed_empty,
            "msms_ids": rel["msms_ids"],
            "mmbs_ids": rel["mmbs_ids"],
            "observations_empty": {"plus": plus, "minus": minus},
        }
        if diagnostics:
            row["search_metrics"] = metrics
        per_input.append(row)

    by_id = {op["id"]: op for op in universe}

    def allowed(sets: Sequence[Sequence[str]], active: Sequence[str]) -> List[List[str]]:
        return emission_allowed(sets, active, emission_mode)

    filter_stats = {"msms_dropped": 0, "mmbs_dropped": 0,
                    "msms_total": 0, "mmbs_total": 0}

    # ---- group verified relations across inputs -------------------------
    msms_groups: Dict[tuple, List[Dict[str, Any]]] = {}
    mmbs_groups: Dict[tuple, List[Dict[str, Any]]] = {}
    exposing_inputs: List[Dict[str, Any]] = []
    for row in per_input:
        if not row["a_executes"]:
            continue
        if row["exposed_empty"]:
            exposing_inputs.append(row["input"])
        if not row["masked_empty"]:
            continue
        # The public scorer requires an observable minimal breaking set on
        # every input used for an MSMS claim: without one there is no local
        # effect to mask, and the input cannot support the claim.  Apply the
        # same condition when grouping inputs.
        filter_stats["msms_total"] += len(row["msms_ids"])
        filter_stats["mmbs_total"] += len(row["mmbs_ids"])
        allowed_msms = allowed(row["msms_ids"], row["active_ops"])
        allowed_mmbs = allowed(row["mmbs_ids"], row["active_ops"])
        filter_stats["msms_dropped"] += len(row["msms_ids"]) - len(allowed_msms)
        filter_stats["mmbs_dropped"] += len(row["mmbs_ids"]) - len(allowed_mmbs)
        if row["mmbs_ids"]:
            for item in allowed_msms:
                msms_groups.setdefault(tuple(item), []).append(row["input"])
        for item in allowed_mmbs:
            mmbs_groups.setdefault(tuple(item), []).append(row["input"])

    claims: List[Dict[str, Any]] = []
    evidence: List[Dict[str, Any]] = []
    if exposing_inputs:
        claims.append(claim_io.exposing(exposing_inputs[0]))
        evidence.append({"type": "EXPOSING_COUNTEREXAMPLE",
                         "inputs": exposing_inputs, "basis": "execution"})

    def add_minimal(kind: str, groups: Dict[tuple, List[Dict[str, Any]]]) -> None:
        for ids, payloads in sorted(groups.items(), key=lambda kv: (len(kv[0]), kv[0])):
            ops = [by_id[op_id] for op_id in ids]
            if len(payloads) >= 2:
                claim = {"type": kind, "inputs": payloads[:12],
                         "operations": claim_io.operation_refs(ops)}
                level = "FINITE_DOMAIN_EXACT"
            else:
                claim = claim_io.minimal_set(kind, payloads[0], ops)
                level = "WITNESS_VERIFIED"
            claims.append(claim)
            evidence.append({"type": kind, "operations": list(ids),
                             "inputs": payloads[:12], "level": level,
                             "basis": "subset enumeration over discovered universe"})

    add_minimal("MSMS", msms_groups)
    add_minimal("MMBS", mmbs_groups)

    # ---- prerequisite-conditioned breaking ------------------------------
    prereq_count = 0
    for ids, payloads in sorted(msms_groups.items()):
        if prereq_count >= 2:
            break
        # The scorer requires the set to be a minimal *breaking* set on the
        # condition input as well.
        condition_inputs = {
            _payload_key(row["input"]) for row in per_input
            if ids in {tuple(item) for item in row["mmbs_ids"]}
        }
        payloads = [p for p in payloads if _payload_key(p) in condition_inputs]
        if not payloads:
            continue
        condition = payloads[0]
        condition_key = _payload_key(condition)
        for control_row in per_input:
            if not control_row["a_executes"]:
                continue
            if _payload_key(control_row["input"]) == condition_key:
                continue
            if not (control_row["masked_empty"] or control_row["exposed_empty"]):
                continue
            if ids in {tuple(item) for item in control_row["mmbs_ids"]}:
                continue  # the set also breaks there: no prerequisite shown
            claims.append(claim_io.prerequisite(
                condition, control_row["input"],
                [by_id[op_id] for op_id in ids],
                "masking holds on input; the same set does not break on control"))
            evidence.append({
                "type": "PREREQUISITE_BREAKING",
                "operations": list(ids),
                "input": condition,
                "control_input": control_row["input"],
                "level": "WITNESS_VERIFIED",
            })
            prereq_count += 1
            break

    claims = claims[:BUDGET["max_claims_per_task"]]

    # ---- unknowns --------------------------------------------------------
    unknown = []
    if not universe:
        unknown.append("no operation survived AST discovery and effect pruning")
    if not exposing_inputs:
        unknown.append("no exposing input found on the public grid")
    for row in per_input:
        if row["a_executes"] and row["masked_empty"]:
            if not allowed(row["msms_ids"], row["active_ops"]):
                unknown.append(
                    "masked input with no causally active minimal sufficient "
                    f"set: {_payload_key(row['input'])}")
    if not msms_groups:
        unknown.append("no MSMS relation could be established")
    if not mmbs_groups:
        unknown.append("no MMBS relation could be established")
    if diagnostics and emission_mode == "active_filtered" and (
            filter_stats["msms_dropped"] or filter_stats["mmbs_dropped"]):
        unknown.append(
            "EXP-1 emission filter dropped verified minimal sets: "
            f"MSMS {filter_stats['msms_dropped']}/{filter_stats['msms_total']}, "
            f"MMBS {filter_stats['mmbs_dropped']}/{filter_stats['mmbs_total']}")

    result = {
        "run_label": "NO_MODEL_DETERMINISTIC_RUN",
        "baseline": "C_ast_intervention",
        "baseline_version": BASELINE_VERSION,
        "task_id": task_id,
        "discovery": discovered,
        "pruning": pruning,
        "universe": universe,
        "inputs": inputs,
        "per_input": per_input,
        "submission": claim_io.envelope(task_id, claims, "baseline-C"),
        "evidence": evidence,
        "unknowns": unknown,
        "probe_executions": executor.probe_executions,
        "variant_builds": len(executor._variants),
    }
    if diagnostics:
        search_summary = {
            "mode": search,
            "inputs_with_search": len(search_runs),
            "evaluations": sum(run["metrics"]["evaluations"]
                               for run in search_runs),
            "subsets_total": sum(run["metrics"]["subsets_total"]
                                 for run in search_runs),
            "complete": all(run["metrics"]["complete"] for run in search_runs),
            "executor_cache_hits": sum(
                int(run["metrics"].get("executor_cache_hits") or 0)
                for run in search_runs),
            "unknown_subsets": sum(run["metrics"]["unknown_subsets"]
                                   for run in search_runs),
            "invalid_subsets": sum(run["metrics"]["invalid_subsets"]
                                   for run in search_runs),
            "msms_unknown": sum(len(run["metrics"].get("msms_unknown", []))
                                for run in search_runs),
            "mmbs_unknown": sum(len(run["metrics"].get("mmbs_unknown", []))
                                for run in search_runs),
        }
        result.update({
            "discovery_source": (candidate_source if candidate_ops is not None
                                 else "ast"),
            "emission_mode": emission_mode,
            "filter_stats": filter_stats,
            "search": search_summary,
            "graph_meta": graph_meta,
            "search_runs": search_runs,
        })
    return result


def run_and_write(task_id: str, out_dir) -> Dict[str, Any]:
    from pathlib import Path

    result = run(task_id)
    path = Path(out_dir)
    path.mkdir(parents=True, exist_ok=True)
    (path / "baseline_c.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (path / "submission.json").write_text(
        json.dumps(result["submission"], ensure_ascii=False, indent=2),
        encoding="utf-8")
    return result
