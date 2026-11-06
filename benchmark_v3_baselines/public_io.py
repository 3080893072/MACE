"""Read only the frozen PUBLIC task package.

No function in this module touches ``release/HIDDEN`` or the scorer.  The
public package is the only information a baseline is allowed to see.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any, Dict, List

from benchmark_v3_baselines.config import PUBLIC


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def load_task(task_id: str) -> Dict[str, Any]:
    root = PUBLIC / "tasks" / task_id
    task_path = root / "task.json"
    task = json.loads(task_path.read_text(encoding="utf-8"))
    source_path = root / task["source_path"]
    source_text = source_path.read_text(encoding="utf-8")
    digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    if digest != task["source_sha256"]:
        raise ValueError(
            f"{task_id}: source sha256 mismatch ({digest} != "
            f"{task['source_sha256']})")
    return {
        "task": task,
        "task_path": str(task_path),
        "source_path": str(source_path),
        "source_text": source_text,
        "source_lines": source_text.splitlines(),
        "task_sha256": hashlib.sha256(
            task_path.read_bytes()).hexdigest(),
    }


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_payload(task: Dict[str, Any], payload: Any) -> List[str]:
    """Validate an input against the *published* legal_input_contract."""
    contract = task["legal_input_contract"]
    fields = contract["fields"]
    if not isinstance(payload, dict):
        return ["input must be a JSON object"]
    errors: List[str] = []
    unknown = sorted(set(payload) - set(fields))
    if unknown:
        errors.append(f"unknown input field(s): {unknown}")
    for name, spec in fields.items():
        if spec.get("required") and name not in payload:
            errors.append(f"missing required field: {name}")
    for name, spec in fields.items():
        if name not in payload:
            continue
        value = payload[name]
        kind = spec["type"]
        if kind == "string":
            if not isinstance(value, str):
                errors.append(f"{name} must be a string")
            elif len(value) > spec.get("max_length", 10000):
                errors.append(f"{name} exceeds max_length")
        elif kind == "string|null":
            if value is not None:
                if not isinstance(value, str):
                    errors.append(f"{name} must be a string or null")
                elif len(value) > spec.get("max_length", 10000):
                    errors.append(f"{name} exceeds max_length")
        elif kind == "object":
            if not isinstance(value, dict):
                errors.append(f"{name} must be a JSON object")
        elif kind == "array|null":
            if value is not None:
                if not isinstance(value, list) or len(value) != 2:
                    errors.append(f"{name} must be a two-element array or null")
                else:
                    host, port = value
                    if not isinstance(host, str):
                        errors.append(f"{name}[0] must be a string")
                    if port is not None and (
                            not _is_int(port) or not 0 <= port <= 65535):
                        errors.append(f"{name}[1] must be an integer 0..65535")
        if "enum" in spec and value not in spec["enum"]:
            errors.append(f"{name} must be one of {spec['enum']}")
    if task["task_id"] == "werkzeug_filestorage_stream_name":
        if payload.get("stream") == "named" and not isinstance(
                payload.get("name"), str):
            errors.append("name is required and must be a string for named streams")
    return errors
