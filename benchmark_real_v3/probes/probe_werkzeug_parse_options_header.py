"""Observe parse_options_header for one declared header value."""
from __future__ import annotations

import json
import sys

from werkzeug.http import parse_options_header


def main() -> int:
    payload = json.load(sys.stdin)
    try:
        mimetype, options = parse_options_header(payload["value"])
        observation = {
            "outcome": "return",
            "mimetype": mimetype,
            "options": options,
        }
    except Exception as exc:  # noqa: BLE001
        observation = {
            "outcome": "raise",
            "type": type(exc).__name__,
            "message": str(exc),
        }
    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
