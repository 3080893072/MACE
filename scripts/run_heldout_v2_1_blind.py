# -*- coding: utf-8 -*-
"""MACE-Bench v2.1 -- HELDOUT blind prediction runner (C0 + Full MACE).

Binds exclusively to the formal v2.1 tree:
    benchmark_v4_dataset/source_derived_v2_1/heldout

Reads public material from the isolated whitelisted copy:
    runs/heldout_public_only

Never reads (audited at runtime, hard failure): tasks/, acceptance/, seal/,
evidence/<cid>/enumeration*.json, any reference.json, and the whole legacy
source_derived/heldout tree.

The DEV runner (scripts/run_candidate_discovery_v2_1.py) is NOT modified and
NOT invoked as a program.  Its pure helper functions are imported; the two
truth-reading sites in it (`_prepare_baseline` scoring, `reference_for`) are
never called -- this file re-implements those preparation steps without them.
Algorithmic logic (discover / rank_and_prune / role-separated search /
verification / strict minimality) is byte-for-byte the frozen DEV code.

Usage:
    python -I scripts/run_heldout_v2_1_blind.py --method c0
    python -I scripts/run_heldout_v2_1_blind.py --method full
    python -I scripts/run_heldout_v2_1_blind.py --method both
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import stat
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Sequence

sys.stdout.reconfigure(encoding="utf-8")

KIT = Path(__file__).resolve().parents[1]
HELDOUT = KIT / "benchmark_v4_dataset" / "source_derived_v2_1" / "heldout"
PUB = KIT / "runs" / "heldout_public_only"
OUTDIR = KIT / "results"
RAWDIR = KIT / "runs" / "heldout_v2_1_blind"

# --- path binding assertions (no silent fallback) -------------------------
assert HELDOUT.is_dir(), HELDOUT
assert HELDOUT.name == "heldout" and HELDOUT.parent.name == "source_derived_v2_1"
assert PUB.is_dir(), PUB
assert (PUB / "public_manifest.json").exists()

# --- runtime truth-access guard ------------------------------------------
ACCESS_LOG: List[str] = []
VIOLATIONS: List[str] = []
FORBIDDEN_MARKERS = (
    "source_derived_v2_1/heldout/tasks",
    "source_derived_v2_1/heldout/acceptance",
    "source_derived_v2_1/heldout/seal",
    "source_derived/heldout",
    "enumeration",
    "reference.json",
)


def _norm(p: Any) -> str:
    try:
        return str(p).replace("\\", "/")
    except Exception:  # noqa: BLE001
        return ""


def _audit(event: str, args: tuple) -> None:
    if event not in ("open", "os.open", "io.open_code"):
        return
    if not args:
        return
    path = _norm(args[0])
    if not path or path.isdigit():
        return
    ACCESS_LOG.append(path)
    for marker in FORBIDDEN_MARKERS:
        if marker in path:
            VIOLATIONS.append(path)
            raise PermissionError(
                f"BLIND-GUARD: forbidden truth path opened: {path}")


sys.addaudithook(_audit)  # type: ignore[attr-defined]

SCRIPTS = KIT / "scripts"
if str(SCRIPTS) not in sys.path:
    sys.path.insert(0, str(SCRIPTS))
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))
TOOLS = KIT / "benchmark_v4_dataset" / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import run_candidate_discovery_v2_1 as cd  # noqa: E402
from mace.qwen import QwenClient  # noqa: E402

# Re-bind the legacy root used by helper constants.  Nothing below calls the
# DEV runner's prepare()/reference_for(); the binding is defensive only.
import sd_algorithm_pilot as sap  # noqa: E402
sap.SD = HELDOUT
cd.SD = HELDOUT

BUDGET = cd.BUDGET
MAX_OPS = cd.MAX_OPS
MODEL = cd.MODEL
ENDPOINT = cd.ENDPOINT
NUM_CTX = cd.NUM_CTX
NUM_PREDICT = cd.NUM_PREDICT
SEED = 42
TEMPERATURE = 0.0


class BlindExecutor(cd.SDExecutor):
    """SDExecutor with a Windows unlink compatibility fix only.

    The upstream tree can contain read-only files; hardlinking them makes the
    variant-file replacement fail with WinError 5.  We chmod the single target
    writable before unlinking.  No algorithmic change.
    """

    def variant_dir(self, disabled, side: str):
        key = (tuple(sorted(disabled)), side)
        if key in self._dirs:
            return self._dirs[key]
        digest = hashlib.sha1(
            (sap.subset_key(disabled) + "|" + side).encode("utf-8")
        ).hexdigest()[:16]
        dest = self.work / "var" / digest
        if not dest.exists():
            sap._hardlink_tree(self.root / self.top, dest / self.top)
        target = dest / self.rel
        if target.exists() or target.is_symlink():
            try:
                target.unlink()
            except PermissionError:
                os.chmod(target, stat.S_IWRITE | stat.S_IREAD)
                target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(self._text(disabled, side)), encoding="utf-8")
        self.variant_builds += 1
        self._dirs[key] = dest
        return dest


def _rmtree_force(path: Path) -> None:
    import shutil
    def onerror(func, p, exc_info):
        try:
            os.chmod(p, stat.S_IWRITE | stat.S_IREAD)
            func(p)
        except Exception:  # noqa: BLE001
            pass
    shutil.rmtree(path, onerror=onerror)


def utc() -> str:
    return datetime.now(timezone.utc).isoformat()


def sha_text(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def sha_file(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def load(p: Path) -> Any:
    return json.loads(p.read_text("utf-8"))


def task_ids() -> List[str]:
    return sorted(p.stem for p in (PUB / "cases").glob("*.json"))


def prepare(cid: str):
    """Public-only preparation.  Mirrors cd.prepare() minus truth reads."""
    spec = load(PUB / "cases" / f"{cid}.json")
    rel = spec["base"]["file"]
    patched = (PUB / "evidence" / cid / "patched" / Path(rel).name) \
        .read_text("utf-8").splitlines(keepends=True)
    public = "".join(line if not cd._MARKER.match(line) else "\n"
                     for line in patched)
    a_line = int(spec["base"]["A_line"])
    payloads = [{"id": f"in{i + 1}"} for i in range(len(spec["inputs"]))]
    key_map = {f"in{i + 1}": key for i, key in enumerate(spec["inputs"])}

    # v2.1 case `probe` still points at the legacy tree -> explicit remap.
    declared = _norm(spec["probe"])
    probe = HELDOUT / "probes" / f"{cid}.py"
    assert probe.exists(), f"missing v2.1 probe for {cid}: {probe}"
    assert Path(declared).name == probe.name, (declared, probe.name)

    meta = cd.stage0_row(spec["base"]["slug"])
    root = (cd.DS / "discovery" / meta["root"]).resolve()
    work = RAWDIR / "work" / cid
    if work.exists():
        _rmtree_force(work)
    work.mkdir(parents=True, exist_ok=True)
    executor = BlindExecutor(spec["base"]["slug"], root, rel, patched, a_line,
                             probe, key_map, work)
    # Compatibility fix (no algorithmic change): SDExecutor derives its variant
    # top from rel.split("/")[0].  For a top-level module file (rel has no
    # directory component) that is a file, so the hardlink tree fails.  Link
    # the whole project directory instead.
    top_remap = None
    if not (executor.root / executor.top).is_dir():
        top_remap = {"from": executor.top, "to": ".",
                     "reason": ("top-level module file; link the whole project "
                                "root instead of a path component")}
        executor.top = "."
    return {
        "spec": spec, "rel": rel, "public": public, "a_line": a_line,
        "payloads": payloads, "key_map": key_map, "executor": executor,
        "probe_declared": declared, "probe_resolved": str(probe),
        "probe_sha256": sha_file(probe),
        "public_sha256": sha_text(public),
        "top_remap": top_remap,
    }


def ops_index(ops: Sequence[dict]) -> Dict[str, dict]:
    return {op["id"]: {"id": op["id"],
                       "after_line": op.get("after_line"),
                       "code": op.get("code") or op.get("text"),
                       "sources": op.get("sources")} for op in ops}


def gate(executor, payload):
    """Public masking gate, identical to the frozen DEV code."""
    plus = executor.observation([], "plus", payload)
    minus = executor.observation([], "minus", payload)
    if plus.get("__probe_error__") or minus.get("__probe_error__"):
        return False, "probe_error", plus, minus
    if not executor.a_executes(payload):
        return False, "A_NOT_EXECUTED", plus, minus
    if plus.get("outcome") != "return":
        return False, "PLUS_NOT_RETURN", plus, minus
    if plus != minus:
        return False, "A_DELETION_CHANGES_OUTPUT", plus, minus
    return True, "PUBLIC_MASKING_CANDIDATE", plus, minus


# ---------------------------------------------------------------- C0 blind
def run_c0(cid: str) -> dict:
    ctx = prepare(cid)
    spec, public = ctx["spec"], ctx["public"]
    executor, payloads, key_map = (ctx["executor"], ctx["payloads"],
                                   ctx["key_map"])
    rel, a_line = ctx["rel"], ctx["a_line"]
    task = {"file": rel, "target_operation": {
        "file": rel, "line": a_line, "code": spec["base"]["A_code"]}}

    started = time.perf_counter()
    probes_before = executor.probe_executions
    found = cd.discover(task, public)
    executor.set_universe(found["candidate_ops"])
    pruned = cd.rank_and_prune(executor, found, payloads, MAX_OPS)
    universe = pruned["universe"]
    executor.set_universe(universe)
    ids = [op["id"] for op in universe]

    predictions, rows = {}, {}
    for payload in payloads:
        key = key_map[payload["id"]]
        ok, reason, _plus, _minus = gate(executor, payload)
        row: Dict[str, Any] = {"gate": reason}
        if ok:
            res = cd.search_relations_role_separated(
                executor, payload, ids, budget=BUDGET)
            sets = res.get("msms_ids") or []
            row.update({
                "search_complete": bool(res.get("complete")),
                "search_subsets_total": res.get("subsets_total"),
                "search_evaluations": res.get("evaluations"),
                "SEARCH_INCOMPLETE": None if res.get("complete")
                else "SEARCH_INCOMPLETE",
            })
        else:
            sets = []
            row.update({"search_complete": None, "search_subsets_total": None,
                        "search_evaluations": None, "SEARCH_INCOMPLETE": None})
        row["sets"] = [list(s) for s in sets]
        rows[key] = row
        predictions[key] = {
            "public_id": payload["id"], "predicted_kept_sets": [list(s) for s in sets],
            "n_sets": len(sets),
        }
    wall = round(time.perf_counter() - started, 3)
    return {
        "task_id": cid, "method": "c0", "mechanism": spec["mechanism"],
        "status": "OK",
        "input_keys": list(spec["inputs"]),
        "probe_declared": ctx["probe_declared"],
        "probe_resolved": ctx["probe_resolved"],
        "probe_sha256": ctx["probe_sha256"],
        "public_source_sha256": ctx["public_sha256"],
        "top_remap": ctx["top_remap"],
        "universe": universe,
        "ops": ops_index(universe),
        "discovery": {k: pruned.get(k) for k in (
            "considered", "dropped_no_effect", "dropped_duplicate_effect",
            "truncated")},
        "per_input": rows,
        "predictions": predictions,
        "cost": {"wall_seconds": wall,
                 "probe_executions": executor.probe_executions,
                 "probe_executions_algorithm":
                     executor.probe_executions - probes_before,
                 "variant_builds": executor.variant_builds},
    }


# -------------------------------------------------------------- Full blind
def run_full(cid: str, client: QwenClient) -> dict:
    ctx = prepare(cid)
    spec, public = ctx["spec"], ctx["public"]
    executor, payloads, key_map = (ctx["executor"], ctx["payloads"],
                                   ctx["key_map"])
    rel, a_line = ctx["rel"], ctx["a_line"]
    a_code = spec["base"]["A_code"]
    task = {"file": rel, "target_operation": {
        "file": rel, "line": a_line, "code": a_code}}

    started = time.perf_counter()
    probes_before = executor.probe_executions

    catalog = cd.build_catalog(public, rel, a_line, task)
    graph = cd.sg.build(task, public)

    # C0 universe computed blind (same algorithm, no reference scoring).
    found = cd.discover(task, public)
    executor.set_universe(found["candidate_ops"])
    pruned = cd.rank_and_prune(executor, found, payloads, MAX_OPS)
    u_graph = pruned["universe"]
    executor.set_universe(u_graph)
    u_graph_map = {op["id"]: op for op in u_graph}
    ast_exec = {op["id"]: op for op in catalog["executable"]}
    controls = {op["id"]: op for op in catalog["control_contexts"]}

    traces = []
    for payload in payloads:
        plus = executor.observation([], "plus", payload)
        minus = executor.observation([], "minus", payload)
        side_plus = cd.trace_run(executor, payload, "plus")
        side_minus = cd.trace_run(executor, payload, "minus")
        same = (not plus.get("__probe_error__")
                and not minus.get("__probe_error__") and plus == minus)
        single_effects = []
        for op in u_graph:
            after = executor.observation([op["id"]], "plus", payload)
            if after != plus:
                single_effects.append(op["id"])
        plus_lines, minus_lines = set(side_plus["lines"]), set(side_minus["lines"])
        traces.append({
            "input": payload["id"],
            "plus": cd.observation_text(plus),
            "minus": cd.observation_text(minus),
            "a_deletion": ("same" if same else "different"),
            "executed_plus": cd.compress_lines(side_plus["lines"]),
            "executed_minus": cd.compress_lines(side_minus["lines"]),
            "executed_only_plus": cd.compress_lines(plus_lines - minus_lines),
            "executed_only_minus": cd.compress_lines(minus_lines - plus_lines),
            "u_graph_single_delete_changes": single_effects,
            "unexplained_by_u_base": bool(not same and not single_effects),
            "trace_plus_lines": side_plus["lines"],
            "trace_minus_lines": side_minus["lines"],
        })

    prompt = cd.build_prompt(cid, rel, a_line, a_code, public, catalog,
                             graph, u_graph, traces, len(payloads))
    messages = [
        {"role": "system", "content": (
            "You analyse Python masking relations. Return one JSON object "
            "only. Use exact executable operation ids from U_ast; control "
            "regions and function boundaries are not operations.")},
        {"role": "user", "content": prompt},
    ]
    prompt_sha = sha_text(prompt)
    print(f"[{cid}] prompt chars={len(prompt)} U_ast={len(ast_exec)} "
          f"U_graph={len(u_graph)}", flush=True)

    call_started = time.perf_counter()
    try:
        response = client.chat(messages, purpose=f"cd_v2_{cid}",
                               json_mode=True)
        call = {"ok": True, "raw_response": response.content,
                "stats": response.stats,
                "wall_seconds": round(time.perf_counter() - call_started, 3)}
    except Exception as exc:  # noqa: BLE001 -- one call, no retry
        call = {"ok": False, "raw_response": "", "stats": None,
                "wall_seconds": round(time.perf_counter() - call_started, 3),
                "error": f"{type(exc).__name__}: {exc}"}
    (RAWDIR / "raw").mkdir(parents=True, exist_ok=True)
    (RAWDIR / "raw" / f"{cid}.json").write_text(json.dumps({
        "task_id": cid, "messages": messages,
        "raw_response": call.get("raw_response"),
        "stats": call.get("stats"), "wall_seconds": call.get("wall_seconds"),
        "prompt_sha256": prompt_sha,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    if not call["ok"]:
        return {
            "task_id": cid, "method": "full", "mechanism": spec["mechanism"],
            "status": "MODEL_UNAVAILABLE", "call": call,
            "prompt_sha256": prompt_sha, "input_keys": list(spec["inputs"]),
            "public_source_sha256": ctx["public_sha256"],
            "top_remap": ctx["top_remap"],
            "predictions": {}, "per_input": {},
            "cost": {"wall_seconds": round(time.perf_counter() - started, 3),
                     "probe_executions": executor.probe_executions},
        }

    parsed_answer = cd.parse_answer(call["raw_response"])
    qwen = cd.collect_qwen(parsed_answer["object"], ast_exec, u_graph_map,
                           controls) if parsed_answer["ok"] else {
        "candidates": [], "rejected_candidates": [], "mapping": [],
        "candidate_sets": [], "rejected_sets": [],
        "stats": {"proposed": 0, "mapped": 0, "rejected": 0,
                  "sets_proposed": 0, "sets_accepted": 0, "sets_rejected": 0}}
    u_qwen = qwen["candidates"]
    u_union = cd.union_ops(u_graph, u_qwen)
    executor.set_universe(u_union)
    union_ids = [op["id"] for op in u_union]
    union_map = {op["id"]: op for op in u_union}

    pruning = {"policy": "retain_all_graph_and_qwen_candidates",
               "candidates": [], "u_ast_not_selected": []}
    for op in u_union:
        sig, changed, total = cd._signature(executor, op, payloads)
        pruning["candidates"].append({
            "id": op["id"], "sources": op.get("sources", []),
            "changed_cells": changed, "cells": total,
            "zero_effect": changed == 0,
            "retained_reason": ("qwen_candidate_for_verification"
                                if "qwen" in op.get("sources", [])
                                else "graph_candidate_retained_even_if_zero_effect"),
        })
    selected = {op["id"] for op in u_union}
    pruning["u_ast_not_selected"] = [
        {"id": op["id"], "reason": "not_proposed_by_graph_or_qwen"}
        for op in catalog["executable"] if op["id"] not in selected]

    # C0 diagnostics (public, same as DEV).
    executor.set_universe(u_graph)
    c0_diag = []
    for op in u_graph:
        sig, changed, total = cd._signature(executor, op, payloads)
        c0_diag.append({"id": op["id"], "changed_cells": changed,
                        "cells": total, "zero_effect": changed == 0})
    executor.set_universe(u_union)

    # Public masking-input detection: no hidden reference read.
    public_masking = []
    for payload in payloads:
        plus = executor.observation([], "plus", payload)
        minus = executor.observation([], "minus", payload)
        if (executor.a_executes(payload)
                and not plus.get("__probe_error__")
                and not minus.get("__probe_error__")
                and plus.get("outcome") == "return" and plus == minus):
            public_masking.append(payload)

    search_rows, verification_rows = {}, {}
    predictions, per_input = {}, {}
    for payload in payloads:
        key = key_map[payload["id"]]
        plus = executor.observation([], "plus", payload)
        minus = executor.observation([], "minus", payload)
        if plus.get("__probe_error__") or minus.get("__probe_error__"):
            reason = "probe_error"
        elif not executor.a_executes(payload):
            reason = "A_NOT_EXECUTED"
        elif plus.get("outcome") != "return":
            reason = "PLUS_NOT_RETURN"
        elif plus != minus:
            reason = "A_DELETION_CHANGES_OUTPUT"
        else:
            reason = "PUBLIC_MASKING_CANDIDATE"
        per_input[key] = {"public_id": payload["id"], "gate": reason}
        predictions[key] = {"public_id": payload["id"],
                            "predicted_sets": [], "n_sets": 0}

    for payload in public_masking:
        key = key_map[payload["id"]]
        hypotheses = {"msms": [
            {"kept_ops": item["kept_operations"]}
            for item in qwen["candidate_sets"][:8]], "mmbs": []}
        search_started = time.perf_counter()
        result = cd.search_relations_role_separated(
            executor, payload, union_ids, budget=BUDGET,
            hypotheses=hypotheses, max_hypothesis_probes_per_role=3)
        result["wall_seconds"] = round(time.perf_counter() - search_started, 3)
        search_rows[key] = result
        search_sets = result.get("msms_ids") or []
        candidates = cd.candidate_sets_for_verification(
            qwen["candidate_sets"], u_qwen, u_graph, search_sets)
        verification = cd.verify_candidate_sets(
            executor, union_ids, candidates, payload)
        verification["search_incomplete"] = not result.get("complete")
        verification["search_subsets_total"] = result.get("subsets_total")
        verification["search_evaluations"] = result.get("evaluations")
        verification["search_budget"] = BUDGET
        verification["SEARCH_INCOMPLETE"] = (
            "SEARCH_INCOMPLETE" if not result.get("complete") else None)
        verification_rows[key] = verification
        confirmed = verification["confirmed"]
        per_input[key].update({
            "search_complete": bool(result.get("complete")),
            "bootstrap_sets": [list(s) for s in search_sets],
            "confirmed_sets": [list(s) for s in confirmed],
            "SEARCH_INCOMPLETE": verification["SEARCH_INCOMPLETE"],
        })
        predictions[key] = {
            "public_id": payload["id"],
            "predicted_sets": [list(s) for s in confirmed],
            "n_sets": len(confirmed),
        }

    wall = round(time.perf_counter() - started, 3)
    return {
        "task_id": cid, "method": "full", "mechanism": spec["mechanism"],
        "status": "OK" if parsed_answer["ok"] else "INVALID_OUTPUT",
        "input_keys": list(spec["inputs"]),
        "probe_declared": ctx["probe_declared"],
        "probe_resolved": ctx["probe_resolved"],
        "probe_sha256": ctx["probe_sha256"],
        "public_source_sha256": ctx["public_sha256"],
        "top_remap": ctx["top_remap"],
        "prompt_sha256": prompt_sha,
        "parsed_answer_ok": parsed_answer["ok"],
        "parsed_answer_error": parsed_answer["error"],
        "call": call,
        "u_ast_counts": catalog["counts"],
        "u_graph": u_graph,
        "u_graph_map": ops_index(u_graph),
        "u_qwen": u_qwen,
        "u_union": u_union,
        "ops": ops_index(u_union),
        "qwen": qwen,
        "pruning": pruning,
        "c0_diagnostics": c0_diag,
        "traces": traces,
        "search": search_rows,
        "verification": verification_rows,
        "per_input": per_input,
        "predictions": predictions,
        "cost": {
            "wall_seconds": wall,
            "probe_executions": executor.probe_executions,
            "probe_executions_algorithm":
                executor.probe_executions - probes_before,
            "variant_builds": executor.variant_builds,
        },
    }


def write_output(method: str, tasks: Dict[str, Any], started: float,
                 totals: Dict[str, Any], model_info: Dict[str, Any],
                 order: List[str], deadline_s: int) -> Path:
    name = ("MACE_HELDOUT_v2_1_C0_predictions.json" if method == "c0"
            else "MACE_HELDOUT_v2_1_Full_predictions.json")
    out = OUTDIR / name
    payload = {
        "schema": f"mace-heldout-v2.1-{method}-predictions/1",
        "generated_utc": utc(),
        "split": "HELDOUT",
        "method": "C0" if method == "c0" else "Full MACE + Qwen",
        "scored": False,
        "dataset_root": str(HELDOUT),
        "public_source_root": str(PUB),
        "task_order": order,
        "model": model_info,
        "frozen_config": {
            "budget_per_input": BUDGET, "max_ops": MAX_OPS,
            "search": "search_relations_role_separated",
            "verification": ("verify_candidate_sets (strict minimality; "
                             "UNKNOWN != FALSE)"),
            "qwen_calls_per_task": 1 if method == "full" else 0,
            "temperature": TEMPERATURE, "seed": SEED,
            "num_ctx": NUM_CTX if method == "full" else None,
            "num_predict": NUM_PREDICT if method == "full" else None,
            "retries": 0,
        },
        "runtime_policy": {"deadline_seconds": deadline_s,
                           "elapsed_seconds": round(time.perf_counter() - started, 2),
                           "no_truth_access_guard": True},
        "guard": {
            "forbidden_markers": list(FORBIDDEN_MARKERS),
            "violations": list(VIOLATIONS),
            "opened_paths_count": len(ACCESS_LOG),
        },
        "tasks": tasks,
        "totals": totals,
    }
    OUTDIR.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                   encoding="utf-8")
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--method", choices=["c0", "full", "both"], required=True)
    ap.add_argument("--tasks", nargs="+")
    ap.add_argument("--deadline-seconds", type=int, default=45 * 60)
    args = ap.parse_args()
    RAWDIR.mkdir(parents=True, exist_ok=True)
    ids = args.tasks or task_ids()
    order = list(ids)
    started = time.perf_counter()

    model_info = {"name": MODEL, "endpoint": ENDPOINT,
                  "options": {"temperature": TEMPERATURE, "seed": SEED,
                              "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT,
                              "retries": 0}}

    if args.method in ("c0", "both"):
        tasks, totals = {}, {"tasks_completed": 0, "tasks_incomplete": 0,
                             "inputs": 0, "probes": 0, "wall_seconds": 0.0,
                             "search_incomplete_inputs": 0}
        remaining = [c for c in ids]
        if args.method == "both":
            remaining = ids
        for cid in remaining:
            if time.perf_counter() - started > args.deadline_seconds:
                for rest in ids[ids.index(cid):]:
                    tasks[rest] = {"task_id": rest, "status": "INCOMPLETE",
                                   "reason": "deadline reached"}
                    totals["tasks_incomplete"] += 1
                break
            try:
                rec = run_c0(cid)
            except Exception as exc:  # noqa: BLE001 -- record, never fabricate
                import traceback
                rec = {"task_id": cid, "method": "c0", "status": "RUN_ERROR",
                       "error": f"{type(exc).__name__}: {exc}",
                       "traceback_tail": traceback.format_exc()[-2000:],
                       "predictions": {}, "per_input": {}}
            tasks[cid] = rec
            if rec["status"] != "OK":
                totals["tasks_incomplete"] += 1
                print(f"[c0 {cid}] {rec['status']}: {rec.get('error')}", flush=True)
            else:
                totals["tasks_completed"] += 1
                totals["inputs"] += len(rec["input_keys"])
                totals["probes"] += rec["cost"]["probe_executions"]
                totals["wall_seconds"] = round(
                    totals["wall_seconds"] + rec["cost"]["wall_seconds"], 3)
                if any(r.get("SEARCH_INCOMPLETE")
                       for r in rec["per_input"].values()):
                    totals["search_incomplete_inputs"] += 1
                print(f"[c0 {cid}] sets="
                      f"{sum(v['n_sets'] for v in rec['predictions'].values())} "
                      f"probes={rec['cost']['probe_executions']} "
                      f"wall={rec['cost']['wall_seconds']}s", flush=True)
            out = write_output("c0", tasks, started, totals, model_info,
                               order, args.deadline_seconds)
        out = write_output("c0", tasks, started, totals, model_info,
                           order, args.deadline_seconds)
        print(f"wrote {out}", flush=True)

    if args.method in ("full", "both"):
        client = QwenClient(provider="ollama", model=MODEL, endpoint=ENDPOINT,
                            num_ctx=NUM_CTX, num_predict=NUM_PREDICT,
                            temperature=TEMPERATURE, seed=SEED, timeout=900,
                            retries=0)
        tasks = {}
        totals = {"tasks_completed": 0, "tasks_incomplete": 0, "inputs": 0,
                  "probes": 0, "wall_seconds": 0.0, "qwen_calls": 0,
                  "prompt_tokens": 0, "completion_tokens": 0,
                  "search_incomplete_inputs": 0}
        started_full = time.perf_counter()
        # In "both" mode Window A is a single 45-minute budget covering C0+Full.
        budget_origin = started if args.method == "both" else started_full
        for cid in ids:
            if time.perf_counter() - budget_origin > args.deadline_seconds:
                for rest in ids[ids.index(cid):]:
                    tasks[rest] = {"task_id": rest, "status": "INCOMPLETE",
                                   "reason": "deadline reached"}
                    totals["tasks_incomplete"] += 1
                break
            try:
                rec = run_full(cid, client)
            except Exception as exc:  # noqa: BLE001 -- record, never fabricate
                import traceback
                rec = {"task_id": cid, "method": "full", "status": "RUN_ERROR",
                       "error": f"{type(exc).__name__}: {exc}",
                       "traceback_tail": traceback.format_exc()[-2000:],
                       "predictions": {}, "per_input": {}}
            tasks[cid] = rec
            if rec["status"] in ("OK", "INVALID_OUTPUT"):
                totals["tasks_completed"] += 1
                totals["qwen_calls"] += 1
                stats = (rec.get("call") or {}).get("stats") or {}
                totals["prompt_tokens"] += stats.get("prompt_tokens") or 0
                totals["completion_tokens"] += stats.get("completion_tokens") or 0
            else:
                totals["tasks_incomplete"] += 1
            totals["inputs"] += len(rec.get("input_keys") or [])
            totals["probes"] += rec.get("cost", {}).get("probe_executions", 0)
            totals["wall_seconds"] = round(
                totals["wall_seconds"] + rec.get("cost", {}).get("wall_seconds", 0), 3)
            if any(v.get("SEARCH_INCOMPLETE")
                   for v in (rec.get("per_input") or {}).values()):
                totals["search_incomplete_inputs"] += 1
            out = write_output("full", tasks, started_full, totals, model_info,
                               order, args.deadline_seconds)
            print(f"[full {cid}] status={rec['status']} "
                  f"confirmed={sum(v.get('n_sets', 0) for v in rec.get('predictions', {}).values())} "
                  f"u_qwen={len(rec.get('u_qwen', []))} "
                  f"probes={rec.get('cost', {}).get('probe_executions')} "
                  f"wall={rec.get('cost', {}).get('wall_seconds')}s", flush=True)
        out = write_output("full", tasks, started_full, totals, model_info,
                           order, args.deadline_seconds)
        print(f"wrote {out}", flush=True)

    if VIOLATIONS:
        print(f"BLIND-GUARD VIOLATIONS: {VIOLATIONS}", flush=True)
        return 2
    print(f"[guard] no truth access; opened={len(ACCESS_LOG)} files", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
