"""Dev probe: exercise QuotedString.parseImpl with escapes through public API."""
from __future__ import annotations
import json, sys
from pyparsing import QuotedString

def main() -> int:
    payload = json.load(sys.stdin)
    try:
        expr = QuotedString(
            payload.get("quote", '"'),
            escChar=payload.get("esc", "\\"),
            escQuote=payload.get("esc_quote"),
            convertWhitespaceEscapes=bool(payload.get("convert_ws", True)),
            unquoteResults=bool(payload.get("unquote", True)),
        )
        result = expr.parse_string(payload.get("text", '"a\tb"'))
        observation = {"outcome": "return", "result": result.as_list()}
    except BaseException as exc:
        observation = {"outcome": "raise", "type": type(exc).__name__, "message": str(exc)[:300]}
    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
