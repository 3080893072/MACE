"""Observation probe for pygments/formatters/bbcode.py:64 (colour end tag)."""
import json
from pygments import highlight
from pygments.formatters import BBCodeFormatter
from pygments.lexers import PythonLexer
from pygments.style import Style
from pygments.token import Token


class Color(Style):
    styles = {Token.Name: "#ff0000"}


class ColorUnderline(Style):
    styles = {Token.Name: "#ff0000 underline"}


class BoldOnly(Style):
    styles = {Token.Name: "bold"}


def render(style):
    try:
        return {"out": highlight("abc = 1", PythonLexer(),
                                 BBCodeFormatter(style=style))}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}


print(json.dumps({
    "mask_color": render(Color),
    "expose_color_underline": render(ColorUnderline),
    "control_bold": render(BoldOnly),
}, ensure_ascii=False))
