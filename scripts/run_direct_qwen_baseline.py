"""Direct Qwen end-to-end baseline on the same four tasks.

This is the "pure Qwen" condition: the model reads only public information,
gets no Graph candidate list, no relation-kind taxonomy, no execution
feedback, and no opportunity to search.  Its raw relations are scored as-is.

Pilot tasks (ctrl_02, ctrl_03) are scored by the frozen pilot Verifier on
every legal input.  Real v3 tasks have no frozen condition verifier, so only
the operation set is checked against the MSMS/MMBS sets that the Graph-only
arm already confirmed causally; their conditions are NOT_EVALUATED.

Nothing here changes the benchmark, the HIDDEN scorer, or the existing
results.  One model call per task, retries disabled.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

from benchmark_real_v3.config import PROJECTS
from scripts.run_semantic_relation_discovery import (
    KIT, PILOT_TASKS, V3_TASKS, pilot_context, v3_prompt_parts, v3_universe,
)
from open_ops.semantic_relations import SourceIndex, map_proposal, numbered_source

OUT = KIT / "runs" / "v3_semantic_relations" / "direct_end_to_end"
RESULTS_LIVE = KIT / "runs" / "v3_semantic_relations" / "results_live.json"
BUDGET = 16
RANK = {"VERIFIED": 4, "INCOMPLETE": 3, "UNVERIFIED": 2,
        "FALSE": 1, "FORMAT_ERROR": 0}


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def direct_prompt(task_id: str, source: str, target: Dict[str, Any],
                  files: Sequence[str], input_domain: Dict[str, Any],
                  observable: Optional[str] = None,
                  max_relations: int = 12,
                  line_offset: int = 0) -> str:
    file_list = ", ".join(f"`{f}`" for f in files)
    args = json.dumps(input_domain.get("args"), ensure_ascii=False)
    cases = json.dumps(input_domain.get("cases"), ensure_ascii=False)
    note = input_domain.get("note")
    note_block = f"\nLegal constraints: {note}" if note else ""
    return f"""You are analysing a proposed deletion in a Python function. Use only
the public information below. A Python exception is an observation. The best
evidence level is BOUNDED: execution on the declared finite domain, never a proof.

## Task
{task_id}

## Files
{file_list}

## Program with source line numbers
```text
{numbered_source(source, line_offset)}
```

## Target A
Line {target['line']}: `{str(target.get('text', '')).strip()}`
Deletion rule: replace exactly this line with `pass` at the same indentation.
Deleting A is **unobservable on an input** when the program's observable
behaviour is the same with A present and with A deleted.

## Legal inputs
Arguments: {args}
Frozen legal cases: {cases}{note_block}

## Observable
{observable or 'the function return value (and raised exception type/message)'}

## Question
Find every set of one or more other statements such that, on at least one
legal input, deleting those statements together makes the deletion of A
unobservable.  Each set must be minimal: no proper non-empty subset of it
has the same effect.  Different sets may be alternative paths.

For each set:
- list the exact statements with their 1-based starting line and source text;
- state the condition on the arguments under which the relation holds, using
  only argument names, int/bool constants, comparisons, arithmetic, `and`,
  `or`, `not`.  If it holds for every legal input, write `true`;
- give a one-sentence rationale.

## Required JSON
{{
  "relations": [
    {{
      "operations": [
        {{"file": "<path from Files>", "line": <int>, "text": "<source text>"}}
      ],
      "condition": "<restricted boolean expression or null>",
      "rationale": "<one sentence>"
    }}
  ]
}}

Return at most {max_relations} different relations.  Return one JSON object
and no prose outside it.
"""


# ---------------------------------------------------------------------------
# Parsing and mapping
# ---------------------------------------------------------------------------

def _strip_fences(text: str) -> str:
    text = text.strip()
    if text.startswith("```"):
        lines = text.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip() == "```":
            lines = lines[:-1]
        text = "\n".join(lines)
    return text.strip()


def parse_relations(raw: str) -> Tuple[List[Dict[str, Any]], Optional[str]]:
    text = _strip_fences(raw)
    if not text:
        return [], "empty response"
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return [], "no JSON object"
    try:
        obj = json.loads(text[start:end + 1])
    except ValueError as exc:
        return [], f"JSON error: {exc}"
    relations = obj.get("relations") if isinstance(obj, dict) else obj
    if not isinstance(relations, list):
        return [], "relations is not a list"
    return [r for r in relations if isinstance(r, dict)], None


def map_relation(relation: Dict[str, Any], indexes: Dict[str, SourceIndex],
                 graph_ops: Sequence[Dict[str, Any]], style: str,
                 exclude_lines: Sequence[int]) -> Dict[str, Any]:
    raw_ops = relation.get("operations")
    if not isinstance(raw_ops, list) or not raw_ops:
        return {"status": "rejected", "reason": "missing operations",
                "relation": relation}
    mapped: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    for proposal in raw_ops:
        file = None
        if isinstance(proposal, dict):
            file = proposal.get("file")
        index = indexes.get(file) if file in indexes else None
        if index is None:
            # The prompt names one target file; accept a missing file field.
            if len(indexes) == 1:
                index = next(iter(indexes.values()))
            else:
                rejected.append({"status": "rejected", "reason": "unknown_file",
                                 "proposal": proposal})
                continue
        result = map_proposal(proposal, index, graph_ops, style=style,
                              exclude_lines=exclude_lines)
        if result.get("status") != "mapped":
            rejected.append(result)
        else:
            mapped.append(result)
    if rejected or not mapped:
        return {"status": "rejected", "reason": "unmapped operation",
                "rejected": rejected, "relation": relation}
    by_id: Dict[str, Dict[str, Any]] = {}
    for item in mapped:
        by_id[item["op"]["id"]] = item["op"]
    # An operation can be named twice when the model cites both an ``if`` and
    # its body; the mapper folds the body into the enclosing statement.  That
    # is the same operation, not a malformed relation.
    return {"status": "mapped", "ops": list(by_id.values()),
            "duplicates": len(mapped) - len(by_id),
            "in_graph": all(item.get("in_graph") for item in mapped),
            "relation": relation}


# ---------------------------------------------------------------------------
# Pilot scoring
# ---------------------------------------------------------------------------

def _quality(result: Dict[str, Any]) -> tuple:
    return (RANK.get(result.get("status"), -1),
            1 if result.get("condition") else 0,
            len(result.get("checks") or {}))


def verify_pilot(relation: Dict[str, Any], ops: Sequence[Dict[str, Any]],
                 context: Dict[str, Any]) -> Dict[str, Any]:
    verifier = context["verifier"]
    names = [verifier.op_for_line(int(op["first_line"])) for op in ops]
    if any(name is None for name in names):
        return {"status": "UNVERIFIED", "reason": "line is not a declared operation",
                "names": names}
    kinds = ["independent"] if len(ops) == 1 else ["cooperative", "coexisting"]
    candidates = [(cid, args) for cid, args in verifier.cases
                  if verifier.base_equal[cid] and verifier.local_effect[cid]]
    best: Optional[Dict[str, Any]] = None
    for kind in kinds:
        for cid, args in candidates:
            submitted = {
                "operations": [{"line": int(op["first_line"])} for op in ops],
                "kind": kind,
                "input": args,
                "condition": relation.get("condition"),
            }
            result = verifier.verify_relation(submitted)
            result["kind"] = kind
            result["relation"] = relation
            if result.get("status") == "VERIFIED":
                return result
            if best is None or _quality(result) > _quality(best):
                best = result
    return best or {"status": "UNVERIFIED", "reason": "no legal witness"}


def true_sets(context: Dict[str, Any]) -> Tuple[set, set]:
    """Return (minimal masking sets, minimal exposing sets) from attribution."""
    absorber = set()
    coexisting = set()
    for case in context["attribution"].get("per_case", []):
        for item in case.get("absorber_sets", []):
            absorber.add(frozenset(item))
        for item in case.get("coexisting_unmasking_sets", []):
            coexisting.add(frozenset(item))
    return absorber, coexisting


# ---------------------------------------------------------------------------
# Real-task scoring
# ---------------------------------------------------------------------------

def _normalise_sets(value: Any) -> List[frozenset]:
    out = []
    if isinstance(value, list):
        for item in value:
            if isinstance(item, list):
                out.append(frozenset(str(x) for x in item))
    return out


def inner_ops(ops: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Drop an enclosing statement when the same relation also names its body.

    This is a post-hoc granularity normalisation, not the primary score: the
    model literally proposed a set containing a control statement.  Keeping the
    innermost statement recovers the assignment the rationale talks about.
    """
    def contains(outer: Dict[str, Any], inner: Dict[str, Any]) -> bool:
        outer_first = int(outer["first_line"])
        outer_last = int(outer.get("last_line", outer_first))
        inner_first = int(inner["first_line"])
        inner_last = int(inner.get("last_line", inner_first))
        return (outer.get("file") == inner.get("file")
                and outer_first <= inner_first and inner_last <= outer_last
                and (outer_first, outer_last) != (inner_first, inner_last))

    kept = [op for op in ops
            if not any(contains(op, other) for other in ops if other is not op)]
    return kept or list(ops)


def check_real_set(task_id: str, ops: Sequence[Dict[str, Any]],
                   live: Dict[str, Any]) -> Dict[str, Any]:
    universe = {op["id"] for op in v3_universe(task_id)}
    ids = frozenset(op["id"] for op in ops)
    new_ops = sorted(ids - universe)
    arm = live["tasks"][task_id]["arms"]["A_graph"]["inputs"]
    msms_inputs: List[Any] = []
    mmbs_inputs: List[Any] = []
    incomplete_inputs: List[Any] = []
    for row in arm:
        if not row.get("searched"):
            continue
        label = row.get("case_id") or json.dumps(row.get("input"),
                                                 ensure_ascii=False,
                                                 sort_keys=True)
        if ids in _normalise_sets(row.get("msms_ids")):
            msms_inputs.append(label)
        if ids in _normalise_sets(row.get("mmbs_ids")):
            mmbs_inputs.append(label)
        if not row.get("complete"):
            incomplete_inputs.append(label)
    if new_ops:
        status = "NEW_OP"
    elif msms_inputs or mmbs_inputs:
        status = "SET_CONFIRMED"
    else:
        status = "NOT_CONFIRMED"
    return {
        "status": status,
        "ids": sorted(ids),
        "new_ops": new_ops,
        "msms_inputs": msms_inputs,
        "mmbs_inputs": mmbs_inputs,
        "incomplete_inputs": incomplete_inputs,
        "condition": "NOT_EVALUATED",
    }


# ---------------------------------------------------------------------------
# Model call
# ---------------------------------------------------------------------------

def call_live(prompt: str, endpoint: str, model: str,
              timeout: int = 900, num_ctx: int = 8192,
              num_predict: int = 4096) -> Dict[str, Any]:
    from mace.qwen import QwenClient
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
    response = client.chat(messages, purpose="direct_end_to_end",
                           json_mode=True)
    return {"raw_response": response.content,
            "stats": response.stats,
            "model": getattr(client, "model", model),
            "wall_seconds": round(time.time() - started, 3),
            "messages": messages}


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def run_task(task_id: str, args: argparse.Namespace,
             live: Optional[Dict[str, Any]],
             previous: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if task_id in PILOT_TASKS:
        context = pilot_context(task_id)
        task = context["task"]
        target = task["program"]["target_A"]
        source = task["program"]["source"]
        input_domain = task["input_domain"]
        files = ["<program>"]
        observable = json.dumps(task.get("observable_behavior"), ensure_ascii=False)
        line_offset = 0
        indexes = {"<program>": context["index"]}
        graph_ops = context["graph_ops"]
        style = "pilot"
    else:
        context = None
        parts = v3_prompt_parts(task_id)
        task = parts["task"]
        target = task["target_operation"]
        source = parts["source"]
        input_domain = parts["input_domain"]
        files = parts["files"]
        observable = parts["observable"]
        line_offset = parts["line_offset"]
        # The prompt shows only the target file; map against that file alone so
        # a cited line cannot silently resolve inside another graph-op file.
        indexes = {target["file"]: SourceIndex.from_path(
            target["file"], PROJECTS[task["project_id"]]["root"])}
        graph_ops = parts["graph_ops"]
        style = "v3"

    prompt = direct_prompt(task_id, source, target, files, input_domain,
                           observable=observable, max_relations=args.max_relations,
                           line_offset=line_offset)
    request = {
        "task_id": task_id,
        "model": args.model,
        "endpoint": args.endpoint,
        "options": {"temperature": 0.0, "seed": 42, "num_ctx": args.num_ctx,
                    "num_predict": args.num_predict, "retries": 0},
        "messages": [
            {"role": "system", "content":
                "You analyse Python masking relations. Return one JSON object only. "
                "Every operation must cite a real file, line and source text."},
            {"role": "user", "content": prompt},
        ],
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
    }
    if previous is not None:
        # Offline rescoring of the already-saved call: no second generation.
        live_record = previous["model_output"]
        if previous.get("prompt") != prompt:
            live_record = dict(live_record)
            live_record["prompt_mismatch_on_replay"] = True
    else:
        try:
            live_record = call_live(prompt, args.endpoint, args.model,
                                    num_ctx=args.num_ctx,
                                    num_predict=args.num_predict)
        except Exception as exc:  # noqa: BLE001 - record failures, do not retry
            live_record = {"raw_response": "", "stats": None,
                           "model": args.model, "wall_seconds": 0.0,
                           "messages": request["messages"],
                           "error": f"{type(exc).__name__}: {exc}"}
    raw = live_record.get("raw_response") or ""
    relations, parse_error = parse_relations(raw)

    mapped_relations: List[Dict[str, Any]] = []
    for relation in relations:
        mapped = map_relation(relation, indexes, graph_ops, style, [target["line"]])
        if mapped["status"] == "mapped":
            if context is not None:
                mapped["verification"] = verify_pilot(
                    relation, mapped["ops"], context)
            elif live is not None:
                score_ops = mapped["ops"]
                if args.normalize_inner:
                    score_ops = inner_ops(score_ops)
                    mapped["normalized_ops"] = score_ops
                mapped["verification"] = check_real_set(
                    task_id, score_ops, live)
            else:
                mapped["verification"] = {"status": "NOT_RUN",
                                          "reason": "no live arm data"}
        mapped_relations.append(mapped)

    summary: Dict[str, Any] = {
        "call_error": live_record.get("error"),
        "raw_relations": len(relations),
        "mapped_relations": sum(1 for r in mapped_relations
                                if r["status"] == "mapped"),
        "rejected_relations": sum(1 for r in mapped_relations
                                  if r["status"] != "mapped"),
        "parse_error": parse_error,
    }
    if context is None:
        summary["normalization"] = ("inner" if args.normalize_inner
                                    else "strict")
    if context is not None:
        verified = [r for r in mapped_relations
                    if r.get("verification", {}).get("status") == "VERIFIED"]
        absorber, coexisting = true_sets(context)
        covered = set()
        for relation in verified:
            names = frozenset(relation["verification"].get("operations", []))
            kind = relation["verification"].get("kind")
            if kind in ("independent", "cooperative") and names in absorber:
                covered.add(names)
            if kind == "coexisting" and names in coexisting:
                covered.add(names)
        total_true = len(absorber) + len(coexisting)
        statuses = [r.get("verification", {}).get("status")
                    for r in mapped_relations if r["status"] == "mapped"]
        summary.update({
            "verified_relations": len(verified),
            "true_relations": total_true,
            "covered_true_relations": len(covered),
            "exact_task": bool(covered == absorber | coexisting
                               and statuses
                               and all(s == "VERIFIED" for s in statuses)),
            "statuses": statuses,
        })
    else:
        statuses = [r.get("verification", {}).get("status")
                    for r in mapped_relations if r["status"] == "mapped"]
        summary.update({
            "set_confirmed_relations": sum(1 for s in statuses
                                           if s == "SET_CONFIRMED"),
            "not_confirmed_relations": sum(1 for s in statuses
                                           if s == "NOT_CONFIRMED"),
            "new_op_relations": sum(1 for s in statuses if s == "NEW_OP"),
            "condition": "NOT_EVALUATED",
        })

    return {
        "task_id": task_id,
        "kind": "pilot" if context is not None else "real_v3",
        "prompt": prompt,
        "prompt_sha256": request["prompt_sha256"],
        "model_output": live_record,
        "relations": mapped_relations,
        "summary": summary,
    }


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", nargs="+",
                        default=list(PILOT_TASKS) + list(V3_TASKS))
    parser.add_argument("--endpoint", default="http://127.0.0.1:11434")
    parser.add_argument("--model", default="qwen2.5-coder:32b")
    parser.add_argument("--num-ctx", type=int, default=8192)
    parser.add_argument("--num-predict", type=int, default=4096)
    parser.add_argument("--max-relations", type=int, default=12)
    parser.add_argument("--replay", type=Path, default=None,
                        help="rescore saved responses from this results.json "
                             "instead of calling the model")
    parser.add_argument("--normalize-inner", action="store_true",
                        help="secondary score: drop an enclosing statement "
                             "when the relation also names its body")
    parser.add_argument("--out", type=Path, default=OUT / "results.json")
    args = parser.parse_args(argv)

    live = json.loads(RESULTS_LIVE.read_text(encoding="utf-8")) \
        if RESULTS_LIVE.exists() else None
    previous = json.loads(args.replay.read_text(encoding="utf-8")) \
        if args.replay is not None else None
    OUT.mkdir(parents=True, exist_ok=True)
    dest = args.out.parent
    dest.mkdir(parents=True, exist_ok=True)
    if previous is None:
        (OUT / "requests").mkdir(exist_ok=True)
        (OUT / "raw").mkdir(exist_ok=True)

    tasks: Dict[str, Any] = {}
    for task_id in args.tasks:
        prior = previous["tasks"].get(task_id) if previous else None
        record = run_task(task_id, args, live, previous=prior)
        tasks[task_id] = record
        if previous is None:
            (OUT / "requests" / f"{task_id}.json").write_text(json.dumps({
                "task_id": task_id,
                "model": args.model,
                "endpoint": args.endpoint,
                "options": {"temperature": 0.0, "seed": 42,
                            "num_ctx": args.num_ctx,
                            "num_predict": args.num_predict, "retries": 0},
                "messages": record["model_output"]["messages"],
                "prompt_sha256": record["prompt_sha256"],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
            (OUT / "raw" / f"{task_id}.json").write_text(json.dumps({
                "task_id": task_id,
                "raw_response": record["model_output"]["raw_response"],
            }, ensure_ascii=False, indent=2), encoding="utf-8")
        (dest / f"{task_id}.json").write_text(json.dumps(
            record, ensure_ascii=False, indent=2), encoding="utf-8")
        print(f"[direct] {task_id} {json.dumps(record['summary'], ensure_ascii=False)}")

    payload = {
        "schema": "mace-direct-end-to-end-v1",
        "model": args.model,
        "options": {"temperature": 0.0, "seed": 42,
                    "num_ctx": args.num_ctx,
                    "num_predict": args.num_predict, "retries": 0},
        "tasks": tasks,
        "totals": {
            "calls": len(tasks),
            "prompt_tokens": sum((t["model_output"].get("stats") or {}).get(
                "prompt_tokens", 0) or 0 for t in tasks.values()),
            "completion_tokens": sum((t["model_output"].get("stats") or {}).get(
                "completion_tokens", 0) or 0 for t in tasks.values()),
            "wall_seconds": sum(t["model_output"].get("wall_seconds", 0) or 0
                                for t in tasks.values()),
        },
    }
    args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                        encoding="utf-8")
    print(f"[direct] wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
