"""Direct Qwen 32B vs Full MACE on the frozen source-derived tasks.

This is an adapter over the frozen SD artefacts; it does not rebuild tasks,
change the hidden scorer, or modify the C0 universe.  Both arms see the same
public patched source, target A and opaque inputs in1..inN.  Full MACE sees
the frozen C0 universe U as its candidate list and may return hypotheses over
U; Direct Qwen sees no candidate list and may cite any statement in the file.

One model call per arm per task (retries disabled).  Full MACE performs the
same role-separated search as C0 with budget 16.  MSMS is scored strictly by
span-containment block family equality; MMBS is recorded but not scored.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Sequence

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))
TOOLS = KIT / "benchmark_v4_dataset" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from sd_algorithm_pilot import (  # noqa: E402
    DS, SD, MAX_OPS, WORK, SDExecutor, block_spans, family,
    load, project_containment, stage0_row, _MARKER,
)
from benchmark_v3_baselines.graph_search import (  # noqa: E402
    search_relations_role_separated,
)
from open_ops.semantic_relations import (  # noqa: E402
    SourceIndex, map_proposal, numbered_source,
)
from mace.qwen import QwenClient  # noqa: E402
from scripts.run_direct_qwen_baseline import (  # noqa: E402
    parse_relations, _strip_fences,
)
from scripts.run_full_mace_comparison import parse_hypotheses  # noqa: E402

MODEL = "qwen2.5-coder:32b"
ENDPOINT = "http://127.0.0.1:11434"
NUM_CTX = 8192
NUM_PREDICT = 4096
BUDGET = 16
RUN_ROOT = KIT / "runs" / "sd_direct_vs_full"


def _public_view(cid: str):
    spec = load(SD / "cases" / f"{cid}.json")
    rel = spec["base"]["file"]
    patched = (SD / "evidence" / cid / "patched" / Path(rel).name) \
        .read_text("utf-8").splitlines(keepends=True)
    public_text = "".join(
        line if not _MARKER.match(line) else "\n" for line in patched)
    a_line = int(spec["base"]["A_line"])
    return spec, rel, patched, public_text, a_line


def _inputs(spec: dict):
    keys = list(spec["inputs"])
    return ([{"id": f"in{i + 1}"} for i in range(len(keys))],
            {f"in{i + 1}": key for i, key in enumerate(keys)})


def _load_universe(cid: str):
    frozen = load(KIT / "runs" / "sd_v1_algorithm_pilot" / f"{cid}__c0.json")
    return frozen["universe"], frozen["per_input"]


def direct_prompt(cid: str, rel: str, source: str, a_line: int,
                  a_code: str, n_inputs: int) -> str:
    inputs = ", ".join(f"`in{i}`" for i in range(1, n_inputs + 1))
    return f"""You are analysing a proposed deletion in a Python function. Use only
the public information below. A Python exception is an observation. The best
evidence level is BOUNDED: execution on the declared finite inputs, never a proof.

## Task
{cid}

## File
`{rel}`

## Program with source line numbers
```text
{numbered_source(source)}
```

## Target A
Line {a_line}: `{a_code.strip()}`
Deletion rule: replace exactly this line with equal-indentation `pass`.
Deleting A is unobservable on an input when the program's observable behaviour
is the same with A present and with A deleted.

## Legal inputs
The declared finite inputs are opaque labels: {inputs}.  Do not assume their
roles or argument values.

## Observable
The function return value, or the raised exception type and message.

## Question
Find every set of one or more other statements such that, on at least one
legal input, deleting those statements together makes the deletion of A
unobservable.  Each set must be minimal: no proper non-empty subset of it has
the same effect.  Different sets may be alternative paths.

For each set:
- list the exact statements with their 1-based starting line and source text;
- state the condition under which the relation holds, using only simple
  comparisons/boolean expressions; write `true` if it is unconditional;
- give a one-sentence rationale.

## Required JSON
{{
  "relations": [
    {{
      "operations": [
        {{"file": "{rel}", "line": <int>, "text": "<source text>"}}
      ],
      "condition": "<boolean expression or true>",
      "rationale": "<one sentence>"
    }}
  ]
}}

Return at most 12 different relations.  Return one JSON object and no prose
outside it.
"""


def full_prompt(cid: str, rel: str, source: str, a_line: int, a_code: str,
                universe: Sequence[dict], n_inputs: int) -> str:
    ops = "\n".join(
        f"- id={op['id']} lines={op['first_line']}-{op['last_line']} "
        f"kind={op.get('kind', '?')} code={op.get('code', '')!r}"
        for op in universe)
    inputs = ", ".join(f"`in{i}`" for i in range(1, n_inputs + 1))
    return f"""You analyse one Python operation A and a frozen set U of other
operations. Return JSON only. Use only ids from U, never invent ids. Your
explanations are hypotheses, not evidence: a separate causal executor will
verify every claim.

## Task
{cid}

## File
`{rel}`

## Program with source line numbers
```text
{numbered_source(source)}
```

## Target operation A
Line {a_line}: `{a_code.strip()}`
Deleting A means replacing exactly this line with equal-indentation `pass`.

## Legal inputs
The declared finite inputs are opaque labels: {inputs}.  Do not assume their
roles or argument values.

## Frozen candidate operations U (the full search space; do not extend it)
{ops}

## Definitions
- An MSMS hypothesis S is a set of operations that, when KEPT while all other
  operations in U are deleted, may still hide A's local effect.
- An MMBS hypothesis H is a set of operations that, when DELETED, may make
  A's local effect appear.

Propose at most 3 MSMS hypotheses and at most 3 MMBS hypotheses.  Each
hypothesis may contain one or several operation ids from U.  Give the input
condition under which you expect it to hold, a one-sentence rationale, and the
source evidence you used.

Return exactly this JSON shape:
{{
  "msms_hypotheses": [
    {{"kept_ops": ["id", ...], "condition": "...", "rationale": "...",
      "source_evidence": ["..."]}}
  ],
  "mmbs_hypotheses": [
    {{"disabled_ops": ["id", ...], "condition": "...", "rationale": "...",
      "source_evidence": ["..."]}}
  ]
}}
"""


def call(client: QwenClient, messages: List[dict], purpose: str) -> dict:
    started = time.perf_counter()
    try:
        response = client.chat(messages, purpose=purpose, json_mode=True)
        return {
            "ok": True,
            "messages": messages,
            "raw_response": response.content,
            "stats": response.stats,
            "model": client.model,
            "wall_seconds": round(time.perf_counter() - started, 3),
        }
    except Exception as exc:  # noqa: BLE001 - record, never retry
        return {
            "ok": False,
            "messages": messages,
            "raw_response": "",
            "stats": None,
            "model": client.model,
            "wall_seconds": round(time.perf_counter() - started, 3),
            "error": f"{type(exc).__name__}: {exc}",
        }


def map_direct(raw: str, rel: str, source: str, a_line: int):
    relations, parse_error = parse_relations(raw)
    index = SourceIndex.from_source(rel, source)
    mapped, rejected = [], []
    for relation in relations:
        ops, bad = [], []
        for proposal in relation.get("operations") or []:
            result = map_proposal(proposal, index, graph_ops=None,
                                  style="v3", exclude_lines=[a_line])
            if result["status"] == "mapped":
                ops.append(result["op"])
            else:
                bad.append(result)
        if bad or not ops:
            rejected.append({"relation": relation, "rejected": bad})
            continue
        by_id = {op["id"]: op for op in ops}
        mapped.append({
            "operations": list(by_id.values()),
            "condition": relation.get("condition"),
            "rationale": relation.get("rationale"),
        })
    return mapped, rejected, parse_error


def score_sets(sets: Sequence[Sequence[str]], ops_by_id: dict,
               spans: dict, hidden_msms: Sequence[Sequence[str]]):
    want = family(hidden_msms)
    hits = [project_containment(s, ops_by_id, spans) for s in sets]
    got = family([h[0] for h in hits])
    stray = [o for h in hits for o in h[1]]
    exact = got == want and not stray
    return {
        "hidden_msms": sorted(sorted(s) for s in hidden_msms),
        "got_msms_blocks": sorted(sorted(s) for s in got),
        "stray_ops": stray,
        "msms_exact": exact,
        "false_relations": len(got - want) + len(stray),
        "unmatched_sets": sum(1 for h in hits if not h[0]),
    }


def prepare(cid: str, arm: str):
    spec, rel, patched, source, a_line = _public_view(cid)
    payloads, key_map = _inputs(spec)
    meta = stage0_row(spec["base"]["slug"])
    root = (DS / "discovery" / meta["root"]).resolve()
    probe = (KIT / spec["probe"]).resolve()
    work = WORK / cid / f"direct_vs_full_{arm}"
    work.mkdir(parents=True, exist_ok=True)
    executor = SDExecutor(spec["base"]["slug"], root, rel, patched, a_line,
                          probe, key_map, work)
    return spec, rel, patched, source, a_line, payloads, key_map, executor


def run_task(cid: str, client: QwenClient) -> dict:
    spec, rel, patched, source, a_line, payloads, key_map, executor = prepare(
        cid, "full")
    universe, frozen_inputs = _load_universe(cid)
    universe_ids = [op["id"] for op in universe]
    executor.set_universe(universe)
    searched = {row["input_key"]: bool(row["searched"])
                for row in frozen_inputs}
    a_code = spec["base"]["A_code"]
    n_inputs = len(payloads)
    reference = load(SD / "tasks" / cid / "reference.json")
    enumeration = load(SD / "evidence" / cid / "enumeration.json")
    spans = block_spans(enumeration)

    # Both arms use the same public source and the same opaque inputs.
    direct_req = [{
        "role": "system",
        "content": ("You analyse Python masking relations. Return one JSON "
                    "object only. Every operation must cite a real file, line "
                    "and source text."),
    }, {"role": "user", "content": direct_prompt(
        cid, rel, source, a_line, a_code, n_inputs)}]
    full_req = [{
        "role": "system",
        "content": ("You analyse one Python operation and a frozen candidate "
                    "set. Return one JSON object only. Use only ids from U."),
    }, {"role": "user", "content": full_prompt(
        cid, rel, source, a_line, a_code, universe, n_inputs)}]

    print(f"[{cid}] direct qwen", flush=True)
    direct = call(client, direct_req, f"sd_direct_{cid}")
    direct_sets, direct_rejected, direct_parse_error = map_direct(
        direct.get("raw_response") or "", rel, source, a_line)
    direct_ops = {op["id"]: op for reln in direct_sets
                  for op in reln["operations"]}

    print(f"[{cid}] full mace qwen", flush=True)
    full_call = call(client, full_req, f"sd_full_hypotheses_{cid}")
    parsed = parse_hypotheses(full_call.get("raw_response") or "",
                              universe_ids)
    hypotheses = {"msms": parsed["msms"], "mmbs": parsed["mmbs"]}

    # Full MACE: one role-separated search per masking input; budget 16.
    full_rows = {}
    for payload in payloads:
        key = payload["id"]
        if not searched.get(key_map[key]):
            continue
        result = search_relations_role_separated(
            executor, payload, universe_ids,
            budget=BUDGET, hypotheses=hypotheses,
            max_hypothesis_probes_per_role=3)
        full_rows[key] = result

    # ---- scoring: hidden data is read only below this line ----------------
    detail, scores = [], {
        "masking_inputs": 0,
        "direct_exact": 0, "full_exact": 0,
        "direct_false": 0, "full_false": 0,
        "direct_unmatched": 0, "full_unmatched": 0,
        "direct_sets": len(direct_sets),
        "full_sets_total": sum(len(r["msms_ids"]) for r in full_rows.values()),
        "full_mmbs_sets_total": sum(len(r["mmbs_ids"])
                                    for r in full_rows.values()),
    }
    for payload in payloads:
        key = payload["id"]
        input_key = key_map[key]
        hidden = reference["inputs"][input_key]
        if hidden["role"] != "masking":
            continue
        scores["masking_inputs"] += 1
        d_sets = [[op["id"] for op in r["operations"]] for r in direct_sets]
        d_score = score_sets(d_sets, direct_ops, spans, hidden["msms"])
        f_result = full_rows.get(key)
        f_sets = f_result["msms_ids"] if f_result else []
        f_score = score_sets(f_sets, executor.universe, spans,
                             hidden["msms"])
        scores["direct_exact"] += int(d_score["msms_exact"])
        scores["full_exact"] += int(f_score["msms_exact"])
        scores["direct_false"] += d_score["false_relations"]
        scores["full_false"] += f_score["false_relations"]
        scores["direct_unmatched"] += d_score["unmatched_sets"]
        scores["full_unmatched"] += f_score["unmatched_sets"]
        detail.append({
            "input": input_key,
            "direct": d_score,
            "full_mace": f_score,
            "full_metrics": None if f_result is None else {
                k: f_result.get(k) for k in (
                    "evaluations", "subsets_total", "complete",
                    "evidence_complete", "unknown_subsets", "invalid_subsets",
                    "cache_hits", "reused_evidence")},
        })

    # Raw model outputs and per-task evidence are written by the caller.
    return {
        "task_id": cid,
        "mechanism": spec["mechanism"],
        "model": MODEL,
        "options": {"temperature": 0.0, "seed": 42, "num_ctx": NUM_CTX,
                    "num_predict": NUM_PREDICT, "retries": 0},
        "public_source_sha256": hashlib.sha256(
            source.encode("utf-8")).hexdigest(),
        "universe": universe,
        "universe_ids": universe_ids,
        "direct": {
            "call": direct,
            "prompt_sha256": hashlib.sha256(
                direct_req[1]["content"].encode("utf-8")).hexdigest(),
            "parsed_sets": [{
                "ids": [op["id"] for op in r["operations"]],
                "ops": r["operations"],
                "condition": r["condition"],
                "rationale": r["rationale"]} for r in direct_sets],
            "rejected": direct_rejected,
            "parse_error": direct_parse_error,
        },
        "full_mace": {
            "call": full_call,
            "prompt_sha256": hashlib.sha256(
                full_req[1]["content"].encode("utf-8")).hexdigest(),
            "parse": {k: parsed.get(k) for k in (
                "format", "msms", "mmbs", "rejected")},
            "hypotheses": {k: [list(x) for x in v]
                           for k, v in hypotheses.items()},
            "per_input": full_rows,
        },
        "scoring": scores,
        "detail": detail,
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", nargs="+", required=True)
    ap.add_argument("--out", type=Path,
                    default=RUN_ROOT / "results.json")
    ap.add_argument("--resume", action="store_true")
    args = ap.parse_args()

    existing = {}
    if args.resume and args.out.exists():
        existing = json.loads(args.out.read_text(encoding="utf-8")).get(
            "tasks", {})
    client = QwenClient(
        provider="ollama", model=MODEL, endpoint=ENDPOINT,
        num_ctx=NUM_CTX, num_predict=NUM_PREDICT, temperature=0.0,
        seed=42, timeout=900, retries=0)
    payload = {
        "schema": "mace-direct-vs-full/1",
        "model": MODEL,
        "options": {"temperature": 0.0, "seed": 42, "num_ctx": NUM_CTX,
                    "num_predict": NUM_PREDICT, "retries": 0,
                    "full_search_budget": BUDGET},
        "tasks": dict(existing),
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    for cid in args.tasks:
        if cid in payload["tasks"]:
            print(f"[{cid}] skipped (resume)", flush=True)
            continue
        record = run_task(cid, client)
        payload["tasks"][cid] = record
        args.out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                            encoding="utf-8")
        print(f"[{cid}] direct={record['scoring']['direct_exact']}/"
              f"{record['scoring']['masking_inputs']} "
              f"full={record['scoring']['full_exact']}/"
              f"{record['scoring']['masking_inputs']}", flush=True)
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
