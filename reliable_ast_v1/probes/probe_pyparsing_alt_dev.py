"""Dev probe: exercise pyparsing MatchFirst with fatal/ordinary exceptions.

Payload: {"text": "options(100) step(A)", "mode": "and"}.
The observation is the public parse result or the raised exception.
"""
from __future__ import annotations
import json, sys
import pyparsing as pp
from pyparsing import pyparsing_common as ppc

def main() -> int:
    payload = json.load(sys.stdin)
    text = payload.get("text", "options(100) step(A)")
    try:
        option_expr = pp.Keyword("options") - "(" + ppc.integer + ")"
        step_expr1 = pp.Keyword("step") - "(" + ppc.integer + ")"
        step_expr2 = pp.Keyword("step") - "(" + ppc.integer + "Z" + ")"
        step_expr = step_expr1 ^ step_expr2
        parser = option_expr & step_expr[...]
        result = parser.parse_string(text)
        observation = {"outcome": "return", "result": result.as_list()}
    except BaseException as exc:
        observation = {"outcome": "raise", "type": type(exc).__name__, "message": str(exc)[:300]}
    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
