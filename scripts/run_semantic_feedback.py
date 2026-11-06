"""MACE semantic feedback v1.

One Qwen discovery call, one causal-verification feedback message, at most one
Qwen correction call, then final verification.  The model never confirms a
relation: every candidate remains a hypothesis until the pilot Verifier or the
v3 causal executor checks it.

The mode is additive.  C0, the old Qwen ordering and the old semantic protocol
are read from historical artifacts; they are not re-run.

Granularity rule: a mapped ``if``/``elif``/loop/try statement is a control
context unless it is already an executable Graph operation (the pilot treats a
whole ``if`` block as one unit).  Control context is quoted to the model but is
never put into a deletable operation set.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from benchmark_pilot import engine
from benchmark_real_v3.config import PROJECTS
from scripts.run_semantic_relation_discovery import (
    KIT, PILOT_TASKS, V3_TASKS, pilot_context, run_pilot_arm, run_v3_arm,
    summarize, v3_prompt_parts, v3_universe,
)
from open_ops.semantic_relations import (
    SourceIndex, extract_json, map_proposal, numbered_source, role_tuples,
)

OUT = KIT / "runs" / "v3_semantic_feedback_v1"
LIVE = KIT / "runs" / "v3_semantic_relations" / "results_live.json"
DIRECT = (KIT / "runs" / "v3_semantic_relations" / "direct_end_to_end"
          / "rescored" / "results.json")
CONTROL_NODE_TYPES = {"If", "For", "AsyncFor", "While", "Try", "TryStar",
                      "With", "AsyncWith", "Match"}
EXECUTABLE_NODE_TYPES = {"Assign", "AnnAssign", "AugAssign", "Expr"}
STATUS_RANK = {"VERIFIED": 5, "SET_CONFIRMED": 5, "INCOMPLETE": 4,
               "UNCONFIRMED_INCOMPLETE": 3, "NOT_CONFIRMED": 2,
               "UNEXECUTABLE": 2, "FALSE": 1, "FORMAT_ERROR": 0,
               "NOT_EXECUTABLE": 1}


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def _op_line(op: Dict[str, Any]) -> str:
    text = str(op.get("code") or op.get("text") or "").splitlines()
    head = text[0].strip() if text else ""
    first = int(op.get("first_line", op.get("line")))
    last = int(op.get("last_line", first))
    return (f"- id={op['id']}  lines={first}-{last}  kind={op.get('kind')}"
            f"  executable=true  `{head}`")


def build_feedback_prompt(task_id: str, source: str, target: Dict[str, Any],
                          files: Sequence[str], input_domain: Dict[str, Any],
                          graph_ops: Sequence[Dict[str, Any]],
                          observable: Optional[str] = None,
                          line_offset: int = 0,
                          max_candidates: int = 8) -> str:
    file_list = ", ".join(f"`{f}`" for f in files)
    args = json.dumps(input_domain.get("args"), ensure_ascii=False)
    cases = json.dumps(input_domain.get("cases"), ensure_ascii=False)
    note = input_domain.get("note")
    note_block = f"\nLegal constraints: {note}" if note else ""
    candidates = "\n".join(_op_line(op) for op in graph_ops) or "(none)"
    return f"""You are analysing a proposed deletion in a Python function.  Use
only the public information below.  A Python exception is an observation.  The
best evidence level is BOUNDED: execution on the declared finite domain, never
a proof.

## Task
{task_id}

## Files
{file_list}

## Program with source line numbers
```text
{numbered_source(source, line_offset)}
```

## Target A
Line {target['line']}: `{str(target.get('text') or target.get('code') or '').strip()}`
Deletion rule: replace exactly this line with `pass` at the same indentation.
Deleting A is **unobservable on an input** when the program's observable
behaviour is the same with A present and with A deleted.

## Legal inputs
Arguments: {args}
Frozen legal cases: {cases}{note_block}

## Observable
{observable or 'the function return value (and raised exception type/message)'}

## Executable operations already found by AST + Graph
{candidates}

An executable operation is a statement the existing intervention can replace
with `pass`.  The list above is executable as a unit.  A bare `if`/`elif`/
`for`/`while`/`try` line that is **not** in this list is control context: you
may quote it in `source_evidence`, but do not put it in an operation set.  If
you cite a line inside a listed multi-line block, cite the listed block, not
its body.  You may propose a new **assignment** operation that is not listed;
give a real file, line and source text, and it must map to a real AST
assignment.  A new control statement is rejected.

## What to return
Two kinds of minimal candidate sets:

- **MSMS candidates**: a minimal non-empty set S of executable operations such
  that, if every other operation is deleted, deleting A is unobservable.  This
  is the set that is kept.
- **MMBS candidates**: a minimal non-empty set D of executable operations such
  that deleting exactly D makes deleting A observable (unmasks it).  This is
  the set that is disabled.

For each candidate give the condition on the arguments under which it holds.
Use only argument names, int/bool constants, comparisons, arithmetic, `and`,
`or`, `not`.  Use `True` if it holds for every legal input.  Do not use `is`,
attribute access, function calls, or `None`.

Return one JSON object:
{{
  "msms_candidates": [
    {{
      "operations": [
        {{"file": "<path from Files>", "line": <int>, "text": "<source text>"}}
      ],
      "condition": "<restricted boolean expression or True>",
      "source_evidence": "<line numbers and why>",
      "rationale": "<one sentence>",
      "hypotheses": ["<what still needs verification>"]
    }}
  ],
  "mmbs_candidates": [ ... same fields ... ],
  "notes": "<optional>"
}}

Return at most {max_candidates} candidates in each list.  Return one JSON
object and no prose outside it.
"""


def build_correction_prompt(initial_prompt: str, previous_output: str,
                            feedback: Sequence[Dict[str, Any]],
                            max_candidates: int = 8) -> str:
    feedback_json = json.dumps(feedback, ensure_ascii=False, indent=2)
    return f"""{initial_prompt}

## Your previous answer
```json
{previous_output}
```

## Causal verification feedback
The verifier executed your candidate sets on the frozen legal inputs.  It did
not reveal a reference answer; it only reports what happened to your own
candidates.  A `false_accept` input satisfies your declared condition but the
declared relation does not hold there.  A `false_reject` input satisfies the
relation but your condition is false there.  `control_context` entries were
removed from the deletable set because they are not executable operations.
```json
{feedback_json}
```

## Revision
Return the full corrected answer in the same JSON schema.  Keep candidates
that already passed unchanged.  Fix the failed conditions or operation sets
using the counterexamples.  Do not add new tasks.  This is the only revision.
Return at most {max_candidates} candidates in each list.
"""


# ---------------------------------------------------------------------------
# Parsing and granular mapping
# ---------------------------------------------------------------------------

def _as_list(value: Any) -> List[Any]:
    return value if isinstance(value, list) else []


def parse_candidates(content: str) -> Dict[str, Any]:
    payload = extract_json(content)
    if payload is None:
        return {"format": "unparseable", "msms": [], "mmbs": [],
                "notes": None, "error": "no JSON object"}
    if not isinstance(payload, dict):
        return {"format": "unparseable", "msms": [], "mmbs": [],
                "notes": None, "error": "JSON is not an object"}
    msms = _as_list(payload.get("msms_candidates")
                    or payload.get("msms") or payload.get("MSMS_candidates"))
    mmbs = _as_list(payload.get("mmbs_candidates")
                    or payload.get("mmbs") or payload.get("MMBS_candidates"))
    return {"format": "structured", "msms": msms, "mmbs": mmbs,
            "notes": payload.get("notes"), "error": None}


def _normalise_condition(value: Any) -> Optional[str]:
    if value is None:
        return None
    if isinstance(value, bool):
        return "True" if value else "False"
    text = str(value).strip()
    if text.lower() == "true":
        return "True"
    if text.lower() == "false":
        return "False"
    return text or None


def _is_control(op: Dict[str, Any]) -> bool:
    return (op.get("node_type") in CONTROL_NODE_TYPES
            or op.get("kind") in {"if", "for", "while", "try", "with",
                                  "match", "block"})


def _is_executable_new(op: Dict[str, Any], style: str,
                       verifier: Any = None) -> bool:
    if style == "pilot" and verifier is not None:
        return verifier.op_for_line(int(op["first_line"])) is not None
    return op.get("node_type") in EXECUTABLE_NODE_TYPES


def map_candidate(candidate: Dict[str, Any], *, role: str,
                  index: SourceIndex, graph_ops: Sequence[Dict[str, Any]],
                  style: str, exclude_lines: Sequence[int],
                  verifier: Any = None) -> Dict[str, Any]:
    raw_ops = candidate.get("operations")
    if not isinstance(raw_ops, list) or not raw_ops:
        return {"role": role, "status": "rejected",
                "reason": "missing operations", "raw": candidate}
    graph_ids = {op["id"] for op in graph_ops}
    mapped: List[Dict[str, Any]] = []
    control: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    unexecutable: List[Dict[str, Any]] = []
    for proposal in raw_ops:
        result = map_proposal(proposal, index, graph_ops, style=style,
                              exclude_lines=exclude_lines)
        if result["status"] != "mapped":
            rejected.append(result)
            continue
        op = dict(result["op"])
        op["in_graph"] = bool(result.get("in_graph"))
        if op["id"] in graph_ids:
            mapped.append(op)
        elif _is_control(op):
            # A new control statement is context, never a deletable operation.
            control.append(op)
        elif _is_executable_new(op, style, verifier):
            mapped.append(op)
        else:
            unexecutable.append(op)
    by_id: Dict[str, Dict[str, Any]] = {}
    for op in mapped:
        by_id[op["id"]] = op
    mapped = list(by_id.values())
    if rejected:
        return {"role": role, "status": "rejected",
                "reason": "operation_mapping_failed",
                "mapping_errors": rejected, "control_context": control,
                "raw": candidate}
    if not mapped:
        return {"role": role, "status": "rejected",
                "reason": "no_executable_operation",
                "mapping_errors": [], "control_context": control,
                "unexecutable": unexecutable, "raw": candidate}
    return {
        "role": role,
        "status": "mapped",
        "ops": mapped,
        "control_context": control,
        "unexecutable": unexecutable,
        "duplicates": len(raw_ops) - len(mapped) - len(control)
                      - len(unexecutable) - len(rejected),
        "condition": _normalise_condition(candidate.get("condition")),
        "source_evidence": candidate.get("source_evidence"),
        "rationale": candidate.get("rationale"),
        "hypotheses": _as_list(candidate.get("hypotheses")),
        "raw": candidate,
    }


def map_candidates(parsed: Dict[str, Any], *, index: SourceIndex,
                   graph_ops: Sequence[Dict[str, Any]], style: str,
                   exclude_lines: Sequence[int],
                   verifier: Any = None) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for role, key in (("msms", "msms"), ("mmbs", "mmbs")):
        for candidate in parsed.get(key) or []:
            if isinstance(candidate, dict):
                out.append(map_candidate(
                    candidate, role=role, index=index, graph_ops=graph_ops,
                    style=style, exclude_lines=exclude_lines,
                    verifier=verifier))
            else:
                out.append({"role": role, "status": "rejected",
                            "reason": "candidate_not_object",
                            "raw": candidate})
    return out


# ---------------------------------------------------------------------------
# Pilot verification
# ---------------------------------------------------------------------------

def _pilot_names(verifier: Any, ops: Sequence[Dict[str, Any]]) -> List[str]:
    names = [verifier.op_for_line(int(op["first_line"])) for op in ops]
    return [name for name in names if name]


def _pick(result: Optional[Dict[str, Any]],
          candidate: Dict[str, Any]) -> Dict[str, Any]:
    if result is None:
        return {"status": "UNVERIFIED", "reason": "no legal witness"}
    return result


def verify_msms(candidate: Dict[str, Any], verifier: Any) -> Dict[str, Any]:
    names = _pilot_names(verifier, candidate.get("ops") or [])
    if len(names) != len(candidate.get("ops") or []):
        return {"status": "UNEXECUTABLE",
                "reason": "operation line is not a declared pilot operation"}
    kind = "independent" if len(names) == 1 else "cooperative"
    cases = [(cid, args) for cid, args in verifier.cases
             if verifier.base_equal.get(cid) and verifier.local_effect.get(cid)]
    best = None
    attempts = 0
    for cid, args in cases:
        attempts += 1
        result = verifier.verify_relation({
            "operations": [{"line": verifier.op_lines[name]} for name in names],
            "kind": kind, "input": args,
            "condition": candidate.get("condition")})
        result["kind"] = kind
        if result.get("status") == "VERIFIED":
            best = result
            break
        if best is None or _quality(result) > _quality(best):
            best = result
    out = _pick(best, candidate)
    out["attempts"] = attempts
    out["names"] = sorted(names)
    return out


def _singleton_mmbs(candidate: Dict[str, Any], verifier: Any) -> Dict[str, Any]:
    names = _pilot_names(verifier, candidate.get("ops") or [])
    if len(names) != 1:
        return {"status": "UNEXECUTABLE",
                "reason": "MMBS singleton requires exactly one pilot operation"}
    name = names[0]
    condition = candidate.get("condition")
    best = None
    for cid, args in verifier.cases:
        if not (verifier.base_equal.get(cid) and verifier.local_effect.get(cid)):
            continue
        out = {"status": "UNVERIFIED", "kind": "mmbs_singleton",
               "operations": [name], "case_id": cid, "input": args,
               "checks": {}}
        out["checks"]["a_has_local_effect"] = bool(verifier.local_effect[cid])
        out["checks"]["original_masks"] = bool(verifier.base_equal[cid])
        out["checks"]["disabling_set_exposes"] = not bool(
            verifier.disabled_equal([name])[cid])
        if not out["checks"]["disabling_set_exposes"]:
            out.update({"status": "FALSE",
                        "reason": "disabling the declared set does not expose A"})
            if best is None or _quality(out) > _quality(best):
                best = out
            continue
        if not isinstance(condition, str) or not condition.strip():
            out["condition"] = {"status": "ABSENT"}
        else:
            out["condition"] = verifier._check_condition(
                condition, "coexisting", frozenset({name}))
            cond = out["condition"]
            if cond.get("status") == "VALID":
                try:
                    witness_value = bool(engine.eval_guard(
                        condition, verifier.arg_names, args))
                except Exception as exc:  # noqa: BLE001
                    cond.update({"status": "INVALID",
                                 "error": f"{type(exc).__name__}: {exc}"})
                else:
                    cond["witness_value"] = witness_value
                    if not witness_value:
                        out.update({"status": "FALSE",
                                    "reason": "condition is false on the witness input"})
                        if best is None or _quality(out) > _quality(best):
                            best = out
                        continue
        cond = out.get("condition") or {}
        if cond.get("status") != "VALID":
            out.update({"status": "INCOMPLETE",
                        "reason": "condition is absent or not in the allowed language"})
        elif not cond.get("sound"):
            out.update({"status": "FALSE",
                        "reason": "condition is unsound"})
        elif not cond.get("exact"):
            out.update({"status": "INCOMPLETE",
                        "reason": "condition is sound but incomplete"})
        else:
            out.update({"status": "VERIFIED", "reason": "candidate verified"})
        if best is None or _quality(out) > _quality(best):
            best = out
    return best or {"status": "UNVERIFIED", "reason": "no legal witness"}


def verify_mmbs(candidate: Dict[str, Any], verifier: Any) -> Dict[str, Any]:
    ops = candidate.get("ops") or []
    if len(ops) == 1:
        return _singleton_mmbs(candidate, verifier)
    names = _pilot_names(verifier, ops)
    if len(names) != len(ops):
        return {"status": "UNEXECUTABLE",
                "reason": "operation line is not a declared pilot operation"}
    cases = [(cid, args) for cid, args in verifier.cases
             if verifier.base_equal.get(cid) and verifier.local_effect.get(cid)]
    best = None
    attempts = 0
    for cid, args in cases:
        attempts += 1
        result = verifier.verify_relation({
            "operations": [{"line": verifier.op_lines[name]} for name in names],
            "kind": "coexisting", "input": args,
            "condition": candidate.get("condition")})
        result["kind"] = "coexisting"
        if result.get("status") == "VERIFIED":
            best = result
            break
        if best is None or _quality(result) > _quality(best):
            best = result
    out = _pick(best, candidate)
    out["attempts"] = attempts
    out["names"] = sorted(names)
    return out


def _quality(result: Dict[str, Any]) -> tuple:
    return (STATUS_RANK.get(result.get("status"), -1),
            1 if result.get("condition") else 0,
            len(result.get("checks") or {}))


def verify_pilot_candidate(candidate: Dict[str, Any], verifier: Any) -> Dict[str, Any]:
    if candidate.get("role") == "msms":
        return verify_msms(candidate, verifier)
    return verify_mmbs(candidate, verifier)


def pilot_feedback_entry(candidate: Dict[str, Any], verifier: Any) -> Dict[str, Any]:
    base = {"role": candidate["role"],
            "operations": [op["id"] for op in candidate.get("ops") or []],
            "status": candidate.get("verification", {}).get("status"),
            "reason": candidate.get("verification", {}).get("reason"),
            "control_context": [{"id": op["id"], "line": op["first_line"],
                                 "text": str(op.get("code") or "").splitlines()[0]}
                                for op in candidate.get("control_context") or []],
            "mapping_errors": candidate.get("mapping_errors") or []}
    if candidate.get("status") != "mapped":
        return base
    cond = candidate["verification"].get("condition")
    if isinstance(cond, dict):
        entry = {k: cond.get(k) for k in
                 ("status", "exact", "sound", "complete",
                  "false_accept", "false_reject")}
        payload = []
        names = candidate["verification"].get("names") or []
        kind = ("independent" if candidate["role"] == "msms" and len(names) == 1
                else "cooperative" if candidate["role"] == "msms"
                else "coexisting")
        if names:
            actual = verifier.actual_relation_holds(kind, frozenset(names))
            for group in ("false_accept", "false_reject"):
                for cid in cond.get(group, []) or []:
                    args = next((a for c, a in verifier.cases if c == cid), None)
                    payload.append({
                        "case_id": cid, "kind": group, "args": args,
                        "declared_condition_value": group == "false_accept",
                        "actual_relation_holds": bool(actual.get(cid)),
                    })
        entry["failed_inputs"] = payload
        base["condition"] = entry
    return base


# ---------------------------------------------------------------------------
# Real-task verification
# ---------------------------------------------------------------------------

def _set_key(ids: Iterable[str]) -> Tuple[str, ...]:
    return tuple(sorted(set(ids)))


def arm_sets(arm: Dict[str, Any], role: str) -> set:
    key = "msms_ids" if role == "msms" else "mmbs_ids"
    out = set()
    for row in arm.get("inputs") or []:
        if not row.get("searched"):
            continue
        for item in row.get(key) or []:
            out.add(_set_key(item))
    return out


def verify_real_candidate(candidate: Dict[str, Any], arm: Dict[str, Any],
                          role: str) -> Dict[str, Any]:
    if candidate.get("status") != "mapped":
        return {"status": "UNEXECUTABLE",
                "reason": candidate.get("reason")}
    ids = _set_key(op["id"] for op in candidate.get("ops") or [])
    sets = arm_sets(arm, role)
    confirmed_inputs = []
    searched = 0
    incomplete = 0
    for row in arm.get("inputs") or []:
        if not row.get("searched"):
            continue
        searched += 1
        if not row.get("complete"):
            incomplete += 1
        key = "msms_ids" if role == "msms" else "mmbs_ids"
        if ids in {_set_key(x) for x in row.get(key) or []}:
            confirmed_inputs.append(row.get("input"))
    if confirmed_inputs:
        status = "SET_CONFIRMED"
    elif incomplete:
        status = "UNCONFIRMED_INCOMPLETE"
    else:
        status = "NOT_CONFIRMED"
    return {"status": status, "ids": list(ids),
            "confirmed_inputs": confirmed_inputs,
            "searched_inputs": searched,
            "incomplete_inputs": incomplete}


def real_feedback_entry(candidate: Dict[str, Any]) -> Dict[str, Any]:
    verification = candidate.get("verification") or {}
    return {
        "role": candidate["role"],
        "operations": verification.get("ids")
                      or [op["id"] for op in candidate.get("ops") or []],
        "status": verification.get("status"),
        "reason": verification.get("reason"),
        "confirmed_inputs": verification.get("confirmed_inputs"),
        "searched_inputs": verification.get("searched_inputs"),
        "incomplete_inputs": verification.get("incomplete_inputs"),
        "control_context": [{"id": op["id"], "line": op["first_line"],
                             "text": str(op.get("code") or "").splitlines()[0]}
                            for op in candidate.get("control_context") or []],
        "mapping_errors": candidate.get("mapping_errors") or [],
        "new_operations": [op["id"] for op in candidate.get("ops") or []
                           if not op.get("in_graph")],
    }


# ---------------------------------------------------------------------------
# Hypotheses and universes
# ---------------------------------------------------------------------------

def candidate_hypotheses(candidates: Sequence[Dict[str, Any]],
                         allowed: Optional[Iterable[str]] = None
                         ) -> Dict[str, Any]:
    allowed_set = set(allowed) if allowed is not None else None
    out = {"msms": [], "mmbs": []}
    for candidate in candidates:
        if candidate.get("status") != "mapped":
            continue
        ids = tuple(_set_key(op["id"] for op in candidate.get("ops") or []))
        if allowed_set is not None and any(op not in allowed_set for op in ids):
            continue
        out[candidate["role"]].append({
            "ops": ids,
            "kind": ("independent" if candidate["role"] == "msms"
                     and len(ids) == 1 else
                     "cooperative" if candidate["role"] == "msms"
                     else "coexisting"),
            "condition": candidate.get("condition"),
            "status": "HYPOTHESIS",
        })
    return out


def universes_from(candidates: Sequence[Dict[str, Any]],
                   graph_ops: Sequence[Dict[str, Any]],
                   executable_ids: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    graph_ids = {op["id"] for op in graph_ops}
    new: Dict[str, Dict[str, Any]] = {}
    for candidate in candidates:
        for op in candidate.get("ops") or []:
            if op["id"] not in graph_ids:
                new.setdefault(op["id"], op)
    union = list(graph_ops) + [new[key] for key in sorted(new)]
    if executable_ids is not None:
        allowed = set(executable_ids)
        union = [op for op in union if op["id"] in allowed]
    return {"U_graph": list(graph_ops), "U_qwen": [new[k] for k in sorted(new)],
            "U_union": union}


# ---------------------------------------------------------------------------
# Model call
# ---------------------------------------------------------------------------

def call_model(messages: List[Dict[str, str]], args: argparse.Namespace,
               purpose: str) -> Dict[str, Any]:
    from mace.qwen import QwenClient
    client = QwenClient(provider="ollama", model=args.model,
                        endpoint=args.endpoint, num_ctx=args.num_ctx,
                        num_predict=args.num_predict, temperature=0.0,
                        seed=42, timeout=args.timeout, retries=0)
    started = time.time()
    try:
        response = client.chat(messages, purpose=purpose, json_mode=True)
        return {"raw_response": response.content, "stats": response.stats,
                "model": getattr(client, "model", args.model),
                "wall_seconds": round(time.time() - started, 3),
                "messages": messages, "error": None}
    except Exception as exc:  # noqa: BLE001 - record, never retry
        return {"raw_response": "", "stats": None, "model": args.model,
                "wall_seconds": round(time.time() - started, 3),
                "messages": messages,
                "error": f"{type(exc).__name__}: {exc}"}


# ---------------------------------------------------------------------------
# Per-task run
# ---------------------------------------------------------------------------

def _task_setup(task_id: str) -> Dict[str, Any]:
    if task_id in PILOT_TASKS:
        context = pilot_context(task_id)
        task = context["task"]
        target = task["program"]["target_A"]
        source = task["program"]["source"]
        input_domain = task["input_domain"]
        files = ["<program>"]
        observable = json.dumps(task.get("observable_behavior"),
                                ensure_ascii=False)
        line_offset = 0
        index = context["index"]
        graph_ops = context["graph_ops"]
        style = "pilot"
        verifier = context["verifier"]
        return {"kind": "pilot", "context": context, "task": task,
                "target": target, "source": source,
                "input_domain": input_domain, "files": files,
                "observable": observable, "line_offset": line_offset,
                "index": index, "graph_ops": graph_ops, "style": style,
                "verifier": verifier}
    parts = v3_prompt_parts(task_id)
    task = parts["task"]
    target = task["target_operation"]
    index = SourceIndex.from_path(
        target["file"], PROJECTS[task["project_id"]]["root"])
    return {"kind": "real_v3", "context": None, "task": task,
            "target": target, "source": parts["source"],
            "input_domain": parts["input_domain"], "files": parts["files"],
            "observable": parts["observable"],
            "line_offset": parts["line_offset"], "index": index,
            "graph_ops": parts["graph_ops"], "style": "v3",
            "verifier": None}


def _evaluate_candidates(candidates: Sequence[Dict[str, Any]],
                         setup: Dict[str, Any],
                         arm: Optional[Dict[str, Any]] = None) -> None:
    for candidate in candidates:
        if setup["kind"] == "pilot":
            if candidate.get("status") != "mapped":
                candidate["verification"] = {
                    "status": "UNEXECUTABLE",
                    "reason": candidate.get("reason")}
            else:
                candidate["verification"] = verify_pilot_candidate(
                    candidate, setup["verifier"])
        elif arm is not None:
            candidate["verification"] = verify_real_candidate(
                candidate, arm, candidate["role"])
        else:
            candidate["verification"] = {
                "status": "UNEXECUTABLE",
                "reason": "no executable arm for this task"}


def _feedback_for(candidates: Sequence[Dict[str, Any]],
                  setup: Dict[str, Any]) -> List[Dict[str, Any]]:
    feedback = []
    for candidate in candidates:
        if setup["kind"] == "pilot":
            if candidate.get("verification", {}).get("status") != "VERIFIED":
                feedback.append(pilot_feedback_entry(candidate,
                                                     setup["verifier"]))
        else:
            status = candidate.get("verification", {}).get("status")
            if status != "SET_CONFIRMED":
                feedback.append(real_feedback_entry(candidate))
    return feedback


def _run_arm(task_id: str, setup: Dict[str, Any], candidates: Sequence[Dict[str, Any]],
             universe: Sequence[Dict[str, Any]], label: str) -> Dict[str, Any]:
    hypotheses = candidate_hypotheses(
        candidates, allowed={op["id"] for op in universe})
    if setup["kind"] == "pilot":
        arm = run_pilot_arm(setup["context"], universe=universe,
                            hypotheses=hypotheses, budget=16,
                            max_hypothesis_probes=3)
    else:
        arm = run_v3_arm(task_id, universe_ops=universe,
                         hypotheses=hypotheses, budget=16,
                         max_hypothesis_probes=3,
                         prefix=f"fb_{label}_{task_id[:18]}")
    return arm


def _arm_summary(arm: Dict[str, Any]) -> Dict[str, Any]:
    summary = summarize(arm)
    summary["universe"] = arm.get("universe")
    return summary


def run_task(task_id: str, args: argparse.Namespace,
             live: Dict[str, Any], direct: Dict[str, Any]) -> Dict[str, Any]:
    setup = _task_setup(task_id)
    prompt = build_feedback_prompt(
        task_id, setup["source"], setup["target"], setup["files"],
        setup["input_domain"], setup["graph_ops"],
        observable=setup["observable"], line_offset=setup["line_offset"],
        max_candidates=args.max_candidates)
    system = {"role": "system", "content":
              "You analyse Python masking relations. Return one JSON object "
              "only. Every operation must cite a real file, line and text. "
              "Never put a control statement in a deletable operation set."}
    messages = [system, {"role": "user", "content": prompt}]

    initial = call_model(messages, args, "semantic_feedback_initial")
    parsed_initial = parse_candidates(initial["raw_response"])
    candidates_initial = map_candidates(
        parsed_initial, index=setup["index"], graph_ops=setup["graph_ops"],
        style=setup["style"],
        exclude_lines=[int(setup["target"]["line"])],
        verifier=setup["verifier"])

    first_arm = None
    if setup["kind"] == "real_v3":
        # First-pass causal check on U_union, used only for feedback.
        union0 = universes_from(candidates_initial, setup["graph_ops"])["U_union"]
        if union0:
            first_arm = _run_arm(task_id, setup, candidates_initial, union0,
                                 "first")
            _evaluate_candidates(candidates_initial, setup, first_arm)
        else:
            _evaluate_candidates(candidates_initial, setup)
    else:
        _evaluate_candidates(candidates_initial, setup)

    feedback = _feedback_for(candidates_initial, setup)
    correction = None
    candidates_final = candidates_initial
    parsed_final = parsed_initial
    bad_keys = {
        (candidate["role"],
         tuple(sorted(op["id"] for op in candidate.get("ops") or [])))
        for candidate in candidates_initial
        if candidate.get("verification", {}).get("status") not in
        ("VERIFIED", "SET_CONFIRMED")}
    if feedback and args.allow_correction:
        correction_prompt = build_correction_prompt(
            prompt, initial["raw_response"], feedback,
            max_candidates=args.max_candidates)
        correction_messages = [
            system, {"role": "user", "content": correction_prompt}]
        correction = call_model(correction_messages, args,
                                "semantic_feedback_correction")
        parsed_final = parse_candidates(correction["raw_response"])
        candidates_final = map_candidates(
            parsed_final, index=setup["index"], graph_ops=setup["graph_ops"],
            style=setup["style"],
            exclude_lines=[int(setup["target"]["line"])],
            verifier=setup["verifier"])

    universes = universes_from(candidates_final, setup["graph_ops"])
    u_graph = universes["U_graph"]
    u_union = universes["U_union"]
    graph_ids = {op["id"] for op in u_graph}
    union_ids = {op["id"] for op in u_union}

    if setup["kind"] == "real_v3":
        if correction is None and first_arm is not None:
            union_arm = first_arm
        else:
            union_arm = (_run_arm(task_id, setup, candidates_final, u_union,
                                  "final_union") if u_union else None)
        graph_arm = (_run_arm(task_id, setup, candidates_final, u_graph,
                              "final_graph") if u_graph else None)
        _evaluate_candidates(candidates_final, setup, union_arm)
        # A graph-only view: the same candidate set is executable only if all
        # of its operations are in U_graph.
        for candidate in candidates_final:
            if candidate.get("status") != "mapped":
                continue
            ids = {op["id"] for op in candidate.get("ops") or []}
            if ids <= graph_ids:
                candidate["verification_graph"] = verify_real_candidate(
                    candidate, graph_arm, candidate["role"]) \
                    if graph_arm is not None else {
                        "status": "UNEXECUTABLE", "reason": "no graph arm"}
            else:
                candidate["verification_graph"] = {
                    "status": "UNEXECUTABLE",
                    "reason": "candidate contains an operation outside U_graph",
                    "ids": sorted(ids)}
    else:
        # Pilot arms: the verifier does not depend on the search universe, but
        # the arms show the probe-order effect under each U.
        graph_arm = _run_arm(task_id, setup, candidates_final, u_graph,
                             "final_graph")
        union_arm = (_run_arm(task_id, setup, candidates_final, u_union,
                              "final_union")
                     if union_ids != graph_ids else graph_arm)
        _evaluate_candidates(candidates_final, setup)
        for candidate in candidates_final:
            candidate["verification_graph"] = candidate.get("verification")

    first_feedback = feedback
    final_feedback = _feedback_for(candidates_final, setup)
    fixed = 0
    still_bad = 0
    for candidate in candidates_final:
        key = (candidate["role"],
               tuple(sorted(op["id"] for op in candidate.get("ops") or [])))
        if candidate.get("verification", {}).get("status") in (
                "VERIFIED", "SET_CONFIRMED"):
            if key in bad_keys:
                fixed += 1
        else:
            still_bad += 1

    task_live = live.get("tasks", {}).get(task_id, {})
    task_direct = direct.get("tasks", {}).get(task_id, {})
    return {
        "task_id": task_id,
        "kind": setup["kind"],
        "prompt_initial": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "initial": {
            "request": messages,
            "model": initial,
            "parsed": parsed_initial,
            "candidates": candidates_initial,
            "arm": _arm_summary(first_arm) if first_arm else None,
            "feedback": first_feedback,
        },
        "correction": ({
            "request": correction["messages"],
            "model": correction,
            "parsed": parsed_final,
            "candidates": candidates_final,
            "feedback": final_feedback,
        } if correction is not None else None),
        "candidates_final": candidates_final,
        "universes": {
            "U_graph": [op["id"] for op in u_graph],
            "U_qwen": [op["id"] for op in universes["U_qwen"]],
            "U_union": [op["id"] for op in u_union],
            "control_context": [
                {"id": op["id"], "line": op["first_line"],
                 "text": str(op.get("code") or "").splitlines()[0]}
                for candidate in candidates_final
                for op in candidate.get("control_context") or []],
            "rejected": [
                {"role": c["role"], "status": c["status"],
                 "reason": c.get("reason"),
                 "mapping_errors": c.get("mapping_errors")}
                for c in candidates_final if c.get("status") != "mapped"],
        },
        "arms": {
            "D_graph": _arm_summary(graph_arm) if graph_arm else None,
            "D_union": _arm_summary(union_arm) if union_arm else None,
        },
        "baselines": {
            "source": str(LIVE),
            "A_graph": (task_live.get("summaries") or {}).get("A_graph"),
            "B_old_qwen": (task_live.get("summaries") or {}).get("B_old_qwen"),
            "C_semantic": (task_live.get("summaries") or {}).get("C_semantic"),
            "direct_qwen": task_direct.get("summary"),
        },
        "metrics": {
            "initial_candidates": len(candidates_initial),
            "final_candidates": len(candidates_final),
            "initial_verified": sum(
                1 for c in candidates_initial
                if c.get("verification", {}).get("status") in
                ("VERIFIED", "SET_CONFIRMED")),
            "final_verified": sum(
                1 for c in candidates_final
                if c.get("verification", {}).get("status") in
                ("VERIFIED", "SET_CONFIRMED")),
            "initial_bad": len(first_feedback),
            "final_bad": len(final_feedback),
            "correction_used": correction is not None,
            "fixed_after_feedback": fixed,
            "still_bad": still_bad,
        },
    }


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", nargs="*",
                        default=list(PILOT_TASKS + V3_TASKS))
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen2.5-coder:32b")
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--num-predict", type=int, default=4096)
    parser.add_argument("--timeout", type=int, default=900)
    parser.add_argument("--max-candidates", type=int, default=8)
    parser.add_argument("--allow-correction", action="store_true", default=True)
    parser.add_argument("--out", type=Path, default=OUT / "results.json")
    args = parser.parse_args(argv)

    live = json.loads(LIVE.read_text(encoding="utf-8"))
    direct = (json.loads(DIRECT.read_text(encoding="utf-8"))
              if DIRECT.exists() else {"tasks": {}})
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "requests").mkdir(exist_ok=True)
    (OUT / "raw").mkdir(exist_ok=True)
    (OUT / "tasks").mkdir(exist_ok=True)

    started = time.time()
    tasks: Dict[str, Any] = {}
    for task_id in args.tasks:
        record = run_task(task_id, args, live, direct)
        tasks[task_id] = record
        for label in ("initial", "correction"):
            call = record.get(label)
            if not call:
                continue
            model = call["model"]
            (OUT / "requests" / f"{task_id}_{label}.json").write_text(
                json.dumps({"task_id": task_id, "label": label,
                            "messages": model["messages"],
                            "model": args.model,
                            "options": {"temperature": 0.0, "seed": 42,
                                        "num_ctx": args.num_ctx,
                                        "num_predict": args.num_predict,
                                        "retries": 0}},
                           ensure_ascii=False, indent=2), encoding="utf-8")
            (OUT / "raw" / f"{task_id}_{label}.json").write_text(
                json.dumps({"task_id": task_id, "label": label,
                            "raw_response": model["raw_response"],
                            "error": model.get("error")},
                           ensure_ascii=False, indent=2), encoding="utf-8")
        (OUT / "tasks" / f"{task_id}.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[feedback] {task_id} {json.dumps(record['metrics'], ensure_ascii=False)}")

    payload = {
        "schema": "mace-semantic-feedback-v1",
        "model": args.model,
        "options": {"temperature": 0.0, "seed": 42,
                    "num_ctx": args.num_ctx,
                    "num_predict": args.num_predict, "retries": 0},
        "baseline_source": str(LIVE),
        "direct_source": str(DIRECT),
        "elapsed_seconds": round(time.time() - started, 3),
        "tasks": tasks,
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2,
                                   default=str), encoding="utf-8")
    print(f"[feedback] wrote {args.out} in {payload['elapsed_seconds']}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
