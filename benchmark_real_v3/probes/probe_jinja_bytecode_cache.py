"""Observe template loading through a user-provided bytecode cache.

The cache is a public extension point (``jinja2.bcc.BytecodeCache``).  The
observation is the public rendering result; the cache never returns anything
except code the caller compiled with ``Environment.compile``.
"""
from __future__ import annotations

import json
import sys

from jinja2 import DictLoader
from jinja2 import Environment
from jinja2.bccache import BytecodeCache


class MemoryCache(BytecodeCache):
    def __init__(self, code):
        super().__init__()
        self.code = code
        self.loads = 0
        self.dumps = 0

    def load_bytecode(self, bucket):
        self.loads += 1
        bucket.code = self.code

    def dump_bytecode(self, bucket):
        self.dumps += 1

    def clear(self):
        pass


def main() -> int:
    payload = json.load(sys.stdin)
    source = payload["template"]
    # Compile outside any cached environment: same public API users use.
    bootstrap = Environment(loader=DictLoader({"t": source}))
    code = bootstrap.compile(
        payload.get("cached_source", source), "t", None)
    cache = MemoryCache(code)
    env = Environment(
        loader=DictLoader({"t": source}), bytecode_cache=cache)
    try:
        rendered = env.get_template("t").render(**payload.get("context", {}))
        observation = {
            "outcome": "return",
            "value": rendered,
            "cache_loads": cache.loads,
            "cache_dumps": cache.dumps,
        }
    except Exception as exc:  # noqa: BLE001
        observation = {
            "outcome": "raise",
            "type": type(exc).__name__,
            "message": str(exc),
            "cache_loads": cache.loads,
            "cache_dumps": cache.dumps,
        }
    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
