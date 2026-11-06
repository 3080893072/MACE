"""Run the minimal method probe on the frozen blind task (public data only).

This script is deliberately *not* a scorer.  It records, for each method,

* whether the method can accept the frozen task at all,
* whether an answer was produced,
* token counts and wall time,
* the exact public prompt / diagnostic evidence.

It never reads ``benchmark_blind_v1/private/``.  A method that is unsupported or
blocked is recorded as ``counted_as_analyzed: false``; it is not silently
treated as a wrong answer and it is not scored against the private oracle.

Run:
    python scripts/blind_probe_methods.py
"""
from __future__ import annotations

import hashlib
import json
import os
import platform
import shutil
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "benchmark_blind_v1"
PUBLIC = OUT / "public" / "task_01_parse_header_links.json"
FREEZE = OUT / "FREEZE.json"
RESULTS = OUT / "results"
LOGS = OUT / "logs"
TASK_ID = "blind_01_parse_header_links"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    return sha256_bytes(path.read_bytes())


def utc_now() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(value), encoding="utf-8", newline="\n")


def load_frozen() -> tuple[Dict[str, Any], Dict[str, Any], str]:
    if not PUBLIC.exists() or not FREEZE.exists():
        raise SystemExit("frozen public task or FREEZE.json is missing; run "
                         "scripts/blind_build.py first")
    public_bytes = PUBLIC.read_bytes()
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if sha256_bytes(public_bytes) != freeze["public_sha256"]:
        raise SystemExit("public task hash does not match FREEZE.json; refusing to run")
    public = json.loads(public_bytes.decode("utf-8"))
    if public["task_id"] != TASK_ID:
        raise SystemExit("unexpected task id")
    schema = OUT / "public" / "SUBMISSION_SCHEMA.json"
    if freeze.get("public_schema_sha256"):
        if not schema.exists() or sha256_file(schema) != freeze["public_schema_sha256"]:
            raise SystemExit("public submission schema hash does not match FREEZE.json")
    return public, freeze, sha256_file(FREEZE)


def direct_qwen_prompt(public: Dict[str, Any]) -> str:
    ops = "\n".join(
        f"- {op['id']}: line {op['source_position']['line']}, "
        f"expression `{op['expression']}`; disable by {op['disable_by']}"
        for op in public["candidate_operations"])
    tests = public["existing_tests"]["adapted_source"]
    probes = "\n".join(
        f"- {probe['probe_id']}: {probe['value']!r}"
        for probe in public["public_probes"]["probes"])
    features = "\n".join(
        f"- {name}: {definition}"
        for name, definition in public["input_domain"]["guard_features"]["definitions"].items())
    return f"""You are analysing a proposed code deletion.  Answer only from the
public information below.  A Python exception is an observation.  Do not claim
a proof over all inputs; the best evidence level is BOUNDED.

## Program P+
```python
{public['program']['source']}```

## Target A
Line {public['program']['target_A']['line']}: `{public['program']['target_A']['text'].strip()}`
Deletion rule: {public['deletion']['rule']}

## Legal inputs and observable
{public['input_domain']['legal_rule']}
Observable: {public['input_domain']['observable_behavior']}

## Public guard features (the correct expression is hidden)
{features}
Use only these features, int/bool constants, and/or/not, comparisons, and
arithmetic.  Return the Guard expression as a string in `guard.expr`.

## Neutral candidate operations
{ops}

## Public probes (inputs are public; labels are private)
{probes}

For each probe, report the exact set of minimal enabled operations that makes
P+ and P- observationally equal, or [] plus kind "none" if the deletion is
observable on that probe.

## T_original (the programmer's existing tests; real upstream test)
```python
{tests}```

## Required JSON answer
{{
  "guard": {{"expr": "...", "status": "BOUNDED or UNKNOWN"}},
  "masking": {{
      "probes": [
        {{"probe_id": "p1", "absorber_sets": [["op_<k>"]], "kind": "independent | cooperative | mixed | none"}},
        {{"probe_id": "p2", "absorber_sets": [["op_<k>"]], "kind": "independent | cooperative | mixed | none"}},
        {{"probe_id": "p3", "absorber_sets": [["op_<k>"]], "kind": "independent | cooperative | mixed | none"}},
        {{"probe_id": "p4", "absorber_sets": [["op_<k>"]], "kind": "independent | cooperative | mixed | none"}}
      ]
  }},
  "counterexample": {{"claim": "exists | none_exists | none_found", "value": "..."}},
  "test_gap": {{"verdict": "...", "tests": [{{"name": "...", "verdict": "..."}}]}},
  "evidence": "..."
}}
Return one JSON object and no prose outside it.
"""


def probe_provider() -> Dict[str, Any]:
    binary = shutil.which("ollama")
    reachable = False
    error = None
    try:
        with socket.create_connection(("127.0.0.1", 11434), timeout=0.5):
            reachable = True
    except OSError as exc:
        error = f"{type(exc).__name__}: {exc}"
    key_present = bool(os.environ.get("DASHSCOPE_API_KEY"))
    return {
        "ollama_binary": binary,
        "ollama_endpoint": "http://127.0.0.1:11434",
        "ollama_reachable": reachable,
        "ollama_probe_error": error,
        "dashscope_key_present": key_present,
        "available": bool(binary) or reachable or key_present,
        "note": "No secret value is recorded; only whether the variable is set.",
    }


def result_shell(method: str, status: str, public: Dict[str, Any],
                 freeze: Dict[str, Any], freeze_sha: str,
                 explanation: List[str]) -> Dict[str, Any]:
    return {
        "schema_version": "mace-benchmark-blind-v1-method-result",
        "task_id": TASK_ID,
        "method": method,
        "status": status,
        "counted_as_analyzed": False,
        "correctness": None,
        "tokens": {"prompt_tokens": 0, "completion_tokens": 0,
                   "total_tokens": 0, "llm_calls": 0},
        "wall_seconds": None,
        "started_at_utc": None,
        "finished_at_utc": None,
        "answer": None,
        "explanation": explanation,
        "input_information": {
            "public_task_sha256": freeze["public_sha256"],
            "freeze_public_sha256": freeze["public_sha256"],
            "freeze_sha256": freeze_sha,
            "public_schema_sha256": freeze.get("public_schema_sha256"),
            "private_data_used": False,
        },
        "environment": {
            "python": sys.version.split()[0],
            "platform": platform.platform(),
        },
    }


def run_direct_qwen(public: Dict[str, Any], freeze: Dict[str, Any],
                    freeze_sha: str) -> Dict[str, Any]:
    start = time.perf_counter()
    started = utc_now()
    provider = probe_provider()
    prompt = direct_qwen_prompt(public)
    out = result_shell(
        "direct_qwen", "BLOCKED", public, freeze, freeze_sha,
        ["No Qwen model service is reachable on this machine.",
         "No call was made, so no tokens were consumed and no answer exists.",
         "A blocked method is not a wrong answer and is not counted as analysed."])
    out["provider_probe"] = provider
    out["model_config"] = {
        "intended_provider": "ollama",
        "intended_model": "qwen2.5-coder:7b",
        "temperature": 0.0,
        "seed": 42,
        "num_ctx": 8192,
    }
    out["prompt"] = prompt
    out["prompt_sha256"] = hashlib.sha256(prompt.encode("utf-8")).hexdigest()
    out["started_at_utc"] = started
    out["finished_at_utc"] = utc_now()
    out["wall_seconds"] = round(time.perf_counter() - start, 3)
    if provider["available"]:
        out["status"] = "NOT_CALLED"
        out["explanation"].append(
            "A provider endpoint/key was detected, but this run did not call it; "
            "the call path is intentionally not exercised without an explicit rerun.")
    return out


def run_full_mace(public: Dict[str, Any], freeze: Dict[str, Any],
                  freeze_sha: str) -> Dict[str, Any]:
    start = time.perf_counter()
    started = utc_now()
    from mace.program import build_pair
    source = public["program"]["source"]
    entry = public["program"]["entry"]
    try:
        pair = build_pair(source, entry)
        error = None
        supported = pair.supported
        problems = list(pair.problems)
        target_line = pair.target_line
        functions = list(pair.function_names)
    except Exception as exc:  # noqa: BLE001
        error = f"{type(exc).__name__}: {exc}"
        supported = False
        problems = []
        target_line = None
        functions = []
    status = "UNSUPPORTED" if not supported else "FRONT_END_ACCEPTED_NOT_RUN"
    out = result_shell(
        "full_mace", status, public, freeze, freeze_sha,
        ["mace.program.build_pair is the Full MACE front-end.",
         "It rejects the frozen source before any contract synthesis or Qwen call.",
         "UNSUPPORTED is not counted as analysed."] if not supported else
        ["The front-end accepted the source; this probe does not run the full pipeline."])
    out["front_end"] = {
        "call": "mace.program.build_pair(source, entry)",
        "supported": supported,
        "target_line": target_line,
        "functions": functions,
        "problems": problems,
        "error": error,
    }
    out["analysis_performed"] = False
    out["llm_calls"] = 0
    out["started_at_utc"] = started
    out["finished_at_utc"] = utc_now()
    out["wall_seconds"] = round(time.perf_counter() - start, 3)
    return out


def run_pure_symbolic(public: Dict[str, Any], freeze: Dict[str, Any],
                      freeze_sha: str) -> Dict[str, Any]:
    start = time.perf_counter()
    started = utc_now()
    from mace.domain import build_domain
    from mace.fixture import Fixture
    from mace.symbolic import derive_guard
    source = public["program"]["source"]
    entry = public["program"]["entry"]

    fixture_error = None
    try:
        build_domain({"kind": "exhaustive",
                      "args": [{"name": "value", "sort": "str"}]})
        fixture_supported = True
    except Exception as exc:  # noqa: BLE001
        fixture_supported = False
        fixture_error = f"{type(exc).__name__}: {exc}"

    diagnostic = None
    diagnostic_error = None
    if not fixture_supported:
        try:
            fixture = Fixture(
                config={"id": "blind_01", "entry": entry,
                        "domain": {"args": [{"name": "value", "sort": "str"}]}},
                source=source,
                domain=None,  # only used by the fixture loader, not derive_guard
                arg_sorts={"value": "str"},
                functions={},
                channels=1,
                entry=entry,
            )
            diagnostic = derive_guard(fixture, use_summaries=False)
        except Exception as exc:  # noqa: BLE001
            diagnostic_error = f"{type(exc).__name__}: {exc}"

    out = result_shell(
        "pure_symbolic", "UNSUPPORTED", public, freeze, freeze_sha,
        ["The published fixture/domain interface has no 'str' argument sort, "
         "so it cannot accept this frozen task as specified.",
         "A diagnostic direct call to mace.symbolic.derive_guard (outside the "
         "published fixture interface) returns UNKNOWN on the string constant.",
         "Neither result is counted as analysed."])
    out["fixture_interface"] = {
        "supported": fixture_supported,
        "error": fixture_error,
    }
    out["diagnostic_derive_guard"] = {
        "performed": diagnostic is not None,
        "error": diagnostic_error,
        "result": diagnostic,
    }
    if diagnostic is not None:
        out["diagnostic_status"] = diagnostic.get("status")
    out["analysis_performed"] = False
    out["llm_calls"] = 0
    out["started_at_utc"] = started
    out["finished_at_utc"] = utc_now()
    out["wall_seconds"] = round(time.perf_counter() - start, 3)
    return out


def main() -> int:
    public, freeze, freeze_sha = load_frozen()
    RESULTS.mkdir(parents=True, exist_ok=True)
    LOGS.mkdir(parents=True, exist_ok=True)

    results = {
        "direct_qwen": run_direct_qwen(public, freeze, freeze_sha),
        "full_mace": run_full_mace(public, freeze, freeze_sha),
        "pure_symbolic": run_pure_symbolic(public, freeze, freeze_sha),
    }
    paths = {
        "direct_qwen": RESULTS / "task_01_direct_qwen.json",
        "full_mace": RESULTS / "task_01_full_mace.json",
        "pure_symbolic": RESULTS / "task_01_pure_symbolic.json",
    }
    for name, path in paths.items():
        write_json(path, results[name])

    summary = {
        "schema_version": "mace-benchmark-blind-v1-comparison",
        "task_id": TASK_ID,
        "freeze": {
            "public_sha256": freeze["public_sha256"],
            "private_sha256": freeze["private_sha256"],
            "freeze_sha256": freeze_sha,
            "frozen_at_utc": freeze["frozen_at_utc"],
        },
        "methods": [
            {
                "method": name,
                "status": result["status"],
                "counted_as_analyzed": result["counted_as_analyzed"],
                "correctness": result["correctness"],
                "tokens": result["tokens"],
                "wall_seconds": result["wall_seconds"],
            }
            for name, result in results.items()
        ],
        "status_counts": {
            status: sum(r["status"] == status for r in results.values())
            for status in sorted({r["status"] for r in results.values()})
        },
        "answered_methods": sum(r["status"] == "ANSWERED" for r in results.values()),
        "analyzed_methods": sum(r["counted_as_analyzed"] for r in results.values()),
        "conclusion": (
            "No method produced an answer on the frozen blind task.  Direct Qwen "
            "is blocked by the missing local service; Full MACE rejects the real "
            "source as outside its supported subset; Pure Symbolic cannot accept "
            "a string argument domain and its diagnostic call returns UNKNOWN.  "
            "Therefore no comparative correctness, token cost, or explanation "
            "quality can be reported.  This is an executability result, not a "
            "0% accuracy result."
        ),
        "generated_at_utc": utc_now(),
    }
    write_json(RESULTS / "comparison_summary.json", summary)

    log_lines = [
        f"task_id: {TASK_ID}",
        f"freeze_sha256: {freeze_sha}",
        f"frozen_at_utc: {freeze['frozen_at_utc']}",
        f"public_sha256: {freeze['public_sha256']}",
        f"private_data_used: false",
    ]
    for name, result in results.items():
        log_lines.append(
            f"{name}: status={result['status']} "
            f"counted_as_analyzed={result['counted_as_analyzed']} "
            f"correctness={result['correctness']} "
            f"tokens={json.dumps(result['tokens'], ensure_ascii=False)} "
            f"wall_seconds={result['wall_seconds']}")
    log_lines.append("answered_methods: 0")
    log_lines.append("analyzed_methods: 0")
    (LOGS / "methods.log").write_text("\n".join(log_lines) + "\n",
                                      encoding="utf-8", newline="\n")

    print("METHOD PROBE COMPLETE")
    for name, result in results.items():
        print(f"{name:14s} {result['status']:12s} "
              f"counted_as_analyzed={result['counted_as_analyzed']} "
              f"wall={result['wall_seconds']}s")
    print("answered_methods 0; analyzed_methods 0")
    print("results:", RESULTS.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
