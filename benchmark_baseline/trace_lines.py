"""Execute one public probe under sys.settrace and record executed lines.

The probe is the ordinary public-API observation script.  The harness only
records which source lines of the project file were executed; it never reads
an expected value or a hidden matrix.

Request JSON (path in argv[1])::

    {"probe": "<abs path>", "target_file": "<abs path>",
     "payload": {...}, "out": "<abs path>"}
"""
from __future__ import annotations

import io
import json
import os
import runpy
import sys


def main() -> int:
    request = json.loads(open(sys.argv[1], encoding="utf-8").read())
    target = os.path.realpath(request["target_file"])
    seen = set()

    def tracer(frame, event, arg):
        if event == "line":
            if os.path.realpath(frame.f_code.co_filename) == target:
                seen.add(frame.f_lineno)
        return tracer

    sys.stdin = io.StringIO(json.dumps(request["payload"]))
    sys.argv = [request["probe"]]
    sys.settrace(tracer)
    try:
        runpy.run_path(request["probe"], run_name="__main__")
    except SystemExit:
        pass
    finally:
        sys.settrace(None)
    with open(request["out"], "w", encoding="utf-8") as handle:
        handle.write(json.dumps({"lines": sorted(seen)}) + "\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
