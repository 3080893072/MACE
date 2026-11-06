"""Observe get_host for a declared Host header / server pair."""
from __future__ import annotations

import json
import sys

from werkzeug.sansio.utils import get_host


def main() -> int:
    payload = json.load(sys.stdin)
    server = payload.get("server")
    if server is not None:
        server = tuple(server)
    try:
        host = get_host(
            payload.get("scheme", "http"),
            payload.get("host_header"),
            server,
        )
        observation = {"outcome": "return", "host": host}
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
