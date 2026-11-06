"""Dev probe: observe pyparsing Or/MatchFirst results including failure details.

run_tests() catches parse failures, so the probe can observe the accumulated
error locations/messages without crashing.  This is a public API.
"""
from __future__ import annotations
import json, sys
import pyparsing as pp

def _desc(result):
    if isinstance(result, BaseException):
        return {"kind": "exc", "type": type(result).__name__,
                "loc": getattr(result, "loc", None),
                "msg": str(getattr(result, "msg", result))[:120]}
    try:
        return {"kind": "ok", "value": result.as_list()}
    except Exception:
        return {"kind": "other", "repr": repr(result)[:120]}

def main() -> int:
    payload = json.load(sys.stdin)
    lines = payload.get("lines", ["abc", "123", "xyz", "abc 123"])
    try:
        expr = pp.Word("abc") ^ pp.Word("123")
        success, results = expr.run_tests("\n".join(lines) + "\n", printResults=False)
        observation = {"outcome": "return", "success": bool(success),
                       "results": [_desc(r) for r in results]}
    except BaseException as exc:
        observation = {"outcome": "raise", "type": type(exc).__name__,
                       "message": str(exc)[:300]}
    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
