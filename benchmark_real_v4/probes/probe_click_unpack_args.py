"""Observe click's public argument-unpacking paths.

Payload ``mode`` selects the command shape:

* ``variadic`` - one ``nargs=-1`` argument; the wildcard path runs, never
  popping from the converted deque;
* ``single``   - one normal argument; ``_fetch`` pops from the deque.

The observation is the CLI result: exit code, output, and exception type.
"""
from __future__ import annotations

import json
import sys

import click
from click.testing import CliRunner


def main() -> int:
    payload = json.load(sys.stdin)
    mode = payload.get("mode", "variadic")
    values = list(payload.get("values", ["alpha", "beta"]))

    if mode == "variadic":
        @click.command()
        @click.argument("files", nargs=-1)
        def cli(files):
            click.echo(",".join(files))
    else:
        @click.command()
        @click.argument("value")
        def cli(value):
            click.echo(value)

    result = CliRunner().invoke(cli, values)
    observation = {
        "outcome": "return",
        "exit_code": result.exit_code,
        "output": result.output,
        "exception": type(result.exception).__name__ if result.exception else None,
    }
    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
