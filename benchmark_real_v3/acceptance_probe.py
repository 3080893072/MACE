"""Run one probe under a line tracer and report whether A executed.

This helper is used only by :mod:`benchmark_real_v3.acceptance_v3`.  It is
deliberately independent of ``verify_task``/``variant_lab``: the child gets a
probe path, an absolute target file, a target line and one JSON payload.  The
probe runs in this process via ``runpy`` so ``sys.settrace`` sees the project
code imported by the probe.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import runpy
import sys
import traceback
from typing import Any, Dict


def _json_load(text: str) -> Dict[str, Any]:
    return json.loads(text)


def main() -> int:
    request = _json_load(sys.stdin.read())
    probe = request["probe"]
    payload = request["payload"]
    target_file = os.path.normcase(os.path.realpath(request["target_file"]))
    target_line = int(request["target_line"])

    state = {"executed": False}

    def _tracer(frame, event, arg):
        if (
            event == "line"
            and frame.f_lineno == target_line
            and os.path.normcase(os.path.realpath(frame.f_code.co_filename))
            == target_file
        ):
            state["executed"] = True
        return _tracer

    buffer = io.StringIO()
    old_stdin = sys.stdin
    old_trace = sys.gettrace()
    exit_code = 0
    error = None
    try:
        sys.stdin = io.StringIO(json.dumps(payload, ensure_ascii=False))
        sys.settrace(_tracer)
        with contextlib.redirect_stdout(buffer):
            try:
                runpy.run_path(probe, run_name="__main__")
            except SystemExit as exc:
                exit_code = int(exc.code or 0)
            except BaseException as exc:  # noqa: BLE001
                error = "".join(
                    traceback.format_exception_only(type(exc), exc)).strip()
    finally:
        sys.settrace(old_trace)
        sys.stdin = old_stdin

    observation = None
    parse_error = None
    lines = [line for line in buffer.getvalue().splitlines() if line.strip()]
    if lines:
        try:
            observation = json.loads(lines[-1])
        except ValueError as exc:
            parse_error = str(exc)
    print(json.dumps({
        "observation": observation,
        "executed": bool(state["executed"]),
        "probe_exit_code": exit_code,
        "probe_error": error,
        "parse_error": parse_error,
    }, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
