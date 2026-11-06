"""Direct GLM baseline on MACE-Bench v2.1 (DEV scoring, HELDOUT blind).

Reuses the frozen Direct-Qwen protocol: same public view, same prompt
template, same JSON schema/parser, same 8192/4096 limits, one call per task,
no retries, no search, no verifier, no candidate universe.

HELDOUT: only cases/ and evidence/<cid>/patched/ are read.  reference.json,
enumeration.json and acceptance are never opened for HELDOUT.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import statistics
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

from sd_algorithm_pilot import block_spans, family, load, project_containment, _MARKER  # noqa: E402
from open_ops.semantic_relations import SourceIndex, map_proposal, numbered_source  # noqa: E402
from mace.qwen import QwenClient  # noqa: E402
from scripts.run_direct_qwen_baseline import parse_relations  # noqa: E402
from scripts.run_sd_direct_vs_full import direct_prompt  # noqa: E402

V21 = KIT / "benchmark_v4_dataset" / "source_derived_v2_1"
MODEL = "glm-4.7-flash:q4_K_M"
ENDPOINT = "http://127.0.0.1:11434"
NUM_CTX = 8192
NUM_PREDICT = 4096
TEMPERATURE = 0.0
SEED = 42
TIMEOUT = 900
RUN = Path(os.environ.get("MACE_RUN_DIR", KIT / "runs" / "direct_glm_v2_1"))

DEV_TASKS = sorted(p.stem for p in (V21 / "cases").glob("*.json"))
HELDOUT_TASKS = sorted(p.stem for p in (V21 / "heldout" / "cases").glob("*.json"))
SMOKE = ["sd_tabulate_1052_strip_right", "sd_coverage_glob_backslash_m2",
         "sd_humanize_filesize_gnu_m5"]


class GLMClient(QwenClient):
    """Ollama client with GLM thinking disabled (JSON answer only)."""

    def _post(self, path: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        payload = dict(payload)
        payload["think"] = False
        payload["keep_alive"] = "30m"
        return super()._post(path, payload)


def sha(s: str) -> str:
    return hashlib.sha256(s.encode("utf-8")).hexdigest()


def root(split: str) -> Path:
    return V21 if split == "dev" else V21 / "heldout"


def public_view(split: str, cid: str):
    base = root(split)
    spec = load(base / "cases" / f"{cid}.json")
    rel = spec["base"]["file"]
    patched = (base / "evidence" / cid / "patched" / Path(rel).name) \
        .read_text("utf-8").splitlines(keepends=True)
    source = "".join(line if not _MARKER.match(line) else "\n" for line in patched)
    return spec, rel, source, int(spec["base"]["A_line"]), spec["base"]["A_code"]


def call(client: QwenClient, messages: List[dict], purpose: str) -> dict:
    started = time.perf_counter()
    try:
        response = client.chat(messages, purpose=purpose, json_mode=True)
        stats = dict(response.stats or {})
        stats["wall_seconds"] = round(time.perf_counter() - started, 3)
        return {"ok": True, "messages": messages,
                "raw_response": response.content, "stats": stats,
                "model": client.model}
    except Exception as exc:  # noqa: BLE001 - never retry
        return {"ok": False, "messages": messages, "raw_response": "",
                "stats": {"wall_seconds": round(time.perf_counter() - started, 3)},
                "model": client.model, "error": f"{type(exc).__name__}: {exc}"}


def map_direct(raw: str, rel: str, source: str, a_line: int):
    relations, parse_error = parse_relations(raw)
    index = SourceIndex.from_source(rel, source)
    mapped, rejected = [], []
    for relation in relations:
        ops, bad = [], []
        for proposal in relation.get("operations") or []:
            result = map_proposal(proposal, index, graph_ops=None, style="v3",
                                  exclude_lines=[a_line])
            if result["status"] == "mapped":
                ops.append(result["op"])
            else:
                bad.append(result)
        if bad or not ops:
            rejected.append({"relation": relation, "rejected": bad})
            continue
        by_id = {op["id"]: op for op in ops}
        mapped.append({"operations": list(by_id.values()),
                       "condition": relation.get("condition"),
                       "rationale": relation.get("rationale")})
    return mapped, rejected, parse_error


def score_sets(sets: Sequence[Sequence[str]], ops_by_id: dict, spans: dict,
               hidden_msms: Sequence[Sequence[str]]):
    want = family(hidden_msms)
    hits = [project_containment(s, ops_by_id, spans) for s in sets]
    got = family([h[0] for h in hits])
    stray = [o for h in hits for o in h[1]]
    tp = len(got & want)
    return {
        "hidden_msms": sorted(sorted(s) for s in hidden_msms),
        "got_msms_blocks": sorted(sorted(s) for s in got),
        "stray_ops": stray,
        "msms_exact": bool(got == want and not stray),
        "precision": round(tp / len(got), 4) if got else 0.0,
        "recall": round(tp / len(want), 4) if want else 0.0,
        "false_relations": len(got - want) + len(stray),
        "unmatched_sets": sum(1 for h in hits if not h[0]),
    }


def run_task(client: QwenClient, split: str, cid: str) -> dict:
    spec, rel, source, a_line, a_code = public_view(split, cid)
    n_inputs = len(spec["inputs"])
    input_keys = list(spec["inputs"])
    payloads = [{"id": f"in{i + 1}"} for i in range(n_inputs)]
    key_map = {f"in{i + 1}": k for i, k in enumerate(input_keys)}
    messages = [
        {"role": "system", "content": (
            "You analyse Python masking relations. Return one JSON object "
            "only. Every operation must cite a real file, line and source text.")},
        {"role": "user", "content": direct_prompt(
            cid, rel, source, a_line, a_code, n_inputs)},
    ]
    rec: Dict[str, Any] = {
        "task_id": cid, "split": split.upper(), "mechanism": spec["mechanism"],
        "model": MODEL,
        "options": {"temperature": TEMPERATURE, "seed": SEED,
                    "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT,
                    "retries": 0, "timeout_s": TIMEOUT, "think": False},
        "public_source_sha256": sha(source),
        "prompt_sha256": sha(messages[1]["content"]),
        "prompt_chars": len(messages[1]["content"]),
        "declared_inputs": n_inputs,
    }
    call_rec = call(client, messages, f"direct_glm_{split}_{cid}")
    rec["call"] = call_rec
    stats = call_rec["stats"]
    rec["prompt_tokens"] = stats.get("prompt_tokens")
    rec["completion_tokens"] = stats.get("completion_tokens")
    rec["runtime_s"] = stats.get("wall_seconds")
    rec["done_reason"] = (stats or {}).get("done_reason")
    rec["context_limit"] = NUM_CTX
    rec["context_truncated_suspected"] = bool(
        rec["prompt_tokens"] and rec["prompt_tokens"] >= NUM_CTX - 8)
    parsed, rejected, parse_error = map_direct(
        call_rec.get("raw_response") or "", rel, source, a_line)
    rec["parsed_sets"] = [{
        "ids": [op["id"] for op in r["operations"]], "ops": r["operations"],
        "condition": r["condition"], "rationale": r["rationale"]} for r in parsed]
    rec["rejected"] = rejected
    rec["parse_error"] = parse_error

    if split == "dev":
        reference = load(V21 / "tasks" / cid / "reference.json")
        enumeration = load(V21 / "evidence" / cid / "enumeration.json")
        spans = block_spans(enumeration)
        ops_by_id = {op["id"]: op for r in parsed for op in r["operations"]}
        sets = [[op["id"] for op in r["operations"]] for r in parsed]
        detail = []
        agg = {"masking_inputs": 0, "exact": 0, "false_relations": 0,
               "unmatched_sets": 0, "precision_sum": 0.0, "recall_sum": 0.0,
               "mmbs_domain": 0, "mmbs_exact": 0}
        for payload in payloads:
            key = key_map[payload["id"]]
            hidden = reference["inputs"][key]
            if hidden.get("role") != "masking":
                continue
            score = score_sets(sets, ops_by_id, spans, hidden["msms"])
            mmbs = hidden.get("mmbs") or []
            mmbs_ok = None
            if hidden.get("mmbs_status") != "NOT_SEPARABLE" and mmbs:
                agg["mmbs_domain"] += 1
                # Direct protocol does not ask for MMBS: no prediction domain.
                mmbs_ok = None
            agg["masking_inputs"] += 1
            agg["exact"] += int(score["msms_exact"])
            agg["false_relations"] += score["false_relations"]
            agg["unmatched_sets"] += score["unmatched_sets"]
            agg["precision_sum"] += score["precision"]
            agg["recall_sum"] += score["recall"]
            detail.append({"input": key, "public_id": payload["id"],
                           "mmbs_expected": mmbs,
                           "mmbs_status": hidden.get("mmbs_status"),
                           "mmbs_exact": mmbs_ok, "score": score})
        n = agg["masking_inputs"]
        rec["scoring"] = {
            "masking_inputs": n, "exact": agg["exact"],
            "precision": round(agg["precision_sum"] / n, 4) if n else 0.0,
            "recall": round(agg["recall_sum"] / n, 4) if n else 0.0,
            "false_relations": agg["false_relations"],
            "unmatched_sets": agg["unmatched_sets"],
            "mmbs_domain": agg["mmbs_domain"],
            "mmbs_exact": None,
            "mmbs_note": ("Direct protocol does not request MMBS; not scored "
                          "(not counted as wrong or empty)."),
        }
        rec["detail"] = detail
        rec["status"] = "OK" if call_rec["ok"] and parsed else "INVALID_OUTPUT"
        if rec["done_reason"] == "length":
            rec["status"] = "TRUNCATED"
    else:
        rec["status"] = "OK" if call_rec["ok"] and parsed else "INVALID_OUTPUT"
        if rec["done_reason"] == "length":
            rec["status"] = "TRUNCATED"
    return rec


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--split", choices=["dev", "heldout"], required=True)
    ap.add_argument("--tasks", nargs="+")
    ap.add_argument("--smoke", action="store_true")
    ap.add_argument("--out", type=Path)
    ap.add_argument("--resume", action="store_true")
    ap.add_argument("--deadline-seconds", type=int, default=2700)
    args = ap.parse_args()
    if args.tasks:
        tasks = args.tasks
    elif args.split == "dev":
        tasks = DEV_TASKS
    else:
        tasks = HELDOUT_TASKS
    if args.smoke:
        tasks = SMOKE
    out = args.out or (KIT / "results" / (
        "MACE_direct_GLM_v2_1_dev.json" if args.split == "dev"
        else "MACE_direct_GLM_v2_1_heldout_predictions.json"))
    existing: Dict[str, Any] = {}
    if args.resume and out.exists():
        existing = load(out).get("tasks", {})
    client = GLMClient(provider="ollama", model=MODEL, endpoint=ENDPOINT,
                       num_ctx=NUM_CTX, num_predict=NUM_PREDICT,
                       temperature=TEMPERATURE, seed=SEED, timeout=TIMEOUT,
                       retries=0)
    payload = {
        "schema": f"mace-direct-glm-v2.1-{args.split}/1",
        "split": args.split.upper(),
        "model": MODEL,
        "options": {"temperature": TEMPERATURE, "seed": SEED,
                    "num_ctx": NUM_CTX, "num_predict": NUM_PREDICT,
                    "retries": 0, "timeout_s": TIMEOUT, "think": False},
        "protocol": ("Direct only: one model call per task, no candidate "
                     "universe, no graph/AST expansion, no search, no verifier."),
        "tasks": dict(existing),
    }
    RUN.mkdir(parents=True, exist_ok=True)
    out.parent.mkdir(parents=True, exist_ok=True)
    started = time.perf_counter()
    for cid in tasks:
        if cid in payload["tasks"]:
            print(f"[{cid}] skipped (resume)", flush=True)
            continue
        if time.perf_counter() - started > args.deadline_seconds:
            print(f"[deadline] stopping before {cid}", flush=True)
            break
        rec = run_task(client, args.split, cid)
        payload["tasks"][cid] = rec
        raw = RUN / args.split / f"{cid}.json"
        raw.parent.mkdir(parents=True, exist_ok=True)
        raw.write_text(json.dumps(rec, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        out.write_text(json.dumps(payload, ensure_ascii=False, indent=2),
                       encoding="utf-8")
        sc = rec.get("scoring") or {}
        print(f"[{cid}] status={rec['status']} "
              f"exact={sc.get('exact', '-')}/{sc.get('masking_inputs', '-')} "
              f"rt={rec.get('runtime_s')}s pt={rec.get('prompt_tokens')} "
              f"ct={rec.get('completion_tokens')} done={rec.get('done_reason')}",
              flush=True)
    print(f"wrote {out}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
