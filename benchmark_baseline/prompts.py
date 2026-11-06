"""Frozen prompt construction for the v3 development baseline.

Only files inside the published PUBLIC package are read.  The hidden candidate
universe, matrices, story labels and per-test classifications are not read here
and are never placed in a prompt.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from benchmark_real_v3.config import V3

PUBLIC = V3 / "release" / "PUBLIC"
PROMPT_VERSION = "mace-v3-baseline-prompt-1.1"

SYSTEM = (
    "You are a precise Python program analyst. You return only one JSON "
    "object and never add markdown or prose outside it."
)

TEMPLATE = """You are given a real Python source file and one target statement A.
Deleting A leaves the listed original tests passing. Explain the deletion risk
with executable claims.

TASK ID: {task_id}
PROJECT: {project}
TARGET A (delete this statement): {file}:{line}
    {code}

PUBLIC SOURCE (project-relative path {file}; line numbers are shown as
``<n>| <code>``.  A full file is shown when small; otherwise a marked window
around A is shown and omitted line ranges are stated):
----- BEGIN SOURCE -----
{source}
----- END SOURCE -----

LEGAL INPUT CONTRACT:
{contract}

ORIGINAL TESTS THAT EXECUTE A (public frozen list, {test_count} node ids):
{tests}

PUBLIC SUBMISSION FORMAT (summary):
- One JSON object: {{"task_id": "...", "claims": [...], "test_gap": {{...}}}}
- An operation is {{"file": "project/relative.py", "line": 123}}.  Optional
  "end_line" covers a block.  Do not invent lines.
- EXPOSING_COUNTEREXAMPLE: {{"type": "EXPOSING_COUNTEREXAMPLE", "input": {{...}}}}
  The input must be legal and must make P+ and P- observations differ.
- MSMS: {{"type": "MSMS", "input": {{...}}, "operations": [{{"file": "...", "line": 1}}]}}
  The operation set S is the minimal set whose preservation masks the deletion.
- MMBS: same fields with "type": "MMBS"; S is the minimal set whose deletion
  exposes the deletion.  The input must already be masked at EMPTY.
- Do not include A itself in MSMS/MMBS.
- test_gap.tests is a list of {{"name": "<full pytest node id>", "verdict":
  "masked" | "no_local_effect" | "assertion_gap" | "not_executed" | "caught"}}.
  Use only tests from the list above.  It is fine to answer a subset.

Return exactly this shape (omit unsupported claims rather than guessing):
{{"task_id": "{task_id}",
  "claims": [ ... ],
  "test_gap": {{"summary": "one sentence", "tests": [ ... ]}}}}
"""


def _load_json(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def public_task(task_id: str) -> Dict[str, Any]:
    return _load_json(PUBLIC / "tasks" / task_id / "task.json")


SOURCE_CHAR_LIMIT = 20000
SOURCE_CONTEXT_LINES = 120


def public_source(task: Dict[str, Any]) -> str:
    """Public file, deterministically windowed only when it exceeds the limit.

    The window is centred on A and is large enough to keep every operation
    used by the development tasks in view.  Omitted ranges are marked with
    their line numbers so the model can see that the file continues.
    """
    path = PUBLIC / "tasks" / task["task_id"] / task["source_path"]
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines()
    if len(text) <= SOURCE_CHAR_LIMIT:
        start, end = 1, len(lines)
    else:
        target_line = int(task["target_operation"]["line"])
        start = max(1, target_line - SOURCE_CONTEXT_LINES)
        end = min(len(lines), target_line + SOURCE_CONTEXT_LINES)
    parts = []
    if start > 1:
        parts.append(f"# <omitted lines 1-{start - 1} of this file>")
    for number in range(start, end + 1):
        parts.append(f"{number:5d}| {lines[number - 1]}")
    if end < len(lines):
        parts.append(f"# <omitted lines {end + 1}-{len(lines)} of this file>")
    return "\n".join(parts) + "\n"


def build_user_prompt(task_id: str) -> str:
    task = public_task(task_id)
    target = task["target_operation"]
    tests = task["frozen_t_task"]
    return TEMPLATE.format(
        task_id=task_id,
        project=task["project"],
        file=target["file"],
        line=target["line"],
        code=target["code"],
        source=public_source(task),
        contract=json.dumps(task["legal_input_contract"],
                            ensure_ascii=False, indent=2),
        test_count=len(tests),
        tests="\n".join(tests),
    )


def messages_for(task_id: str) -> List[Dict[str, str]]:
    return [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": build_user_prompt(task_id)},
    ]


def feedback_message(result: Dict[str, Any], round_index: int) -> str:
    """Status-only validator feedback; no hidden labels or observations."""
    rows = []
    for claim in result.get("claims", []):
        rows.append({
            "index": claim.get("index"),
            "type": claim.get("type"),
            "status": claim.get("status"),
            "note": claim.get("note"),
        })
    return (
        f"Round {round_index} validator results. These are execution statuses "
        "only; no hidden labels are included.\n"
        + json.dumps(rows, ensure_ascii=False, indent=2)
        + "\nRevise the JSON. Keep a claim only if you believe it is correct; "
          "remove or repair FALSE/INVALID/UNVERIFIED claims; add missing claims. "
          "Return only the complete JSON object in the same schema."
    )


def prompt_manifest() -> Dict[str, Any]:
    digest = hashlib.sha256()
    digest.update(SYSTEM.encode("utf-8"))
    digest.update(b"\0")
    digest.update(TEMPLATE.encode("utf-8"))
    digest.update(b"\0")
    for task_id in sorted(
            item["task_id"] for item in _load_json(PUBLIC / "tasks" / "index.json")["tasks"]):
        digest.update(build_user_prompt(task_id).encode("utf-8"))
        digest.update(b"\0")
    return {
        "prompt_version": PROMPT_VERSION,
        "prompt_sha256": digest.hexdigest(),
        "template_sha256": hashlib.sha256(
            (SYSTEM + "\0" + TEMPLATE).encode("utf-8")).hexdigest(),
        "public_bundle_sha256": _load_json(
            V3 / "release" / "manifest.json")["bundle_sha256"],
        "submission_format_sha256": hashlib.sha256(
            (PUBLIC / "submission_format.md").read_bytes()).hexdigest(),
    }
