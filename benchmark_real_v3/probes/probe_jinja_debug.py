"""Observe a template runtime error's public traceback shape."""
from __future__ import annotations

import json
import sys
import traceback

from jinja2 import Environment


def main() -> int:
    payload = json.load(sys.stdin)
    env = Environment()
    try:
        template = env.from_string(payload["template"])
        result = template.render(**payload.get("context", {}))
        observation = {"outcome": "return", "value": result}
    except Exception as exc:  # noqa: BLE001 - the exception is the observation
        frames = []
        tb = exc.__traceback__
        while tb is not None:
            code = tb.tb_frame.f_code
            frames.append({
                "function": code.co_name,
                "file": code.co_filename.replace("\\", "/").split("/")[-1],
                "lineno": tb.tb_lineno,
            })
            tb = tb.tb_next
        text = "".join(traceback.format_exception(
            type(exc), exc, exc.__traceback__))
        observation = {
            "outcome": "raise",
            "type": type(exc).__name__,
            "message": str(exc),
            "frames": frames,
            "formatted_tail": text.splitlines()[-6:],
        }
    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
