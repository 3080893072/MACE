"""Dev probe: exercise CharsNotIn.parseImpl (loop at core.py:3310/3313)."""
from __future__ import annotations
import json, sys
import pyparsing as pp

def main() -> int:
    payload = json.load(sys.stdin)
    try:
        expr = pp.CharsNotIn(
            payload.get("not_chars", "x"),
            min=int(payload.get("min", 1)),
            max=int(payload.get("max", 0)),
            exact=int(payload.get("exact", 0)),
        )
        result = expr.parse_string(payload.get("text", "aaaa"))
        observation = {"outcome": "return", "result": result.as_list()}
    except BaseException as exc:
        observation = {"outcome": "raise", "type": type(exc).__name__,
                       "message": str(exc)[:300]}
    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
