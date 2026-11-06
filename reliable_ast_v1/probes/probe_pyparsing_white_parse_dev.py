"""Dev probe: exercise White.parseImpl through the public API.

Payload: {"text": "   ", "max": 4, "exact": 0, "min": 0}
The observation is the parsed substring or the raised exception.
"""
from __future__ import annotations
import json, sys
from pyparsing import White

def main() -> int:
    payload = json.load(sys.stdin)
    try:
        ws = White(" ", max=int(payload.get("max", 4)), exact=int(payload.get("exact", 0)), min=int(payload.get("min", 0)))
        result = ws.parse_string(payload.get("text", "   "))
        observation = {"outcome": "return", "result": result.as_list()}
    except BaseException as exc:
        observation = {"outcome": "raise", "type": type(exc).__name__, "message": str(exc)[:300]}
    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
