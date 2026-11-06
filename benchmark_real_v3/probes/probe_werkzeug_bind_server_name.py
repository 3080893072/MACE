"""Observe MapAdapter server name/subdomain after bind_to_environ."""
from __future__ import annotations

import io
import json
import sys

from werkzeug.routing import Map, Rule


def main() -> int:
    payload = json.load(sys.stdin)
    url_map = Map([Rule("/", endpoint="index")])
    env = {
        "REQUEST_METHOD": "GET",
        "SCRIPT_NAME": "",
        "PATH_INFO": "/",
        "QUERY_STRING": "",
        "SERVER_NAME": payload.get("host", "example.com"),
        "SERVER_PORT": "80",
        "HTTP_HOST": payload.get("host", "example.com"),
        "wsgi.url_scheme": "http",
        "wsgi.input": io.BytesIO(b""),
        "wsgi.errors": sys.stderr,
        "wsgi.version": (1, 0),
        "wsgi.multithread": False,
        "wsgi.multiprocess": False,
        "wsgi.run_once": False,
    }
    try:
        adapter = url_map.bind_to_environ(
            env,
            server_name=payload.get("server_name"),
            subdomain=payload.get("subdomain"),
        )
        observation = {
            "outcome": "return",
            "server_name": adapter.server_name,
            "subdomain": adapter.subdomain,
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
