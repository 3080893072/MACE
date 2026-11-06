"""Subprocess helper: did the target line execute on this input?

Reads one JSON request from stdin, runs the public probe against the variant
tree already put on ``PYTHONPATH`` by the caller, and prints
``{"executed": bool}`` on the real stdout.  The probe's own stdout is
captured and discarded.

This is a small, independent implementation of the trace check; it reads no
benchmark reference data.
"""
from __future__ import annotations

import io
import json
import os
import runpy
import sys


def main() -> int:
    request = json.load(sys.stdin)
    probe = request["probe"]
    target_file = os.path.realpath(request["target_file"])
    target_line = int(request["target_line"])
    payload = request["payload"]

    hit = {"executed": False}

    def tracer(frame, event, arg):  # noqa: ANN001, ANN202
        if event == "line":
            if (frame.f_lineno == target_line
                    and os.path.realpath(frame.f_code.co_filename) == target_file):
                hit["executed"] = True
        return tracer

    saved_stdin, saved_stdout = sys.stdin, sys.stdout
    sys.stdin = io.StringIO(json.dumps(payload, ensure_ascii=False))
    sys.stdout = io.StringIO()
    try:
        sys.settrace(tracer)
        try:
            runpy.run_path(probe, run_name="__main__")
        except SystemExit:
            pass
        except BaseException:  # noqa: BLE001 - the probe reports its own errors
            pass
        finally:
            sys.settrace(None)
    finally:
        sys.stdin, sys.stdout = saved_stdin, saved_stdout

    print(json.dumps({"executed": hit["executed"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
