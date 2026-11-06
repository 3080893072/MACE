"""Probe for pygments BBCodeFormatter line 64 (color closing tag)."""
import json

from pygments import highlight
from pygments.formatters.bbcode import BBCodeFormatter
from pygments.lexers.markup import MarkdownLexer
from pygments.lexers.python import PythonLexer

CASES = {
    # Generic.Strong is bold without colour in the default style, so this
    # input exercises the bold closing tag but emits no colour token.
    "mask_strong_markdown": lambda: highlight(
        "**strong text**", MarkdownLexer(), BBCodeFormatter()),
    # `def` is a coloured keyword: the colour closing tag is observable.
    "expose_keyword_python": lambda: highlight(
        "def f(): pass", PythonLexer(), BBCodeFormatter()),
    # A bare name has no style at all, so no closing tag is needed.
    "control_plain_name": lambda: highlight(
        "foo", PythonLexer(), BBCodeFormatter()),
}

out = {}
for name, fn in CASES.items():
    try:
        out[name] = {"kind": "value", "value": fn()}
    except Exception as exc:
        out[name] = {"kind": "error", "error": type(exc).__name__,
                     "message": str(exc)}
print(json.dumps(out))
