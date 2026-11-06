"""Run one Direct Qwen baseline on the frozen blind task.

The model receives only the frozen public task and the public submission
schema.  The raw response is written to disk *before* any private label is
read for scoring.  Scoring is a separate, documented step: it never edits the
answer and never feeds private information back to the model.

Run:
    python scripts/run_blind_baseline.py --model-path D:/tmp/qwen15b
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mace.qwen import extract_json  # noqa: E402
from scripts.blind_probe_methods import direct_qwen_prompt  # noqa: E402

OUT = ROOT / "benchmark_blind_v1"
PUBLIC = OUT / "public" / "task_01_parse_header_links.json"
SCHEMA = OUT / "public" / "SUBMISSION_SCHEMA.json"
FREEZE = OUT / "FREEZE.json"
PRIVATE = OUT / "private" / "task_01_oracle.json"
RUN_DIR = OUT / "executability"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def normalize_obs(value: Any) -> Any:
    """Type-aware observation form matching the frozen oracle's encoding."""
    if isinstance(value, dict):
        return {"dict": sorted((normalize_obs(k), normalize_obs(v)) for k, v in value.items())}
    if isinstance(value, (list, tuple)):
        return ["seq", [normalize_obs(v) for v in value]]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", value]
    if isinstance(value, str):
        return ["str", value]
    if value is None:
        return ["none"]
    return [type(value).__name__, repr(value)]


def run(source: str, entry: str, value: Any) -> Any:
    namespace: Dict[str, Any] = {"__name__": "__blind_eval__"}
    exec(compile(source, "<frozen-task>", "exec"), namespace)  # noqa: S102
    try:
        return ["return", normalize_obs(namespace[entry](value))]
    except Exception as exc:  # noqa: BLE001
        return ["raise", type(exc).__name__, str(exc)]


def allowed_guard_ast(node: ast.AST) -> bool:
    if isinstance(node, ast.Constant):
        return isinstance(node.value, (bool, int))
    if isinstance(node, ast.Name):
        return node.id in ("nonempty", "all_special")
    if isinstance(node, (ast.Expression, ast.BoolOp, ast.UnaryOp, ast.Compare,
                         ast.BinOp, ast.Load,
                         ast.And, ast.Or, ast.Not, ast.Add, ast.Sub, ast.Mult,
                         ast.FloorDiv, ast.Mod, ast.USub, ast.UAdd,
                         ast.Eq, ast.NotEq, ast.Lt, ast.LtE, ast.Gt, ast.GtE)):
        return all(allowed_guard_ast(child) for child in ast.iter_child_nodes(node))
    return False


def eval_guard(expr: str, value: str) -> bool:
    tree = ast.parse(expr, mode="eval")
    if not allowed_guard_ast(tree):
        raise ValueError("guard uses syntax outside the public restricted language")
    env = {
        "nonempty": len(value) > 0,
        "all_special": all(ch in " '\"" for ch in value),
        "True": True, "False": False,
    }
    return bool(eval(compile(tree, "<guard>", "eval"),  # noqa: S307
                     {"__builtins__": {}}, env))


def classify_guard(expr: str, cases: List[Dict[str, Any]]) -> Dict[str, Any]:
    false_accept: List[str] = []
    false_reject: List[str] = []
    errors: List[Dict[str, str]] = []
    for case in cases:
        value = case["args"]["value"]
        actual = bool(case["observations_equal"])
        try:
            predicted = eval_guard(expr, value)
        except Exception as exc:  # noqa: BLE001
            errors.append({"case_id": case["case_id"],
                           "error": f"{type(exc).__name__}: {exc}"})
            continue
        if predicted and not actual:
            false_accept.append(case["case_id"])
        elif not predicted and actual:
            false_reject.append(case["case_id"])
    return {
        "status": "INVALID" if errors else "BOUNDED",
        "sound": not false_accept and not errors,
        "complete": not false_reject and not errors,
        "exact": not false_accept and not false_reject and not errors,
        "false_accept": false_accept,
        "false_reject": false_reject,
        "errors": errors,
        "evidence_level": "BOUNDED",
        "note": "Finite hidden-eval check only; never PROVEN.",
    }


def score_masking(answer: Dict[str, Any], probes: List[Dict[str, Any]]) -> Dict[str, Any]:
    submitted = {}
    raw = ((answer.get("masking") or {}).get("probes") or [])
    if isinstance(raw, list):
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("probe_id"), str):
                submitted[item["probe_id"]] = item
    rows = []
    for probe in probes:
        pid = probe["case_id"]
        expected_sets = sorted({tuple(sorted(s)) for s in probe["minimal_masking_sets"]})
        expected_kind = probe["masking_type"]
        item = submitted.get(pid)
        if item is None:
            rows.append({"probe_id": pid, "status": "uncovered",
                         "expected_sets": [list(s) for s in expected_sets],
                         "expected_kind": expected_kind})
            continue
        sets = item.get("absorber_sets")
        got_sets = []
        if isinstance(sets, list):
            for s in sets:
                if isinstance(s, list) and all(isinstance(x, str) for x in s):
                    got_sets.append(tuple(sorted(s)))
        got_sets = sorted(set(got_sets))
        got_kind = item.get("kind")
        exact = got_sets == expected_sets and got_kind == expected_kind
        rows.append({
            "probe_id": pid, "status": "exact" if exact else "wrong",
            "got_sets": [list(s) for s in got_sets], "got_kind": got_kind,
            "expected_sets": [list(s) for s in expected_sets],
            "expected_kind": expected_kind,
        })
    return {
        "probes": rows,
        "exact": all(r["status"] == "exact" for r in rows),
        "covered": sum(r["status"] != "uncovered" for r in rows),
        "total": len(rows),
    }


def score_counterexample(answer: Dict[str, Any], public: Dict[str, Any],
                         oracle: Dict[str, Any]) -> Dict[str, Any]:
    claim = (answer.get("counterexample") or {}).get("claim")
    value = (answer.get("counterexample") or {}).get("value")
    exposed = [c for c in oracle["eval_cases"]
               if not c["observations_equal"]]
    result = {"claim": claim, "value": value, "valid": None,
              "hidden_exposed_count": len(exposed), "status": "unscored"}
    if claim == "exists":
        if not isinstance(value, str):
            result.update({"status": "invalid_submission", "valid": False})
            return result
        obs_plus = run(public["program"]["source"], public["program"]["entry"], value)
        obs_minus = run(public["deletion"]["p_minus_source"],
                        public["program"]["entry"], value)
        result["observation_plus"] = obs_plus
        result["observation_minus"] = obs_minus
        result["valid"] = obs_plus != obs_minus
        result["status"] = "correct" if result["valid"] else "invalid_witness"
    elif claim == "none_exists":
        result["status"] = "wrong_none_exists_claim" if exposed else "correctly_none_exists"
    elif claim == "none_found":
        result["status"] = "none_found_not_a_proof"
    return result


def score_test_gap(answer: Dict[str, Any], oracle: Dict[str, Any]) -> Dict[str, Any]:
    expected = {c["case_id"]: c["gap"] for c in oracle["test_cases"]}
    tests = ((answer.get("test_gap") or {}).get("tests") or [])
    submitted = {}
    if isinstance(tests, list):
        for item in tests:
            if isinstance(item, dict) and isinstance(item.get("name"), str):
                submitted[item["name"]] = item.get("verdict")
    rows = []
    for name, gap in expected.items():
        got = submitted.get(name)
        rows.append({"test": name, "expected": gap, "got": got,
                     "status": "uncovered" if got is None else
                               ("correct" if got == gap else "wrong")})
    return {
        "tests": rows,
        "exact": all(r["status"] == "correct" for r in rows),
        "covered": sum(r["status"] != "uncovered" for r in rows),
        "total": len(rows),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--max-new-tokens", type=int, default=1536)
    parser.add_argument("--out-prefix", default="task_01_direct_qwen")
    args = parser.parse_args()

    public = json.loads(PUBLIC.read_text(encoding="utf-8"))
    schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if sha256_bytes(PUBLIC.read_bytes()) != freeze["public_sha256"]:
        raise SystemExit("public task hash mismatch")
    if sha256_bytes(SCHEMA.read_bytes()) != freeze["public_schema_sha256"]:
        raise SystemExit("public schema hash mismatch")

    prompt = direct_qwen_prompt(public)
    if any(secret in prompt for secret in ("sk-", "DASHSCOPE", "Bearer")):
        raise SystemExit("prompt unexpectedly contains a secret marker")

    from scripts.local_qwen_client import LocalQwenClient  # noqa: PLC0415
    client = LocalQwenClient(args.model_path, max_new_tokens=args.max_new_tokens,
                             temperature=0.0, seed=42)
    messages = [{"role": "system",
                 "content": "You are a precise program-semantics analyst. "
                            "Return exactly one JSON object."},
                {"role": "user", "content": prompt}]
    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    start = time.perf_counter()
    response = client.chat(messages, purpose="blind_01/direct")
    wall = round(time.perf_counter() - start, 3)
    finished = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    raw_payload = {
        "schema_version": "mace-blind-baseline-raw-v1",
        "task_id": public["task_id"],
        "method": "direct_qwen",
        "provider": client.provider,
        "model_info": client.model_info(),
        "generation": {"temperature": 0.0, "seed": 42,
                       "max_new_tokens": args.max_new_tokens,
                       "do_sample": False},
        "prompt": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "public_task_sha256": freeze["public_sha256"],
        "public_schema_sha256": freeze["public_schema_sha256"],
        "private_data_used_before_answer": False,
        "started_at_utc": started,
        "finished_at_utc": finished,
        "wall_seconds": wall,
        "stats": response.stats,
        "raw_response": response.content,
    }
    raw_path = RUN_DIR / f"{args.out_prefix}_raw.json"
    write_json(raw_path, raw_payload)

    try:
        answer = extract_json(response.content)
        parse_error = None
        status = "ANSWERED"
    except Exception as exc:  # noqa: BLE001
        answer = None
        parse_error = f"{type(exc).__name__}: {exc}"
        status = "INVALID"

    # Only now, after the raw answer is on disk, read the private oracle.
    oracle = json.loads(PRIVATE.read_text(encoding="utf-8"))
    if sha256_bytes(PRIVATE.read_bytes()) != freeze["private_sha256"]:
        raise SystemExit("private oracle hash mismatch")
    guard_expr = ((answer or {}).get("guard") or {}).get("expr")
    guard_score = (classify_guard(guard_expr, oracle["eval_cases"])
                   if isinstance(guard_expr, str) and guard_expr.strip()
                   else {"status": "ABSENT", "exact": False, "sound": None,
                         "complete": None, "note": "no guard expression"})
    masking_score = (score_masking(answer or {}, oracle["public_probe_labels"])
                     if answer is not None else {"exact": False, "covered": 0, "total": 4})
    counterexample_score = (score_counterexample(answer or {}, public, oracle)
                            if answer is not None else {"status": "unscored"})
    test_gap_score = (score_test_gap(answer or {}, oracle)
                      if answer is not None else {"exact": False, "covered": 0, "total": 5})

    scored = {
        **{k: v for k, v in raw_payload.items() if k not in ("prompt", "raw_response")},
        "status": status,
        "parse_error": parse_error,
        "answer": answer,
        "counted_as_analyzed": status == "ANSWERED",
        "scoring": {
            "guard": guard_score,
            "masking": masking_score,
            "counterexample": counterexample_score,
            "test_gap": test_gap_score,
            "overall_exact_is_not_a_single_score": True,
        },
        "scored_after_raw_write": True,
    }
    scored_path = RUN_DIR / f"{args.out_prefix}_scored.json"
    write_json(scored_path, scored)

    summary = {
        "task_id": public["task_id"],
        "method": "direct_qwen",
        "model": client.model_name,
        "status": status,
        "counted_as_analyzed": status == "ANSWERED",
        "tokens": {"prompt_tokens": response.stats.get("prompt_tokens"),
                   "completion_tokens": response.stats.get("completion_tokens"),
                   "total_tokens": response.stats.get("total_tokens")},
        "wall_seconds": wall,
        "guard": {k: guard_score.get(k) for k in
                  ("status", "exact", "sound", "complete", "false_accept", "false_reject")},
        "masking": {k: masking_score.get(k) for k in ("exact", "covered", "total")},
        "counterexample": counterexample_score.get("status"),
        "test_gap": {k: test_gap_score.get(k) for k in ("exact", "covered", "total")},
        "raw_path": str(raw_path.relative_to(ROOT)),
        "scored_path": str(scored_path.relative_to(ROOT)),
    }
    write_json(RUN_DIR / f"{args.out_prefix}_summary.json", summary)
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
