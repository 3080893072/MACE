"""Observe ParserElement multiplication with a (Ellipsis, n) tuple."""
from __future__ import annotations

import json
import sys

from pyparsing import Word, alphas


def main() -> int:
    payload = json.load(sys.stdin)
    expr = Word(alphas)
    other = tuple(
        Ellipsis if item == "Ellipsis" else item
        for item in payload.get("other", ["Ellipsis", 3])
    )
    try:
        result = expr * other
        observation = {
            "outcome": "return",
            "type": type(result).__name__,
            "structure": repr(result)[:300],
        }
    except BaseException as exc:  # noqa: BLE001 - probe must report failures
        observation = {
            "outcome": "raise",
            "type": type(exc).__name__,
            "message": str(exc)[:300],
        }
    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
