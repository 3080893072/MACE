"""Observe postParse and parse-action interaction through pyparsing's API.

Payload fields:

* ``kind`` - ``group``, ``combine`` or ``suppress``;
* ``action`` - when true, attach an action that returns ``["CONST"]`` and
  ignores the tokens it receives.

The observation is the final parsed result.  With an action the post-parse
normalization is invisible; without one it shows through.
"""
from __future__ import annotations

import json
import sys

import pyparsing as pp


def _build(kind: str):
    if kind == "group":
        expr = pp.Group(pp.Word(pp.alphas))
        text = "abc"
    elif kind == "combine":
        expr = pp.Combine(
            pp.Word(pp.alphas, exact=2) + pp.Word(pp.alphas, exact=2)
        )
        text = "abcd"
    elif kind == "suppress":
        expr = pp.Suppress(pp.Word(pp.alphas))
        text = "abc"
    else:
        raise ValueError(f"unknown kind: {kind}")
    return expr, text


def main() -> int:
    payload = json.load(sys.stdin)
    kind = payload.get("kind", "group")
    with_action = bool(payload.get("action", True))
    expr, text = _build(kind)
    if with_action:
        expr.add_parse_action(lambda s, l, t: ["CONST"])
    try:
        result = expr.parse_string(text)
    except Exception as exc:  # noqa: BLE001 - report the public outcome
        observation = {
            "outcome": "raise",
            "type": type(exc).__name__,
            "message": str(exc),
        }
    else:
        observation = {"outcome": "return", "result": result.as_list()}
    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
