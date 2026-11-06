"""Observe Parameter.process_value with a controlled callback and value.

The payload is a legal public-API call: build a Click context, an INT option
with an explicit callback, and process a raw value.  ``const`` returns a value
that does not depend on the (type-cast) input; ``echo`` returns the input
together with its type, so the cast is visible.
"""
from __future__ import annotations

import json
import sys

import click


def main() -> int:
    payload = json.load(sys.stdin)
    raw = payload.get("value", "42")
    mode = payload.get("callback", "const")

    if mode == "const":
        def callback(ctx, param, value):
            return "CONST"
    else:
        def callback(ctx, param, value):
            return [type(value).__name__, value]

    option = click.Option(["--num"], type=click.INT, callback=callback)
    command = click.Command("probe", params=[option])
    ctx = click.Context(command)
    try:
        result = option.process_value(ctx, raw)
        observation = {
            "outcome": "return",
            "result_type": type(result).__name__,
            "result": result if isinstance(result, (str, int, list)) else repr(result),
        }
    except BaseException as exc:  # noqa: BLE001 - probe reports failures
        observation = {
            "outcome": "raise",
            "type": type(exc).__name__,
            "message": str(exc)[:300],
        }
    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
