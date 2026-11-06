"""Minimal experiment: Qwen semantic relation discovery vs Graph-only.

Arms (section 4 of the round instruction):

A  Graph-only C0        U_graph, role-separated search, no hypotheses
B  Graph + old Qwen     U_graph, legacy model output under the same gate
C  Semantic discovery   U_union, new-protocol relations -> role hypotheses
Cg Semantic / U_graph   same hypotheses restricted to U_graph (same-U control)

Tasks: ``ctrl_02``, ``ctrl_03`` and the two real-source DEV tasks
``werkzeug_get_host_default_empty`` and ``werkzeug_filestorage_stream_name``.

Nothing is fabricated: a model arm without saved or live model output is
reported as ``NOT_RUN``.  Every relation starts as ``HYPOTHESIS``; only the
causal search (strict-subset minimality over real interventions) can confirm
a MSMS/MMBS.  The pilot verifier additionally scores the model's claimed
conditions on the frozen domain.

Examples
--------
Emit prompts for an external model::

    python -m scripts.run_semantic_relation_discovery --emit-prompts runs/v3_semantic_relations/prompts

Replay saved model output (JSON mapping task_id -> raw response text)::

    python -m scripts.run_semantic_relation_discovery --hypotheses runs/v3_semantic_relations/qwen.json

Live call (needs an Ollama endpoint)::

    python -m scripts.run_semantic_relation_discovery --live --endpoint http://127.0.0.1:11434
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from benchmark_real_v3.config import PROJECTS
from benchmark_real_v3.variant_lab import build_variant  # noqa: F401  (documented)
from benchmark_v3_baselines.baseline_c import PROBES
from benchmark_v3_baselines.config import MODEL
from benchmark_v3_baselines.execution import Executor
from benchmark_v3_baselines.graph_search import search_relations_role_separated
from benchmark_v3_baselines.inputs import grid_for
from benchmark_v3_baselines.public_io import load_task
from open_ops import discover
from open_ops.pilot_oracle import PilotOracle, searchable_cases
from open_ops.semantic_relations import (
    SourceIndex, build_prompt, build_universes, map_proposal,
    numbered_source, parse_semantic_hypotheses, relations_to_role_hypotheses,
    role_tuples)

KIT = Path(__file__).resolve().parents[1]
AUDIT = KIT / "runs" / "v3_full_mace_audit" / "audit.json"
UNIVERSE_RUN = KIT / "runs" / "v3_baseline_pilot"
PILOT_TASKS = ("ctrl_02", "ctrl_03")
V3_TASKS = ("werkzeug_get_host_default_empty",
            "werkzeug_filestorage_stream_name")
DEFAULT_OUT = KIT / "runs" / "v3_semantic_relations" / "results.json"
BUDGET = 16


# ---------------------------------------------------------------------------
# Common helpers
# ---------------------------------------------------------------------------

def _task_file(task: Dict[str, Any]) -> str:
    target = task.get("target_operation") or task.get("program", {}).get("target_A")
    return (target or {}).get("file", "<program>")


def _legacy_content(task_id: str) -> Optional[str]:
    path = KIT / "benchmark_open_v1" / "interface" / "direct_qwen" / f"{task_id}_raw.json"
    if not path.exists():
        return None
    record = json.loads(path.read_text(encoding="utf-8"))
    return record.get("raw_response")


def _new_content(task_id: str, supplied: Optional[Dict[str, Any]]) -> Optional[str]:
    if not supplied:
        return None
    value = supplied.get(task_id)
    if value is None:
        return None
    if isinstance(value, str):
        return value
    if isinstance(value, dict):
        return value.get("raw_response") or value.get("content")
    return None


def _read_supplied(path: Optional[Path]) -> Dict[str, Any]:
    if path is None:
        return {}
    if path.is_dir():
        out: Dict[str, Any] = {}
        for item in path.glob("*.json"):
            out[item.stem] = json.loads(item.read_text(encoding="utf-8"))
        for item in path.glob("*.txt"):
            out[item.stem] = item.read_text(encoding="utf-8")
        return out
    return json.loads(path.read_text(encoding="utf-8"))


def _first_of(result: Dict[str, Any]) -> Dict[str, Any]:
    def entry(value):
        if not value:
            return None
        return {"index": value["evaluations"], "set": value["set"]}
    return {"msms": entry(result.get("first_msms")),
            "mmbs": entry(result.get("first_mmbs"))}


def _hash(path: Path) -> Optional[str]:
    if not path.exists():
        return None
    return hashlib.sha256(path.read_bytes()).hexdigest()


# ---------------------------------------------------------------------------
# Pilot tasks
# ---------------------------------------------------------------------------

def pilot_graph_ops(task: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = discover(task)
    return [{
        "id": op.key,
        "key": op.key,
        "file": "<program>",
        "first_line": op.line,
        "last_line": op.end_line,
        "line": op.line,
        "end_line": op.end_line,
        "col": op.col,
        "end_col": op.end_col,
        "kind": op.kind,
        "node_type": {"if": "If", "assign": "Assign",
                      "annassign": "AnnAssign", "augassign": "AugAssign",
                      "expr": "Expr"}.get(op.kind, op.kind),
        "code": op.text,
        "text": op.text,
    } for op in result.candidates]


def pilot_context(task_id: str) -> Dict[str, Any]:
    import sys
    scripts = str(KIT / "scripts")
    if scripts not in sys.path:
        sys.path.insert(0, scripts)
    from check_open_interface import Verifier  # noqa: E402

    tasks = {t["task_id"]: t for t in json.loads(
        (KIT / "benchmark_pilot" / "tasks.json").read_text(encoding="utf-8"))["tasks"]}
    attribution = json.loads(
        (KIT / "benchmark_pilot" / "attribution.json").read_text(
            encoding="utf-8"))["controlled"][task_id]
    task = tasks[task_id]
    verifier = Verifier(task, attribution)
    graph_ops = pilot_graph_ops(task)
    index = SourceIndex.from_source("<program>", task["program"]["source"])
    line_by_op = {op["id"]: op["first_line"] for op in graph_ops}
    name_by_id = {op["id"]: verifier.op_for_line(op["first_line"])
                  for op in graph_ops}
    return {"task": task, "attribution": attribution, "verifier": verifier,
            "graph_ops": graph_ops, "index": index,
            "line_by_op": line_by_op, "name_by_id": name_by_id}


def run_pilot_arm(context: Dict[str, Any], *,
                  universe: Sequence[Dict[str, Any]],
                  hypotheses: Optional[Dict[str, Any]],
                  budget: int = BUDGET,
                  max_hypothesis_probes: int = 3) -> Dict[str, Any]:
    verifier = context["verifier"]
    line_by_op = {op["id"]: op["first_line"] for op in universe}
    rows: List[Dict[str, Any]] = []
    for case_id, args in searchable_cases(verifier):
        oracle = PilotOracle(verifier, case_id, line_by_op)
        before = verifier.executions
        role_hyp = hypotheses or {"msms": [], "mmbs": []}
        result = search_relations_role_separated(
            None, args, [op["id"] for op in universe], budget=budget,
            hypotheses={"msms": role_tuples(role_hyp, "msms"),
                        "mmbs": role_tuples(role_hyp, "mmbs")},
            max_hypothesis_probes_per_role=max_hypothesis_probes,
            oracle=oracle)
        rows.append({
            "case_id": case_id,
            "input": args,
            "searched": True,
            "evaluations": result["evaluations"],
            "complete": result["complete"],
            "first_msms": _first_of(result)["msms"],
            "first_mmbs": _first_of(result)["mmbs"],
            "msms_ids": result["msms_ids"],
            "mmbs_ids": result["mmbs_ids"],
            "schedule": result["schedule"],
            "queues": result["queues"],
            "unknown_subsets": result["unknown_subsets"],
            "invalid_subsets": result["invalid_subsets"],
            "reused_evidence": result["reused_evidence"],
            "duplicate_probes": result["duplicate_probes"],
            "hypotheses": result["hypotheses"],
            "probe_executions": verifier.executions - before,
        })
    return {"task": context["task"]["task_id"],
            "universe": [op["id"] for op in universe],
            "inputs": rows,
            "probe_executions": verifier.executions}


# ---------------------------------------------------------------------------
# Pilot relation verification and candidate metrics
# ---------------------------------------------------------------------------

def _witness_case(verifier, candidates: List[str]) -> Optional[Dict[str, Any]]:
    for case_id, args in verifier.cases:
        if verifier.base_equal.get(case_id) and verifier.local_effect.get(case_id):
            return args
    return None


def verify_pilot_relations(relations: Sequence[Dict[str, Any]],
                           context: Dict[str, Any]) -> List[Dict[str, Any]]:
    verifier = context["verifier"]
    name_by_id = {op["id"]: context["verifier"].op_for_line(op["first_line"])
                  for op in context["graph_ops"]}
    out = []
    for relation in relations:
        names = [name_by_id.get(op_id) for op_id in relation["ops"]]
        record = {"relation_index": relation["relation_index"],
                  "kind": relation["kind"], "ops": relation["ops"],
                  "names": names}
        if any(name is None for name in names):
            record.update({"status": "UNMAPPED_TO_VERIFIER",
                           "reason": "operation is outside the declared pilot ops"})
            out.append(record)
            continue
        kind = relation["kind"]
        if kind == "fallback":
            kind = "cooperative" if len(names) > 1 else "independent"
        if kind not in ("independent", "cooperative", "coexisting"):
            record.update({"status": "UNSUPPORTED_KIND", "kind": kind})
            out.append(record)
            continue
        candidates = [args for cid, args in verifier.cases
                      if verifier.base_equal.get(cid)
                      and verifier.local_effect.get(cid)]
        if not candidates:
            record.update({"status": "NO_WITNESS"})
            out.append(record)
            continue
        rank = {"VERIFIED": 4, "INCOMPLETE": 3, "UNVERIFIED": 2,
                "FALSE": 1, "FORMAT_ERROR": 0}

        def quality(result: Dict[str, Any]) -> tuple:
            # Same status first, then prefer the attempt that got furthest:
            # a record with condition evidence or more executed checks.
            return (rank.get(result.get("status"), -1),
                    1 if result.get("condition") else 0,
                    len(result.get("checks") or {}))

        best: Optional[Dict[str, Any]] = None
        attempts = 0
        for witness in candidates:
            attempts += 1
            submitted = {
                "operations": [{"line": verifier.op_lines[name]}
                               for name in names],
                "kind": kind,
                "input": witness,
                "condition": relation.get("condition"),
            }
            result = verifier.verify_relation(submitted)
            if result.get("status") == "VERIFIED":
                best = result
                break
            if best is None or quality(result) > quality(best):
                best = result
        best = best or {}
        record.update({
            "status": best.get("status"),
            "reason": best.get("reason"),
            "case_id": best.get("case_id"),
            "checks": best.get("checks"),
            "condition": best.get("condition"),
            "attempts": attempts,
        })
        out.append(record)
    return out


def pilot_candidate_metrics(proposals: Sequence[Dict[str, Any]],
                            context: Dict[str, Any]) -> Dict[str, Any]:
    truth = set(context["attribution"]["ops"])
    name_by_id = context["name_by_id"]
    reference = {op["id"] for op in context["graph_ops"]}
    exclude = [context["task"]["program"]["target_A"]["line"]]
    mapped = []
    rejected = []
    for proposal in proposals:
        result = map_proposal(proposal, context["index"], context["graph_ops"],
                              style="pilot", exclude_lines=exclude)
        if result["status"] != "mapped":
            rejected.append(result)
            continue
        op = result["op"]
        mapped.append({"id": op["id"],
                       "name": name_by_id.get(op["id"]),
                       "in_graph": result["in_graph"],
                       "new": op["id"] not in reference})
    names = {item["name"] for item in mapped if item["name"]}
    new = [item for item in mapped if item["new"]]
    new_named = {item["name"] for item in new if item["name"]}
    return {
        "truth_ops": sorted(truth),
        "mapped_ops": mapped,
        "mapped_count": len(mapped),
        "new_ops": new,
        "new_real_ops": sorted(new_named & truth),
        "new_false_ops": sorted(new_named - truth),
        "precision": (round(len(names & truth) / len(names), 4)
                      if names else None),
        "recall": round(len(names & truth) / len(truth), 4) if truth else None,
        "rejected": rejected,
    }


def graph_fixture(task: Dict[str, Any]) -> Dict[str, Any]:
    """A new-protocol-shaped fixture built from the graph's own relations.

    This is a pipeline control, **not** model output: it checks that a
    correct semantic answer can be carried through the new protocol and
    gated by the causal search.  It is never counted as a Qwen result.
    """
    result = discover(task)
    relations = []
    for relation in result.relations:
        relations.append({
            "kind": relation.kind,
            "operations": [{"line": op.line,
                            "text": (op.text.splitlines() or [""])[0].strip()}
                           for op in relation.operations],
            "condition": relation.condition,
            "source_evidence": f"graph discovery: {relation.witness_case}",
            "rationale": "deterministic graph relation, used as a pipeline fixture",
        })
    return {"relations": relations, "notes": "graph-derived fixture, not a model"}


def pilot_truth(context: Dict[str, Any]) -> Dict[str, Any]:
    per_case = {}
    for row in context["attribution"].get("per_case", []):
        per_case[row["case_id"]] = {
            "masked": row.get("masked"),
            "absorber_sets": row.get("absorber_sets"),
            "individually_masking_ops": row.get("individually_masking_ops"),
            "coexisting_unmasking_sets": row.get("coexisting_unmasking_sets"),
        }
    return per_case


# ---------------------------------------------------------------------------
# v3 tasks
# ---------------------------------------------------------------------------

def v3_universe(task_id: str) -> List[Dict[str, Any]]:
    path = UNIVERSE_RUN / "tasks" / task_id / "baseline_c" / "baseline_c.json"
    return json.loads(path.read_text(encoding="utf-8"))["universe"]


def v3_indexes(task: Dict[str, Any],
               graph_ops: Sequence[Dict[str, Any]]) -> Dict[str, SourceIndex]:
    project = PROJECTS[task["project_id"]]
    files = {task["target_operation"]["file"]}
    files.update(op.get("file") for op in graph_ops if op.get("file"))
    return {file: SourceIndex.from_path(file, project["root"])
            for file in sorted(files)}


def v3_default_file(task: Dict[str, Any]) -> str:
    return task["target_operation"]["file"]


def _excerpt(source: str, function_name: Optional[str],
             target_line: int, radius: int = 45) -> Tuple[str, int]:
    """Return ``(text, first_absolute_line)`` for the prompt."""
    import ast
    if function_name:
        try:
            tree = ast.parse(source)
            best = None
            name = function_name.split(".")[-1]
            for node in ast.walk(tree):
                if not isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    continue
                first = node.lineno
                last = getattr(node, "end_lineno", first)
                if not (first <= target_line <= last):
                    continue
                if node.name == name:
                    best = (first, last)
                    break
                if best is None or (last - first) < (best[1] - best[0]):
                    best = (first, last)
            if best:
                lines = source.splitlines()
                return "\n".join(lines[best[0] - 1:best[1]]), best[0]
        except Exception:  # noqa: BLE001
            pass
    lines = source.splitlines()
    low = max(1, target_line - radius)
    high = min(len(lines), target_line + radius)
    return "\n".join(lines[low - 1:high]), low


def v3_prompt_parts(task_id: str) -> Dict[str, Any]:
    loaded = load_task(task_id)
    task = loaded["task"]
    target = task["target_operation"]
    source = loaded["source_text"]
    function = (target.get("function") or "").split(".")[-1] or None
    excerpt, line_offset = _excerpt(source, function, int(target["line"]))
    contract = task.get("legal_input_contract") or {}
    fields = contract.get("fields") or {}
    constraints = contract.get("legal_constraints") or []
    try:
        sample = grid_for(task_id, 6)
    except Exception:  # noqa: BLE001
        sample = []
    return {
        "task": task,
        "source": excerpt,
        "line_offset": line_offset - 1,
        "files": [target["file"]],
        "graph_ops": v3_universe(task_id),
        "input_domain": {
            "args": fields,
            "cases": sample,
            "note": "; ".join(constraints) if constraints else None,
        },
        "observable": json.dumps(contract.get("observation"),
                                 ensure_ascii=False),
        "loaded": loaded,
    }


def run_v3_arm(task_id: str, *, universe_ops: Sequence[Dict[str, Any]],
               hypotheses: Optional[Dict[str, Any]],
               budget: int = BUDGET,
               max_hypothesis_probes: int = 3,
               prefix: str = "sem") -> Dict[str, Any]:
    loaded = load_task(task_id)
    task = loaded["task"]
    inputs = grid_for(task_id, 16)
    executor = Executor(task_id, task["project_id"], PROBES[task_id],
                        task["target_operation"], prefix)
    executor.set_universe(list(universe_ops))
    universe = sorted(op["id"] for op in universe_ops)
    rows: List[Dict[str, Any]] = []
    for payload in inputs:
        plus = executor.observation([], "plus", payload)
        minus = executor.observation([], "minus", payload)
        executable = (not plus.get("__probe_error__")
                      and not minus.get("__probe_error__"))
        searched = bool(executor.a_executes(payload) and executable
                        and plus.get("outcome") == "return" and plus == minus)
        if not searched:
            rows.append({"input": payload, "searched": False})
            continue
        before = executor.probe_executions
        role_hyp = hypotheses or {"msms": [], "mmbs": []}
        result = search_relations_role_separated(
            executor, payload, universe, budget=budget,
            hypotheses={"msms": role_tuples(role_hyp, "msms"),
                        "mmbs": role_tuples(role_hyp, "mmbs")},
            max_hypothesis_probes_per_role=max_hypothesis_probes)
        rows.append({
            "input": payload,
            "searched": True,
            "evaluations": result["evaluations"],
            "complete": result["complete"],
            "first_msms": _first_of(result)["msms"],
            "first_mmbs": _first_of(result)["mmbs"],
            "msms_ids": result["msms_ids"],
            "mmbs_ids": result["mmbs_ids"],
            "schedule": result["schedule"],
            "queues": result["queues"],
            "unknown_subsets": result["unknown_subsets"],
            "invalid_subsets": result["invalid_subsets"],
            "reused_evidence": result["reused_evidence"],
            "duplicate_probes": result["duplicate_probes"],
            "hypotheses": result["hypotheses"],
            "probe_executions": executor.probe_executions - before,
        })
    return {"task": task_id, "universe": universe, "inputs": rows,
            "probe_executions": executor.probe_executions,
            "variants": len(executor._variants)}


def recorded_v3_arm(task_id: str, arm: str) -> Dict[str, Any]:
    audit = json.loads(AUDIT.read_text(encoding="utf-8"))
    task_audit = audit["tasks"][task_id]
    rows = []
    for row in task_audit["replays"][arm]["inputs"]:
        if not row.get("searched"):
            rows.append({"input": row["input"], "searched": False})
            continue
        first = row.get("first") or {}

        def _norm(value):
            if not value:
                return None
            return {"index": value.get("index", value.get("evaluations")),
                    "set": value.get("set")}

        rows.append({
            "input": row["input"], "searched": True,
            "evaluations": row.get("evaluations"),
            "complete": row.get("complete"),
            "first_msms": _norm(first.get("msms")),
            "first_mmbs": _norm(first.get("mmbs")),
            "msms_ids": row.get("msms", []),
            "mmbs_ids": row.get("mmbs", []),
            "schedule": row.get("order", []),
        })
    return {"task": task_id,
            "universe": sorted(task_audit["replays"][arm]["universe"]),
            "inputs": rows,
            "probe_executions": task_audit["replays"][arm]["probe_executions"]}


# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------

def summarize(arm: Dict[str, Any]) -> Dict[str, Any]:
    rows = [row for row in arm["inputs"] if row.get("searched")]
    msms = [row["first_msms"]["index"] for row in rows
            if row.get("first_msms")
            and row["first_msms"].get("index") is not None]
    mmbs = [row["first_mmbs"]["index"] for row in rows
            if row.get("first_mmbs")
            and row["first_mmbs"].get("index") is not None]
    gates = [row.get("hypotheses") for row in rows if row.get("hypotheses")]
    witness = {role: sum(bool(entry.get("witness"))
                         for gate in gates
                         for entry in gate.get("gate", {}).get(role, []))
               for role in ("msms", "mmbs")}
    probed = {role: sum(entry.get("status") != "BUDGET_SKIPPED"
                        for gate in gates
                        for entry in gate.get("gate", {}).get(role, []))
              for role in ("msms", "mmbs")}
    return {
        "universe_size": len(arm.get("universe") or []),
        "inputs_searched": len(rows),
        "evaluations": sum(int(row.get("evaluations") or 0) for row in rows),
        "complete_inputs": sum(1 for row in rows if row.get("complete")),
        "first_msms_values": msms,
        "first_msms_mean": round(sum(msms) / len(msms), 3) if msms else None,
        "first_mmbs_values": mmbs,
        "first_mmbs_mean": round(sum(mmbs) / len(mmbs), 3) if mmbs else None,
        "msms_relations": sorted({tuple(item) for row in rows
                                  for item in row.get("msms_ids", [])}),
        "mmbs_relations": sorted({tuple(item) for row in rows
                                  for item in row.get("mmbs_ids", [])}),
        "unknown_subsets": sum(int(row.get("unknown_subsets") or 0)
                               for row in rows),
        "invalid_subsets": sum(int(row.get("invalid_subsets") or 0)
                               for row in rows),
        "duplicate_probes": sum(int(row.get("duplicate_probes") or 0)
                                for row in rows),
        "reused_evidence": sum(int(row.get("reused_evidence") or 0)
                               for row in rows),
        "hypothesis_witness": witness,
        "hypothesis_probed": probed,
        "probe_executions": arm.get("probe_executions"),
    }


def _jsonable(value: Any) -> Any:
    return json.loads(json.dumps(value, ensure_ascii=False, default=str))


# ---------------------------------------------------------------------------
# Model output
# ---------------------------------------------------------------------------

def _call_live(prompt: str, endpoint: str, model: str,
               timeout: int = 900, num_ctx: int = 8192,
               num_predict: int = 4096) -> Dict[str, Any]:
    from mace.qwen import QwenClient
    # One model call per task: retries are disabled so a failure is recorded
    # as a failure instead of silently becoming a second generation.
    client = QwenClient(provider="ollama", model=model, endpoint=endpoint,
                        num_ctx=num_ctx, num_predict=num_predict,
                        temperature=0.0, seed=42, timeout=timeout, retries=0)
    messages = [
        {"role": "system", "content":
            "You analyse Python masking relations. Return one JSON object only. "
            "Every operation must cite a real file, line and source text."},
        {"role": "user", "content": prompt},
    ]
    started = time.time()
    response = client.chat(messages, purpose="semantic_relation_discovery",
                           json_mode=True)
    return {"raw_response": response.content,
            "request_messages": messages,
            "stats": response.stats,
            "model": getattr(client, "model", model),
            "wall_seconds": round(time.time() - started, 3)}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", nargs="*", default=list(PILOT_TASKS + V3_TASKS))
    parser.add_argument("--budget", type=int, default=BUDGET)
    parser.add_argument("--max-hypothesis-probes", type=int, default=3)
    parser.add_argument("--hypotheses", type=Path, default=None,
                        help="saved new-protocol model output (dir or JSON map)")
    parser.add_argument("--emit-prompts", type=Path, default=None)
    parser.add_argument("--live", action="store_true",
                        help="call the model for tasks without saved output")
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default=MODEL["model"])
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--num-predict", type=int, default=4096)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--max-relations", type=int, default=12)
    args = parser.parse_args(argv)

    supplied = _read_supplied(args.hypotheses)
    output: Dict[str, Any] = {
        "schema": "mace-semantic-relation-discovery-v1",
        "budget_per_input": args.budget,
        "tasks": {},
    }
    prompts: Dict[str, str] = {}

    for task_id in args.tasks:
        if task_id in PILOT_TASKS:
            context = pilot_context(task_id)
            graph_ops = context["graph_ops"]
            index = context["index"]
            default_file = "<program>"
            target_line = context["task"]["program"]["target_A"]["line"]
            prompt = build_prompt(
                task_id, context["task"]["program"]["source"],
                context["task"]["program"]["target_A"],
                ["<program>"], context["task"]["input_domain"], graph_ops,
                observable=json.dumps(context["task"].get("observable_behavior"),
                                      ensure_ascii=False),
                max_relations=args.max_relations)
            excluded = [target_line]
            arm_runner = lambda universe, hyp: run_pilot_arm(
                context, universe=universe, hypotheses=hyp,
                budget=args.budget,
                max_hypothesis_probes=args.max_hypothesis_probes)
            recorded = None
        else:
            parts = v3_prompt_parts(task_id)
            context = None
            graph_ops = parts["graph_ops"]
            index = None
            default_file = v3_default_file(parts["task"])
            target_line = int(parts["task"]["target_operation"]["line"])
            prompt = build_prompt(
                task_id, parts["source"], parts["task"]["target_operation"],
                parts["files"], parts["input_domain"], graph_ops,
                observable=parts["observable"],
                max_relations=args.max_relations,
                line_offset=parts["line_offset"])
            excluded = [target_line]
            arm_runner = lambda universe, hyp: run_v3_arm(
                task_id, universe_ops=universe, hypotheses=hyp,
                budget=args.budget,
                max_hypothesis_probes=args.max_hypothesis_probes,
                prefix=f"sem_{task_id[:24]}")
            recorded = {"A_graph": recorded_v3_arm(task_id, "graph"),
                        "B_old_qwen": recorded_v3_arm(task_id, "full_mace")}
        prompts[task_id] = prompt

        # ---- model output for C ------------------------------------------
        content = _new_content(task_id, supplied)
        live_record = None
        if content is None and args.live:
            live_record = _call_live(prompt, args.endpoint, args.model,
                                     num_ctx=args.num_ctx,
                                     num_predict=args.num_predict)
            content = live_record["raw_response"]

        if context is not None:
            parse_index = index
            style = "pilot"
        else:
            parse_index = v3_indexes(parts["task"], graph_ops)[default_file]
            style = "v3"

        parsed = (parse_semantic_hypotheses(
            content, parse_index, graph_ops, style=style,
            exclude_lines=excluded,
            max_relations=args.max_relations)
            if content else {"format": "not_run", "relations": [],
                             "rejected": [], "operations": []})

        # Universe construction: U_graph / U_qwen / U_union.
        raw_proposals = [proposal for relation in parsed.get("relations", [])
                         for proposal in relation.get("proposals", [])]
        universes = build_universes(graph_ops, raw_proposals, parse_index,
                                    style=style, exclude_lines=excluded)
        u_graph = universes["U_graph"]
        if context is not None:
            verifier = context["verifier"]
            executable_ids = {
                op["id"] for op in universes["U_union"]
                if verifier.op_for_line(op["first_line"]) is not None}
            u_union = [op for op in universes["U_union"]
                       if op["id"] in executable_ids]
            unexecutable = [op["id"] for op in universes["U_union"]
                            if op["id"] not in executable_ids]
        else:
            u_union = universes["U_union"]
            unexecutable = []
        executable_ids = {op["id"] for op in u_union}
        graph_ids = {op["id"] for op in u_graph}
        role_hyp = relations_to_role_hypotheses(
            parsed.get("relations", []), executable_ops=executable_ids)
        role_hyp_graph = relations_to_role_hypotheses(
            parsed.get("relations", []), executable_ops=graph_ids)

        arms: Dict[str, Any] = {}
        summaries: Dict[str, Any] = {}
        if recorded:
            arms.update(recorded)
        else:
            arms["A_graph"] = arm_runner(u_graph, None)

        legacy = _legacy_content(task_id) if context is not None else None
        legacy_info: Optional[Dict[str, Any]] = None
        if legacy:
            legacy_parsed = parse_semantic_hypotheses(
                legacy, index, graph_ops, style="pilot",
                exclude_lines=excluded, max_relations=args.max_relations)
            legacy_roles = relations_to_role_hypotheses(
                legacy_parsed.get("relations", []),
                executable_ops=graph_ids)
            arms["B_old_qwen"] = arm_runner(u_graph, legacy_roles)
            legacy_info = {
                "format": legacy_parsed["format"],
                "raw_response": legacy,
                "relations": legacy_parsed.get("relations", []),
                "rejected": legacy_parsed.get("rejected", []),
                "verification": verify_pilot_relations(
                    legacy_parsed.get("relations", []), context),
                "candidate_metrics": pilot_candidate_metrics(
                    [proposal for relation in legacy_parsed.get("relations", [])
                     for proposal in relation.get("proposals", [])], context),
            }

        if parsed["format"] in ("structured", "empty"):
            arms["C_semantic"] = arm_runner(u_union, role_hyp)
            if [op["id"] for op in u_union] != [op["id"] for op in u_graph]:
                arms["C_graph_only"] = arm_runner(u_graph, role_hyp_graph)

        fixture_info: Optional[Dict[str, Any]] = None
        if context is not None:
            fixture = graph_fixture(context["task"])
            fixture_parsed = parse_semantic_hypotheses(
                json.dumps(fixture), index, graph_ops, style="pilot",
                exclude_lines=excluded, max_relations=args.max_relations)
            fixture_roles = relations_to_role_hypotheses(
                fixture_parsed.get("relations", []),
                executable_ops=graph_ids)
            arms["C_fixture"] = arm_runner(u_graph, fixture_roles)
            fixture_info = {
                "source": "graph-derived fixture, not model output",
                "relations": fixture_parsed.get("relations", []),
                "rejected": fixture_parsed.get("rejected", []),
                "verification": verify_pilot_relations(
                    fixture_parsed.get("relations", []), context),
                "candidate_metrics": pilot_candidate_metrics(
                    [proposal for relation in fixture_parsed.get("relations", [])
                     for proposal in relation.get("proposals", [])], context),
            }

        for name, arm in arms.items():
            summaries[name] = summarize(arm)
            summaries[name]["universe"] = arm.get("universe")

        task_output: Dict[str, Any] = {
            "kind": "pilot" if context is not None else "real_v3",
            "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
            "model_output": {
                "format": parsed["format"],
                "source": ("live" if live_record else
                           "saved" if content else "not_run"),
                "raw_response": content,
                "stats": (live_record or {}).get("stats"),
                "model": (live_record or {}).get("model"),
                "wall_seconds": (live_record or {}).get("wall_seconds"),
            },
            "relations": parsed.get("relations", []),
            "rejected_relations": parsed.get("rejected", []),
            "universes": {
                "U_graph": [op["id"] for op in universes["U_graph"]],
                "U_qwen": [op["id"] for op in universes["U_qwen"]],
                "U_union": [op["id"] for op in universes["U_union"]],
                "U_union_executable": [op["id"] for op in u_union],
                "unexecutable": unexecutable,
                "mapped": universes["mapped"],
                "rejected": universes["rejected"],
                "duplicates": universes["duplicates"],
            },
            "role_hypotheses": role_hyp,
            "role_hypotheses_graph_only": role_hyp_graph,
            "arms": arms,
            "summaries": summaries,
        }
        if context is not None:
            task_output["relation_verification"] = verify_pilot_relations(
                parsed.get("relations", []), context)
            task_output["candidate_metrics"] = pilot_candidate_metrics(
                raw_proposals, context)
            task_output["truth"] = pilot_truth(context)
            task_output["legacy_model_output"] = legacy_info
            task_output["fixture_control"] = fixture_info
        output["tasks"][task_id] = _jsonable(task_output)

    if args.emit_prompts:
        args.emit_prompts.mkdir(parents=True, exist_ok=True)
        for task_id, prompt in prompts.items():
            (args.emit_prompts / f"{task_id}.txt").write_text(
                prompt, encoding="utf-8")
        (args.emit_prompts / "prompts.json").write_text(
            json.dumps(prompts, ensure_ascii=False, indent=2), encoding="utf-8")

    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(output, ensure_ascii=False, indent=2,
                                   default=str), encoding="utf-8")
    print(f"[semantic] wrote {args.out}")
    for task_id, data in output["tasks"].items():
        print(f"\n=== {task_id}  U_graph={len(data['universes']['U_graph'])} "
              f"U_qwen={len(data['universes']['U_qwen'])} "
              f"format={data['model_output']['format']}")
        for name, summary in data["summaries"].items():
            print(f"  {name:14s} evals={summary['evaluations']:3d} "
                  f"firstMSMS={summary['first_msms_values']} "
                  f"firstMMBS={summary['first_mmbs_values']} "
                  f"msms={summary['msms_relations']} "
                  f"mmbs={summary['mmbs_relations']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
