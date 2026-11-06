"""Efficient ordered event tracer (reliable_ast_v1).

Request JSON is passed as argv[1]::

    {"probe": ..., "target_file": ..., "payload": ..., "out": ...,
     "watch_names": ["code"], "max_events": 20000}

Design constraints:
  * code-object -> path match is cached once; no per-line realpath;
  * line events carry a monotonically increasing sequence number, so
    "downstream" is decided by dynamic order, never by source line number;
  * call / return / exception events of the target file are recorded too;
  * only explicitly named local variables are snapshotted.  Attributes and
    subscripts are never evaluated by the tracer (no side effects).
"""
from __future__ import annotations

import hashlib
import io
import json
import os
import re
import runpy
import sys

_ADDRESS = re.compile(r"0x[0-9a-fA-F]+")


def _safe_repr(value: object) -> str:
    try:
        text = repr(value)
    except Exception as exc:  # noqa: BLE001
        text = f"<repr-error {type(exc).__name__}>"
    return _ADDRESS.sub("0xADDR", text)[:200]


def _snapshot(frame: dict, names: list) -> dict:
    out = {}
    for name in names:
        if name not in frame:
            out[name] = {"bound": False, "type": None, "repr": None, "hash": None}
            continue
        value = frame[name]
        text = _safe_repr(value)
        out[name] = {
            "bound": True,
            "type": type(value).__name__,
            "repr": text,
            "hash": hashlib.sha1(
                (type(value).__name__ + "\0" + text).encode("utf-8", "replace")
            ).hexdigest(),
        }
    return out


def main() -> int:
    request = json.loads(open(sys.argv[1], encoding="utf-8").read())
    target = os.path.realpath(request["target_file"])
    names = list(request.get("watch_names") or [])
    max_events = int(request.get("max_events", 50000))
    match_cache: dict = {}
    events: list = []
    errors: list = []
    truncated = False
    seq = 0
    call_seq = 0

    def matches(code) -> bool:
        if code not in match_cache:
            try:
                match_cache[code] = os.path.realpath(code.co_filename) == target
            except Exception:  # noqa: BLE001
                match_cache[code] = False
        return match_cache[code]

    def make_local_tracer(call_id: int):
        def local_tracer(frame, event, arg):
            nonlocal truncated, seq, call_seq
            if event == "call" and matches(frame.f_code):
                call_seq += 1
                return make_local_tracer(call_seq)
            if not matches(frame.f_code):
                return local_tracer
            if event == "line":
                if len(events) >= max_events:
                    truncated = True
                    return local_tracer
                seq += 1
                events.append({
                    "seq": seq,
                    "event": "line",
                    "call_id": call_id,
                    "line": int(frame.f_lineno),
                    "func": frame.f_code.co_name,
                    "locals": _snapshot(frame.f_locals, names),
                })
            elif event == "exception":
                seq += 1
                exc_type = arg[0].__name__ if arg and arg[0] else "Exception"
                events.append({
                    "seq": seq,
                    "event": "exception",
                    "call_id": call_id,
                    "line": int(frame.f_lineno),
                    "func": frame.f_code.co_name,
                    "exception": exc_type,
                })
            elif event == "return":
                seq += 1
                events.append({
                    "seq": seq,
                    "event": "return",
                    "call_id": call_id,
                    "line": int(frame.f_lineno),
                    "func": frame.f_code.co_name,
                })
            return local_tracer
        return local_tracer

    def global_tracer(frame, event, arg):
        nonlocal call_seq
        if event == "call" and matches(frame.f_code):
            call_seq += 1
            return make_local_tracer(call_seq)
        return None

    sys.stdin = io.StringIO(json.dumps(request["payload"]))
    sys.argv = [request["probe"]]
    sys.settrace(global_tracer)
    try:
        runpy.run_path(request["probe"], run_name="__main__")
    except SystemExit as exc:
        if exc.code not in (0, None):
            errors.append({"type": "SystemExit", "message": str(exc.code)[:300]})
    except BaseException as exc:  # noqa: BLE001
        errors.append({"type": type(exc).__name__, "message": str(exc)[:300]})
    finally:
        sys.settrace(None)

    with open(request["out"], "w", encoding="utf-8") as handle:
        handle.write(json.dumps({
            "target_file": target,
            "watch_names": names,
            "events": events,
            "errors": errors,
            "truncated": truncated,
        }, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
