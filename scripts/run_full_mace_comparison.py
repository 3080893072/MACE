"""Full-MACE adapter: Qwen hypotheses + role-separated causal search (v2).

v2 changes what Qwen is allowed to do:

* the model returns *structured hypotheses* (kept_ops for MSMS,
  disabled_ops for MMBS) with a condition, rationale and source evidence;
* every hypothesis is probed first.  Only ``status == OK`` with the matching
  predicate True grants priority; an unverified hypothesis keeps no reward;
* MSMS and MMBS are searched with separate score maps and separate queues
  (``graph_search.search_relations_role_separated``).  No fixed
  ``2.0 / (1 + rank)`` reward is applied to raw id rankings any more;
* the frozen universe U is never widened, narrowed or pruned: operations the
  model did not mention stay in the deterministic search space.

Legacy model output (``msms_rank`` / ``mmbs_rank``) is still accepted, but it
is converted into single-operation hypotheses that must pass the same gating
as any other hypothesis; it receives no unconditional priority.

``--mode legacy`` reproduces the previous shared-score arm for comparison and
is not the default.  All relations in either mode are still derived from real
interventions and the frozen strict-subset minimality definitions.
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from benchmark_v3_baselines import baseline_c, subgraph
from benchmark_v3_baselines.config import MODEL
from benchmark_v3_baselines.public_io import load_task

KIT = Path(__file__).resolve().parents[1]
DEFAULT_UNIVERSE_RUN = KIT / "runs" / "v3_baseline_pilot"
BOOST = 2.0  # legacy adapter only; v2 never uses this reward

SYSTEM = (
    "You analyse one Python operation A and a frozen set U of other "
    "operations. Return JSON only. Use only ids from U, never invent ids. "
    "Your explanations are hypotheses, not evidence: a separate causal "
    "executor will verify every claim."
)

TEMPLATE = """\
Target operation A:
{target}

Frozen candidate operations U (the full search space; do not extend it):
{ops}

Definitions:
- An MSMS hypothesis S is a set of operations that, when KEPT while all
  other operations in U are deleted, may still hide A's local effect.
- An MMBS hypothesis H is a set of operations that, when DELETED, may make
  A's local effect appear.

Propose at most {k_msms} MSMS hypotheses and at most {k_mmbs} MMBS hypotheses.
Each hypothesis may contain one or several operation ids from U. Give the
input condition under which you expect it to hold, a one-sentence rationale,
and the source evidence you used (names, expressions or line numbers).

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


def load_universe(task_id: str, run_root: Path) -> List[Dict[str, Any]]:
    path = run_root / "tasks" / task_id / "baseline_c" / "baseline_c.json"
    data = json.loads(path.read_text(encoding="utf-8"))
    return data["universe"]


def graph_scores(task_id: str, universe: Sequence[Dict[str, Any]]) -> Dict[str, float]:
    loaded = load_task(task_id)
    graph = subgraph.build(loaded["task"], loaded["source_text"])
    by_id = {item["id"]: float(item.get("score", 0.0))
             for item in graph.get("candidates", [])}
    return {op["id"]: by_id.get(op["id"], 0.0) for op in universe}


# ------------------------------------------------------------------ parsing
def _clean_ops(raw: Any, known: set, field: str) -> Dict[str, Any]:
    if not isinstance(raw, list):
        return {"ok": False, "reason": f"{field}_not_a_list"}
    ops = [item for item in raw if isinstance(item, str)]
    unknown = [item for item in ops if item not in known]
    if unknown:
        return {"ok": False, "reason": "unknown_ids", "unknown_ids": unknown}
    cleaned = sorted(set(ops))
    if not cleaned:
        return {"ok": False, "reason": "empty"}
    return {"ok": True, "ops": cleaned}


def parse_hypotheses(content: str, universe: Sequence[str]) -> Dict[str, Any]:
    """Parse structured v2 output, with legacy rank lists as a fallback.

    Returns ``msms`` / ``mmbs`` lists of id tuples plus a rejection log.
    Unknown ids reject the *hypothesis*, never the universe.
    """
    from mace.qwen import extract_json

    known = set(universe)
    parsed: Any
    try:
        parsed = extract_json(content)
    except Exception as exc:  # noqa: BLE001 - recorded, never hidden
        return {"format": "unparseable", "msms": [], "mmbs": [],
                "rejected": [{"reason": f"{type(exc).__name__}: {exc}"}]}

    rejected: List[Dict[str, Any]] = []
    if isinstance(parsed, dict) and (
            "msms_hypotheses" in parsed or "mmbs_hypotheses" in parsed):
        msms: List[tuple] = []
        mmbs: List[tuple] = []
        for key, field, bucket in (
                ("msms_hypotheses", "kept_ops", msms),
                ("mmbs_hypotheses", "disabled_ops", mmbs)):
            entries = parsed.get(key) or []
            if not isinstance(entries, list):
                rejected.append({"role": key, "reason": "not_a_list"})
                continue
            for entry in entries:
                if not isinstance(entry, dict):
                    rejected.append({"role": key, "reason": "not_an_object"})
                    continue
                cleaned = _clean_ops(entry.get(field), known, field)
                if not cleaned.get("ok"):
                    rejected.append({"role": key, **cleaned,
                                     "entry": entry})
                    continue
                if tuple(cleaned["ops"]) not in bucket:
                    bucket.append(tuple(cleaned["ops"]))
        return {"format": "structured", "msms": msms, "mmbs": mmbs,
                "rejected": rejected, "parsed": parsed}

    # Legacy rank lists -> one-operation hypotheses, gated like any other.
    if isinstance(parsed, dict) and (
            "msms_rank" in parsed or "mmbs_rank" in parsed):
        converted = {"msms": [], "mmbs": []}
        for key, field, bucket in (("msms_rank", "msms", converted["msms"]),
                                   ("mmbs_rank", "mmbs", converted["mmbs"])):
            for item in parsed.get(key) or []:
                if not isinstance(item, str):
                    rejected.append({"role": key, "reason": "not_a_string"})
                    continue
                if item not in known:
                    rejected.append({"role": key, "reason": "unknown_ids",
                                     "unknown_ids": [item]})
                    continue
                if (item,) not in bucket:
                    bucket.append((item,))
        return {"format": "legacy_converted", "msms": converted["msms"],
                "mmbs": converted["mmbs"], "rejected": rejected,
                "parsed": parsed}

    return {"format": "unknown", "msms": [], "mmbs": [], "rejected":
            [{"reason": "no recognised hypothesis keys"}], "parsed": parsed}


def call_qwen(client: Any, task_id: str, universe: Sequence[Dict[str, Any]],
              k_msms: int = 3, k_mmbs: int = 3) -> Dict[str, Any]:
    loaded = load_task(task_id)
    target = loaded["task"]["target_operation"]
    lines = "\n".join(
        f"- id={op['id']} lines={op['first_line']}-{op['last_line']} "
        f"kind={op.get('kind', '?')} code={op.get('code', '')!r}"
        for op in universe)
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": TEMPLATE.format(
            target=f"{target.get('file')}:{target.get('line')} "
                   f"{target.get('name', '')}",
            ops=lines, k_msms=k_msms, k_mmbs=k_mmbs)},
    ]
    started = time.time()
    response = client.chat(messages, purpose="full_mace_hypotheses",
                           json_mode=True)
    elapsed = time.time() - started
    parsed = parse_hypotheses(response.content, [op["id"] for op in universe])
    parsed.update({
        "request_messages": messages,
        "raw_response": response.content,
        "stats": response.stats,
        "model": getattr(client, "model", MODEL["model"]),
        "wall_seconds": round(elapsed, 3),
    })
    return parsed


# --------------------------------------------------------------------- arms
def run_arm(task_id: str, universe: Sequence[Dict[str, Any]], *,
            mode: str, hypotheses: Optional[Dict[str, Any]],
            msms_scores: Optional[Dict[str, float]] = None,
            mmbs_scores: Optional[Dict[str, float]] = None,
            legacy_scores: Optional[Dict[str, float]] = None,
            budget: Optional[int] = None,
            max_hypothesis_probes_per_role: int = 3) -> Dict[str, Any]:
    started = time.time()
    if mode == "legacy":
        result = baseline_c.run(
            task_id, candidate_ops=universe, search="graph",
            graph_scores=legacy_scores, probe_budget=budget,
            graph_meta={"ordering": "legacy_shared_scores", "budget": budget})
    elif mode == "role_separated":
        result = baseline_c.run(
            task_id, candidate_ops=universe, search="role_separated",
            msms_scores=msms_scores, mmbs_scores=mmbs_scores,
            hypotheses=hypotheses, probe_budget=budget,
            max_hypothesis_probes_per_role=max_hypothesis_probes_per_role,
            graph_meta={"ordering": "role_separated", "budget": budget})
    else:
        raise ValueError(f"unknown mode: {mode!r}")
    return {
        "arm": mode,
        "budget": budget,
        "search": result["search"],
        "per_input": [{
            "input": row["input"],
            "masked_empty": row["masked_empty"],
            "msms_ids": row["msms_ids"],
            "mmbs_ids": row["mmbs_ids"],
            "active_ops": row["active_ops"],
            "search_metrics": row.get("search_metrics"),
        } for row in result["per_input"]],
        "submission": result["submission"],
        "probe_executions": result["probe_executions"],
        "variant_builds": result["variant_builds"],
        "wall_seconds": round(time.time() - started, 3),
    }


def legacy_scores_from(ranking: Dict[str, Any],
                       base: Optional[Dict[str, float]] = None
                       ) -> Dict[str, float]:
    """Reproduce the old shared-score reward (comparison arm only)."""
    scored = dict(base or {})
    for key in ("msms", "mmbs"):
        for rank, ops in enumerate(ranking.get(key, [])):
            for op in ops:
                scored[op] = scored.get(op, 0.0) + BOOST / (1 + rank)
    return scored


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", nargs="+", required=True)
    parser.add_argument("--universe-run", type=Path,
                        default=DEFAULT_UNIVERSE_RUN)
    parser.add_argument("--budget", type=int, default=16,
                        help="subset evaluations per masked input; equal for "
                             "all arms")
    parser.add_argument("--mode", choices=["v2", "legacy"], default="v2")
    parser.add_argument("--max-hypothesis-probes", type=int, default=3)
    parser.add_argument("--out", type=Path,
                        default=KIT / "runs" / "v3_full_mace_v2")
    parser.add_argument("--skip-control", action="store_true",
                        help="do not run the deterministic control arm")
    args = parser.parse_args(argv)
    args.out.mkdir(parents=True, exist_ok=True)

    from benchmark_v3_baselines.run_pilot import _live_client

    client = _live_client()
    summary: Dict[str, Any] = {"model": MODEL["model"], "mode": args.mode,
                               "tasks": {}}
    for task_id in args.tasks:
        universe = load_universe(task_id, args.universe_run)
        base = graph_scores(task_id, universe)
        record: Dict[str, Any] = {
            "universe": [op["id"] for op in universe],
            "graph_scores": base,
        }
        print(f"[full-mace-v2] {task_id} qwen", flush=True)
        qwen = call_qwen(client, task_id, universe)
        record["qwen"] = qwen
        hypotheses = {"msms": qwen["msms"], "mmbs": qwen["mmbs"]}
        if not args.skip_control:
            print(f"[full-mace-v2] {task_id} control (no hypotheses)",
                  flush=True)
            record["control"] = run_arm(
                task_id, universe, mode="role_separated", hypotheses=None,
                budget=args.budget,
                max_hypothesis_probes_per_role=args.max_hypothesis_probes)
        if args.mode == "legacy":
            print(f"[full-mace-v2] {task_id} legacy shared scores", flush=True)
            record["full_mace"] = run_arm(
                task_id, universe, mode="legacy", hypotheses=None,
                legacy_scores=legacy_scores_from(qwen, base),
                budget=args.budget)
        else:
            print(f"[full-mace-v2] {task_id} role-separated + gating",
                  flush=True)
            record["full_mace"] = run_arm(
                task_id, universe, mode="role_separated",
                hypotheses=hypotheses, msms_scores={}, mmbs_scores={},
                budget=args.budget,
                max_hypothesis_probes_per_role=args.max_hypothesis_probes)
        summary["tasks"][task_id] = record
        (args.out / "tasks" / task_id).mkdir(parents=True, exist_ok=True)
        (args.out / "tasks" / task_id / "result.json").write_text(
            json.dumps(record, ensure_ascii=False, indent=2), encoding="utf-8")
        (args.out / "summary.json").write_text(
            json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({t: {"universe": len(r["universe"]),
                          "qwen_format": r["qwen"]["format"],
                          "hypotheses": {
                              "msms": len(r["qwen"]["msms"]),
                              "mmbs": len(r["qwen"]["mmbs"])}}
                      for t, r in summary["tasks"].items()}, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
