"""Observe the bool-flag UNSET branch of click Option.process_value.

Payload ``callback`` selects what the option callback does:

* ``const``  - returns a constant, independent of the supplied value;
* ``echo``   - returns the supplied value together with its type;
* ``none``   - no callback, so the value produced by the branch is visible.

The observation is the public return value of ``process_value``.
"""
from __future__ import annotations

import json
import sys

import click


def main() -> int:
    payload = json.load(sys.stdin)
    mode = payload.get("callback", "const")

    if mode == "const":
        def callback(ctx, param, value):
            return "CONST"
    elif mode == "echo":
        def callback(ctx, param, value):
            return [type(value).__name__, value]
    else:
        callback = None

    option = click.Option(["--flag/--no-flag"], is_flag=True, callback=callback)
    command = click.Command("probe", params=[option])
    ctx = click.Context(command)
    try:
        result = option.process_value(ctx, click.core.UNSET)
        observation = {
            "outcome": "return",
            "result_type": type(result).__name__,
            "result": result if isinstance(result, (str, int, list, bool, tuple))
            else repr(result),
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
