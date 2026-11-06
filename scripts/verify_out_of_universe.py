"""Independent intervention acceptance for claims outside the scorer's U.

The scorer reads a HIDDEN ``candidate_universe`` and reports any claim that
uses another operation as ``UNVERIFIED``.  That is a statement about the
scorer's declared universe, not about the claim.  This script re-executes the
interventions locally, over the *public* graph candidate set the submission
was produced from, and records the evidence separately:

* MSMS claim ``S``: ``masked(U \\ S)`` must hold on every submitted input and
  no non-empty proper subset ``S'`` may satisfy ``masked(U \\ S')``.
* MMBS claim ``D``: ``exposed(D)`` must hold on every submitted input and no
  proper subset of ``D`` (empty included) may satisfy ``exposed(D')``.

The result is labelled ``ACCEPTED_LOCAL_UNIVERSE`` only when every input
passes.  It is *not* a claim over the HIDDEN universe and *not* a claim over
the whole legal input domain; ``outcome_scope`` says so explicitly.

Usage::

    python -m scripts.verify_out_of_universe
    python -m scripts.verify_out_of_universe --tasks jinja2_bytecode_cache_read
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import time
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from benchmark_v3_baselines.baseline_c import PROBES, _active_ops
from benchmark_v3_baselines.config import TASK_IDS
from benchmark_v3_baselines.execution import Executor
from benchmark_v3_baselines.public_io import load_task

KIT = Path(__file__).resolve().parents[1]
ABLATION = KIT / "runs" / "v3_subgraph_ablation"
PILOT = KIT / "runs" / "v3_baseline_pilot"
OUT = KIT / "runs" / "v3_out_of_universe"
MODES = ("Graph-candidates", "Graph-full")

Outcome = Tuple[Optional[bool], str]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _key(ids: Iterable[str]) -> str:
    return "+".join(sorted(ids)) or "EMPTY"


def _eval(executor: Executor, payload: Dict[str, Any],
          disabled: Sequence[str]) -> Dict[str, Any]:
    plus = executor.observation(disabled, "plus", payload)
    minus = executor.observation(disabled, "minus", payload)
    ok = (not plus.get("__probe_error__")
          and not minus.get("__probe_error__"))
    if not ok:
        return {"status": "UNKNOWN", "masked": None, "exposed": None,
                "plus": plus, "minus": minus}
    status = "OK"
    return {
        "status": status,
        "masked": bool(plus.get("outcome") == "return" and plus == minus),
        "exposed": bool(plus != minus),
        "plus": plus,
        "minus": minus,
    }


def op_id_for(task_dir: Path, operation: Dict[str, Any]) -> Optional[str]:
    ops = json.loads((task_dir / "candidates.json").read_text(
        encoding="utf-8"))["selection"]["ops"]
    for op in ops:
        if (op["file"] == operation["file"]
                and op["first_line"] <= int(operation["line"])
                <= op["last_line"]):
            return op["id"]
    return None


def verify_msms(executor: Executor, payload: Dict[str, Any],
                universe: List[str], kept: List[str]) -> Dict[str, Any]:
    rest = sorted(set(universe) - set(kept))
    base = _eval(executor, payload, rest)
    evidence = {"kept": kept, "complement": rest, "base": base,
                "proper_subsets": []}
    if base["masked"] is not True:
        return {"verdict": "REJECTED" if base["status"] == "OK" else "UNDECIDED",
                "reason": "masked(U \\ S) does not hold", "evidence": evidence}
    undecided = False
    for size in range(1, len(kept)):
        for sub in itertools.combinations(sorted(kept), size):
            sub_rest = sorted(set(universe) - set(sub))
            record = _eval(executor, payload, sub_rest)
            evidence["proper_subsets"].append(
                {"kept": list(sub), "disabled": sub_rest, "masked":
                 record["masked"], "status": record["status"]})
            if record["masked"] is True:
                return {"verdict": "REJECTED",
                        "reason": f"proper subset {list(sub)} also masks",
                        "evidence": evidence}
            if record["status"] != "OK":
                undecided = True
    return {"verdict": "UNDECIDED" if undecided else "ACCEPTED",
            "reason": ("some strict subset has no valid intervention"
                       if undecided else "masked and minimal over U"),
            "evidence": evidence}


def verify_mmbs(executor: Executor, payload: Dict[str, Any],
                universe: List[str], disabled: List[str]) -> Dict[str, Any]:
    base = _eval(executor, payload, disabled)
    evidence = {"disabled": disabled, "base": base, "proper_subsets": []}
    if base["exposed"] is not True:
        return {"verdict": "REJECTED" if base["status"] == "OK" else "UNDECIDED",
                "reason": "exposed(D) does not hold", "evidence": evidence}
    undecided = False
    for size in range(0, len(disabled)):
        for sub in itertools.combinations(sorted(disabled), size):
            record = _eval(executor, payload, sub)
            evidence["proper_subsets"].append(
                {"disabled": list(sub), "exposed": record["exposed"],
                 "status": record["status"]})
            if record["exposed"] is True:
                return {"verdict": "REJECTED",
                        "reason": f"proper subset {list(sub)} also exposes",
                        "evidence": evidence}
            if record["status"] != "OK":
                undecided = True
    return {"verdict": "UNDECIDED" if undecided else "ACCEPTED",
            "reason": ("some proper subset has no valid intervention"
                       if undecided else "exposed and minimal over U"),
            "evidence": evidence}


def claim_scope(task_dir: Path, universe: List[str],
                claim: Dict[str, Any]) -> Dict[str, Any]:
    ids = [op_id_for(task_dir, operation) for operation in claim["operations"]]
    outside_ops = [operation["file"] + ":" + str(operation["line"])
                   for operation, op_id in zip(claim["operations"], ids)
                   if op_id is None]
    return {"op_ids": ids, "unresolved_operations": outside_ops,
            "inside_local_universe": all(op_id is not None for op_id in ids)}


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tasks", nargs="*", choices=TASK_IDS,
                        default=TASK_IDS)
    args = parser.parse_args(argv)
    OUT.mkdir(parents=True, exist_ok=True)
    config = {
        "experiment": "mace_out_of_universe_independent_acceptance",
        "task_ids": list(args.tasks),
        "modes": list(MODES),
        "local_universe": "Graph candidate set (public, frozen before run)",
        "scorer_universe": "HIDDEN; never read by this script",
        "model_calls": 0,
        "code_sha256": {
            "benchmark_v3_baselines/execution.py": sha256_file(
                KIT / "benchmark_v3_baselines/execution.py"),
            "benchmark_v3_baselines/baseline_c.py": sha256_file(
                KIT / "benchmark_v3_baselines/baseline_c.py"),
            "scripts/verify_out_of_universe.py": sha256_file(Path(__file__)),
        },
        "started": time.strftime("%Y-%m-%dT%H:%M:%S"),
    }
    (OUT / "config.json").write_text(
        json.dumps(config, ensure_ascii=False, indent=2), encoding="utf-8")
    report: Dict[str, Any] = {"tasks": {}, "totals": {}}
    for task_id in args.tasks:
        task_dir = ABLATION / "tasks" / task_id
        loaded = load_task(task_id)
        task = loaded["task"]
        candidates = json.loads((task_dir / "candidates.json").read_text(
            encoding="utf-8"))["selection"]["ops"]
        universe = sorted(op["id"] for op in candidates)
        pilot = json.loads((PILOT / "tasks" / task_id / "baseline_c" /
                            "baseline_c.json").read_text(encoding="utf-8"))
        c_universe = sorted(op["id"] for op in pilot["universe"])
        score_path = task_dir / "Graph-full" / "score.json"
        scores = json.loads(score_path.read_text(encoding="utf-8"))
        unverified = [claim for claim in scores["claims"]
                      if claim.get("status") == "UNVERIFIED"]
        submissions = {}
        for mode in MODES:
            submissions[mode] = json.loads(
                (task_dir / mode / "submission.json").read_text(
                    encoding="utf-8"))
        # Claims are identical across the two graph modes on this dev set;
        # verify each distinct (type, operation set) once and cite both.
        rows = []
        executor = Executor(task_id, task["project_id"], PROBES[task_id],
                            task["target_operation"], f"verify_{task_id}")
        executor.set_universe(candidates)
        for scored in unverified:
            relation_key = scored.get("relation_key", "")
            kind, _, relation_ref = relation_key.partition(":")
            claim = None
            for candidate in submissions["Graph-full"]["claims"]:
                if candidate["type"] != kind:
                    continue
                for operation in candidate["operations"]:
                    prefix = f"{operation['file']}:{operation['line']}"
                    if relation_ref == prefix or relation_ref.startswith(
                            prefix + "-"):
                        claim = candidate
                        break
                if claim is not None:
                    break
            if claim is None:
                rows.append({"relation_key": relation_key,
                             "verdict": "UNRESOLVED_CLAIM"})
                continue
            modes_with_claim = []
            for mode in MODES:
                for candidate in submissions[mode]["claims"]:
                    if (candidate["type"] == kind
                            and candidate.get("operations")
                            == claim.get("operations")):
                        modes_with_claim.append(mode)
                        break
            scope = claim_scope(task_dir, universe, claim)
            ids = [op_id for op_id in scope["op_ids"] if op_id]
            operations_meta = []
            for operation, op_id in zip(claim["operations"], scope["op_ids"]):
                source_path = _project_file(task, operation["file"])
                source_check = None
                if source_path and source_path.exists():
                    lines = source_path.read_text(
                        encoding="utf-8", errors="replace").splitlines()
                    if 1 <= int(operation["line"]) <= len(lines):
                        source_check = {
                            "line_matches_claim_code": (
                                lines[int(operation["line"]) - 1].strip()
                                == operation["code"].strip().splitlines()[0].strip()
                                if operation.get("code") else None),
                            "actual_line": lines[int(operation["line"]) - 1],
                        }
                operations_meta.append({
                    "operation": operation,
                    "op_id": op_id,
                    "in_c_universe": op_id in c_universe,
                    "in_local_universe": op_id in universe,
                    "source_check": source_check,
                })
            per_input = []
            for payload in claim["inputs"]:
                if not scope["inside_local_universe"]:
                    per_input.append({"input": payload,
                                      "verdict": "UNDECIDED",
                                      "reason": "operation not in local U"})
                    continue
                if not executor.a_executes(payload):
                    per_input.append({"input": payload, "verdict": "INVALID",
                                      "reason": "A does not execute"})
                    continue
                if kind == "MSMS":
                    result = verify_msms(executor, payload, universe, ids)
                elif kind == "MMBS":
                    result = verify_mmbs(executor, payload, universe, ids)
                else:
                    result = {"verdict": "UNSUPPORTED_TYPE", "reason": kind}
                active = _active_ops(executor, payload)
                result["input"] = payload
                result["active_ops"] = sorted(active)
                result["members_individually_active"] = {
                    op_id: op_id in active for op_id in ids}
                per_input.append(result)
            verdicts = [row["verdict"] for row in per_input]
            if verdicts and all(v == "ACCEPTED" for v in verdicts):
                verdict = "ACCEPTED_LOCAL_UNIVERSE"
            elif any(v == "REJECTED" for v in verdicts):
                verdict = "REJECTED"
            elif any(v in ("INVALID", "UNDECIDED") for v in verdicts):
                verdict = "UNDECIDED"
            else:
                verdict = "UNRESOLVED"
            rows.append({
                "relation_key": relation_key,
                "type": kind,
                "scorer_status": scored.get("status"),
                "verdict": verdict,
                "outcome_scope": (
                    "exact over the submitted finite inputs and the public "
                    "graph candidate universe; not over HIDDEN U and not "
                    "over the whole legal input domain"),
                "modes_with_claim": modes_with_claim,
                "operations": operations_meta,
                "per_input": per_input,
                "probes_used": executor.probe_executions,
            })
            print(f"[verify] {task_id} {kind} {ids} -> {verdict}", flush=True)
        probe_total = executor.probe_executions
        report["tasks"][task_id] = {
            "task_id": task_id,
            "local_universe_size": len(universe),
            "c_universe_size": len(c_universe),
            "graph_universe_extra": sorted(set(universe) - set(c_universe)),
            "unverified_claims": len(unverified),
            "rows": rows,
            "probe_executions": probe_total,
            "variant_builds": len(executor._variants),
        }
        (OUT / "tasks" / task_id).mkdir(parents=True, exist_ok=True)
        (OUT / "tasks" / task_id / "verification.json").write_text(
            json.dumps(report["tasks"][task_id], ensure_ascii=False, indent=2),
            encoding="utf-8")
    counts: Dict[str, int] = {}
    for task in report["tasks"].values():
        for row in task["rows"]:
            counts[row["verdict"]] = counts.get(row["verdict"], 0) + 1
    report["totals"] = {
        "claims": sum(len(task["rows"]) for task in report["tasks"].values()),
        "verdicts": counts,
        "probe_executions": sum(task["probe_executions"]
                                for task in report["tasks"].values()),
        "variant_builds": sum(task["variant_builds"]
                              for task in report["tasks"].values()),
    }
    (OUT / "verification.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(report["totals"], ensure_ascii=False, indent=2))
    return 0


def _project_file(task: Dict[str, Any], relative: str) -> Optional[Path]:
    from benchmark_real_v3.config import PROJECTS
    root = PROJECTS[task["project_id"]]["root"]
    return root / relative


if __name__ == "__main__":
    raise SystemExit(main())
