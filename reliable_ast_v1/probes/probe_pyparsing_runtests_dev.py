"""Dev probe: run pyparsing's public run_tests harness on a MatchFirst/Or.

Payload: {"text": "..."} lines passed to run_tests.  run_tests catches parse
exceptions internally and returns a success flag, so the observation is a
normal return even when individual expressions raise.
"""
from __future__ import annotations
import json, sys
import pyparsing as pp

def main() -> int:
    payload = json.load(sys.stdin)
    text = payload.get("text", "abc\n123\nxyz\n")
    try:
        expr = pp.Word("abc") ^ pp.Word("123")
        success, results = expr.run_tests(text, printResults=False)
        observation = {"outcome": "return", "success": bool(success), "n": len(results)}
    except BaseException as exc:
        observation = {"outcome": "raise", "type": type(exc).__name__, "message": str(exc)[:300]}
    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
