"""Efficient value-aware tracer for difference-guided candidate discovery.

Unlike ``trace_lines.py`` this tracer:
  * matches code objects once (cached), instead of calling realpath per event;
  * records the value of one named local at every target-file line event;
  * records function name and whether the name is bound.

Request JSON (path in argv[1])::

    {"probe": ..., "target_file": ..., "target_var": ..., "payload": ...,
     "out": ..., "max_events": 20000}

The tracer reads only the public probe input.  It never reads a reference or
an expected observation.
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import runpy
import sys

_MISSING = object()
_ADDRESS = re.compile(r"0x[0-9a-fA-F]+")


def _safe_repr(value: object) -> str:
    try:
        text = repr(value)
    except Exception as exc:  # noqa: BLE001
        text = f"<repr-error {type(exc).__name__}>"
    # Object/code reprs embed process-specific addresses; remove them so the
    # same logical value compares equal across P+ and P- processes.
    text = _ADDRESS.sub("0xADDR", text)
    return text[:200]


def _snapshot(frame, var: str) -> dict:
    if var not in frame.f_locals:
        return {"bound": False, "type": None, "repr": None, "hash": None}
    value = frame.f_locals[var]
    text = _safe_repr(value)
    digest = hashlib.sha1(
        (type(value).__name__ + "\0" + text).encode("utf-8", "replace")).hexdigest()
    return {"bound": True, "type": type(value).__name__,
            "repr": text, "hash": digest}


def main() -> int:
    request = json.loads(open(sys.argv[1], encoding="utf-8").read())
    target = os.path.realpath(request["target_file"])
    var = request["target_var"]
    max_events = int(request.get("max_events", 20000))
    match_cache: dict = {}
    events: list = []
    errors: list = []
    truncated = False

    def matches(code) -> bool:
        if code not in match_cache:
            try:
                match_cache[code] = os.path.realpath(
                    code.co_filename) == target
            except Exception:  # noqa: BLE001
                match_cache[code] = False
        return match_cache[code]

    def local_tracer(frame, event, arg):
        nonlocal truncated
        if event == "line":
            if len(events) >= max_events:
                truncated = True
                return local_tracer
            snap = _snapshot(frame, var)
            events.append({
                "line": int(frame.f_lineno),
                "func": frame.f_code.co_name,
                "bound": snap["bound"],
                "type": snap["type"],
                "repr": snap["repr"],
                "hash": snap["hash"],
            })
        return local_tracer

    def global_tracer(frame, event, arg):
        if event == "call" and matches(frame.f_code):
            return local_tracer
        return None

    sys.stdin = io.StringIO(json.dumps(request["payload"]))
    sys.argv = [request["probe"]]
    sys.settrace(global_tracer)
    try:
        runpy.run_path(request["probe"], run_name="__main__")
    except BaseException as exc:  # noqa: BLE001
        errors.append({"type": type(exc).__name__, "message": str(exc)[:300]})
    finally:
        sys.settrace(None)

    with open(request["out"], "w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "target_file": target,
            "target_var": var,
            "events": events,
            "errors": errors,
            "truncated": truncated,
        }, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
