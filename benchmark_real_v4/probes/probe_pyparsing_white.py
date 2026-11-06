"""Observe pyparsing White's max/exact attributes after construction.

Payload ``max`` and ``exact`` are passed to the public ``White`` constructor.
The observation is the resulting ``maxLen`` and ``minLen``; with ``exact=0``
the assignment at 3371 is the only one that sets ``maxLen``, so the deletion
of A leaves the attribute unset and the probe raises.
"""
from __future__ import annotations

import json
import sys

from pyparsing import White


def main() -> int:
    payload = json.load(sys.stdin)
    try:
        ws = White(max=int(payload.get("max", 3)),
                   exact=int(payload.get("exact", 0)))
        observation = {
            "outcome": "return",
            "maxLen": ws.maxLen,
            "minLen": ws.minLen,
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
