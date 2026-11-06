"""Observation probe (generated)."""
import json

from pygments import highlight
from pygments.formatters import BBCodeFormatter
from pygments.lexers import PythonLexer
from pygments.style import Style
from pygments.token import Token
class Color(Style):
    styles = {Token.Name: "#ff0000"}
class Color2(Style):
    styles = {Token.Name: "#00ff00"}
CASES = {
    "one": (Color, "a = 1"),
    "two": (Color, "a = 1\nb = 2"),
    "other": (Color2, "c = 3"),
}
def render(style, code):
    return {"out": highlight(code, PythonLexer(), BBCodeFormatter(style=style))}

def observe(value):
    try:
        style, code = CASES[value]
        return render(style, code)
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}

print(json.dumps({
    "nc_one_token": observe('one'),
    "nc_two_tokens": observe('two'),
    "nc_other_colour": observe('other'),
}, ensure_ascii=False))
