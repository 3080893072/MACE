"""Baseline A: Direct Qwen.

One prompt, one call, no verifier feedback.  The model sees only the frozen
PUBLIC task package: the task JSON and the target source file.  Its raw
response is stored verbatim; the submission is parsed mechanically and is
never repaired using hidden feedback.
"""
from __future__ import annotations

import json
import time
from typing import Any, Dict, List, Optional, Tuple

from benchmark_v3_baselines import claims as claim_io
from benchmark_v3_baselines.public_io import load_task, validate_payload

PROMPT_VERSION = "direct-qwen-v3-baseline-1.0"

SYSTEM = """You are analysing a Python program for operation-level masking.
Return only a JSON object. Do not explain outside the JSON."""

INSTRUCTIONS = """\
You are given one frozen benchmark task and the full text of its target
source file.

Definitions used by the benchmark:
- A is the target operation named in task["target_operation"].
- P+ keeps A; P- deletes it (the statement is replaced by `pass`).
- An input is EXPOSING when P+ and P- produce different observations.
- An input is MASKED when P+ and P- produce equal observations.
- MSMS (minimal sufficient masking set): a non-empty set S of other
  operations such that, with every candidate operation outside S deleted and
  A also deleted, the observation equals P+; and no non-empty proper subset
  of S has that property.
- MMBS (minimal breaking set): a non-empty set S that exposes the deletion
  when deleted, and no proper subset (including the empty set) does.

The candidate operation universe is NOT given to you.  Name operations by
project-relative file and line, with the exact source text in "code".
Operations outside the benchmark's hidden universe cannot be scored; prefer
operations you can justify from the source.

Submit claims in this JSON shape:
{
  "claims": [
    {"type": "EXPOSING_COUNTEREXAMPLE", "input": {...}},
    {"type": "MSMS", "input": {...}, "operations": [{"file": "...", "line": 1, "code": "..."}]},
    {"type": "MMBS", "input": {...}, "operations": [{"file": "...", "line": 1, "code": "..."}]},
    {"type": "PREREQUISITE_BREAKING", "input": {...}, "control_input": {...},
     "operations": [...], "prerequisite": "..."}
  ]
}
Every input must satisfy the published legal_input_contract.  Only include
claims you believe are true; include several distinct witnesses when useful.

TASK JSON:
{task_json}

TARGET SOURCE FILE ({source_path}):
```python
{source_text}
```
"""


def build_messages(task: Dict[str, Any], source_text: str,
                   source_path: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": (
            INSTRUCTIONS
            .replace("{task_json}", json.dumps(task, ensure_ascii=False, indent=2))
            .replace("{source_path}", source_path)
            .replace("{source_text}", source_text)
        )},
    ]


def extract_json_object(text: str) -> Tuple[Optional[Dict[str, Any]], str]:
    body = (text or "").strip()
    if body.startswith("```"):
        lines = body.splitlines()
        if lines and lines[0].startswith("```"):
            lines = lines[1:]
        if lines and lines[-1].strip().startswith("```"):
            lines = lines[:-1]
        body = "\n".join(lines)
    decoder = json.JSONDecoder()
    for index, char in enumerate(body):
        if char != "{":
            continue
        try:
            obj, _ = decoder.raw_decode(body[index:])
        except json.JSONDecodeError:
            continue
        if isinstance(obj, dict):
            return obj, ""
    return None, "response contains no JSON object"


def parse_submission(raw: str, task_id: str) -> Dict[str, Any]:
    obj, error = extract_json_object(raw)
    if obj is None:
        return {"task_id": task_id, "claims": [], "parse_error": error}
    claims = obj.get("claims") if isinstance(obj, dict) else None
    if not isinstance(claims, list):
        return {"task_id": task_id, "claims": [],
                "parse_error": "JSON object has no list field 'claims'"}
    return {"task_id": task_id, "claims": claims}


def public_input_errors(task: Dict[str, Any],
                        submission: Dict[str, Any]) -> List[str]:
    """Count claims whose input violates the published contract (diagnostic)."""
    problems: List[str] = []
    for index, claim in enumerate(submission.get("claims") or []):
        if not isinstance(claim, dict):
            problems.append(f"claim[{index}]: not an object")
            continue
        for field in ("input", "control_input", "condition_input",
                      "conclusion_input"):
            if field in claim:
                errors = validate_payload(task, claim[field])
                if errors:
                    problems.append(f"claim[{index}].{field}: " + "; ".join(errors))
    return problems


def run(client: Any, task_id: str, *, out_dir: Optional[Any] = None,
        submission_id: str = "baseline-A") -> Dict[str, Any]:
    loaded = load_task(task_id)
    task = loaded["task"]
    messages = build_messages(task, loaded["source_text"],
                              task["source_path"])
    started = time.time()
    response = client.chat(messages, purpose="baseline_A_direct")
    elapsed = round(time.time() - started, 3)
    submission = parse_submission(response.content, task_id)
    submission["submission_id"] = submission_id
    record = {
        "run_label": "LIVE_MODEL_RUN",
        "baseline": "A_direct_qwen",
        "task_id": task_id,
        "prompt_version": PROMPT_VERSION,
        "messages": messages,
        "raw_response": response.content,
        "response_stats": getattr(response, "stats", None),
        "wall_seconds": elapsed,
        "submission": submission,
        "input_contract_errors": public_input_errors(task, submission),
    }
    if out_dir is not None:
        out_dir.mkdir(parents=True, exist_ok=True)
        (out_dir / "request.json").write_text(
            json.dumps({"messages": messages, "prompt_version": PROMPT_VERSION},
                       ensure_ascii=False, indent=2), encoding="utf-8")
        (out_dir / "raw_response.txt").write_text(
            response.content, encoding="utf-8")
        (out_dir / "submission.json").write_text(
            json.dumps(submission, ensure_ascii=False, indent=2),
            encoding="utf-8")
    return record
