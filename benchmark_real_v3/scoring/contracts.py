"""Public input contracts and their executable validators.

The same data is copied into the public task package.  Keeping the validator
and the published contract in one place prevents the public schema and the
scorer from drifting apart.
"""
from __future__ import annotations

from typing import Any, Dict, List

MAX_TEXT = 10000
MAX_FILENAME = 4096
MAX_HOST = 1024


CONTRACTS: Dict[str, Dict[str, Any]] = {
    "jinja2_bytecode_cache_read": {
        "fields": {
            "template": {
                "type": "string", "required": True, "max_length": MAX_TEXT,
                "description": "Template source compiled by the environment.",
            },
            "cached_source": {
                "type": "string|null", "required": False,
                "max_length": MAX_TEXT,
                "description": (
                    "Optional source compiled by Environment.compile and "
                    "handed back by the caller's BytecodeCache.  Omit for "
                    "the ordinary same-source cache path."
                ),
            },
            "context": {
                "type": "object", "required": False,
                "description": "Render context; keys are strings.",
            },
        },
        "legal_constraints": [
            "The payload is a JSON object with only the fields listed above.",
            "template must be a string that Jinja2 3.1.3 can compile.",
            "cached_source, when present, must be a string or null and must be "
            "compilable by Jinja2 3.1.3.",
            "context, when present, must be a JSON object with string keys.",
        ],
        "observation": {
            "return": {
                "outcome": "return", "value": "rendered template string",
                "cache_loads": "integer", "cache_dumps": "integer",
            },
            "raise": {
                "outcome": "raise", "type": "exception class name",
                "message": "string", "cache_loads": "integer",
                "cache_dumps": "integer",
            },
        },
    },
    "werkzeug_filestorage_stream_name": {
        "fields": {
            "stream": {
                "type": "string", "required": True,
                "enum": ["tempfile", "stderr", "none", "named"],
                "description": "Kind of stream object passed to FileStorage.",
            },
            "data": {
                "type": "string", "required": False,
                "description": "Bytes encoded as UTF-8 for none/named streams.",
            },
            "name": {
                "type": "string", "required": False,
                "description": "Required when stream is 'named'.",
            },
        },
        "legal_constraints": [
            "The payload is a JSON object with only the fields listed above.",
            "stream must be one of tempfile, stderr, none, named.",
            "data, when present, must be a string.",
            "name is required for stream='named' and must be a string.",
        ],
        "observation": {
            "return": {
                "outcome": "return", "filename": "string|null",
                "filename_type": "Python type name",
            },
            "raise": {
                "outcome": "raise", "type": "exception class name",
                "message": "string",
            },
        },
    },
    "werkzeug_bind_server_name_lower": {
        "fields": {
            "host": {
                "type": "string", "required": False, "max_length": MAX_HOST,
                "description": "WSGI SERVER_NAME and HTTP_HOST value.",
            },
            "server_name": {
                "type": "string|null", "required": False, "max_length": MAX_HOST,
                "description": "Optional explicit server_name argument.",
            },
            "subdomain": {
                "type": "string|null", "required": False, "max_length": MAX_HOST,
                "description": "Optional explicit subdomain argument.",
            },
        },
        "legal_constraints": [
            "The payload is a JSON object with only the fields listed above.",
            "host, server_name and subdomain must be strings or null; host "
            "defaults to example.com when omitted.",
            "Strings longer than the published limit are rejected.",
        ],
        "observation": {
            "return": {
                "outcome": "return", "server_name": "string",
                "subdomain": "string",
            },
            "raise": {
                "outcome": "raise", "type": "exception class name",
                "message": "string",
            },
        },
    },
    "werkzeug_get_host_default_empty": {
        "fields": {
            "scheme": {
                "type": "string", "required": False,
                "enum": ["http", "https", "ws", "wss"],
                "description": "URL scheme; defaults to http.",
            },
            "host_header": {
                "type": "string|null", "required": False,
                "max_length": MAX_HOST,
                "description": "Host header value, or null when absent.",
            },
            "server": {
                "type": "array|null", "required": False,
                "items": ["string", "integer|null"],
                "description": "Server address [host, port], or null.",
            },
        },
        "legal_constraints": [
            "The payload is a JSON object with only the fields listed above.",
            "scheme must be one of http, https, ws, wss.",
            "host_header must be a string or null.",
            "server must be null or a two-element array [string, integer|null]; "
            "port must be 0..65535.",
        ],
        "observation": {
            "return": {"outcome": "return", "host": "string"},
            "raise": {
                "outcome": "raise", "type": "exception class name",
                "message": "string",
            },
        },
    },
    "werkzeug_secure_filename_ascii_filter": {
        "fields": {
            "filename": {
                "type": "string", "required": True,
                "max_length": MAX_FILENAME,
                "description": "Filename supplied by the caller.",
            },
        },
        "legal_constraints": [
            "The payload is a JSON object with only the field filename.",
            "filename must be a string of at most the published length.",
        ],
        "observation": {
            "return": {"outcome": "return", "filename": "string"},
            "raise": {
                "outcome": "raise", "type": "exception class name",
                "message": "string",
            },
        },
    },
}


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def validate_payload(task_id: str, payload: Any) -> List[str]:
    """Return a list of contract violations; empty means legal."""
    contract = CONTRACTS.get(task_id)
    if contract is None:
        return [f"unknown task_id: {task_id}"]
    if not isinstance(payload, dict):
        return ["input must be a JSON object"]
    allowed = set(contract["fields"])
    unknown = sorted(set(payload) - allowed)
    if unknown:
        return [f"unknown input field(s): {unknown}"]
    required = [
        name for name, spec in contract["fields"].items() if spec.get("required")
    ]
    errors = [f"missing required field: {name}" for name in required
              if name not in payload]
    if errors:
        return errors

    def _check(name: str, spec: Dict[str, Any]) -> None:
        if name not in payload:
            return
        value = payload[name]
        kind = spec["type"]
        if kind == "string":
            if not isinstance(value, str):
                errors.append(f"{name} must be a string")
            elif len(value) > spec.get("max_length", MAX_TEXT):
                errors.append(f"{name} exceeds max_length")
        elif kind == "string|null":
            if value is not None:
                if not isinstance(value, str):
                    errors.append(f"{name} must be a string or null")
                elif len(value) > spec.get("max_length", MAX_TEXT):
                    errors.append(f"{name} exceeds max_length")
        elif kind == "object":
            if not isinstance(value, dict):
                errors.append(f"{name} must be a JSON object")
            else:
                if any(not isinstance(key, str) for key in value):
                    errors.append(f"{name} keys must be strings")
        elif kind == "array|null":
            if value is not None:
                if not isinstance(value, list) or len(value) != 2:
                    errors.append(f"{name} must be a two-element array or null")
                else:
                    host, port = value
                    if not isinstance(host, str):
                        errors.append(f"{name}[0] must be a string")
                    if port is not None and (
                        not _is_int(port) or not 0 <= port <= 65535
                    ):
                        errors.append(f"{name}[1] must be an integer 0..65535 "
                                      "or null")
        if "enum" in spec and value not in spec["enum"]:
            errors.append(f"{name} must be one of {spec['enum']}")

    for name, spec in contract["fields"].items():
        _check(name, spec)

    if task_id == "jinja2_bytecode_cache_read" and "context" in payload:
        context = payload["context"]
        if isinstance(context, dict):
            if len(context) > 1000:
                errors.append("context has too many entries")
    if task_id == "werkzeug_filestorage_stream_name":
        stream = payload.get("stream")
        if stream == "named" and not isinstance(payload.get("name"), str):
            errors.append("name is required and must be a string for named streams")
    if task_id == "werkzeug_bind_server_name_lower":
        for name in ("host", "server_name", "subdomain"):
            if isinstance(payload.get(name), str):
                if len(payload[name]) > MAX_HOST:
                    errors.append(f"{name} exceeds max_length")
    return errors
