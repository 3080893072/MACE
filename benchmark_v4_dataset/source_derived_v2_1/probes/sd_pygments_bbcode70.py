"""Observation probe for pygments/formatters/bbcode.py:70 (italic end tag)."""
import json
from pygments import highlight
from pygments.formatters import BBCodeFormatter
from pygments.lexers import PythonLexer
from pygments.style import Style
from pygments.token import Token


class Ital(Style):
    styles = {Token.Name: "italic"}


class ItalColor(Style):
    styles = {Token.Name: "italic #ff0000"}


class BoldOnly(Style):
    styles = {Token.Name: "bold"}


def render(style, codetag=False):
    try:
        return {"out": highlight("abc = 1", PythonLexer(),
                                 BBCodeFormatter(style=style,
                                                 codetag=codetag))}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}


print(json.dumps({
    "mask_italic": render(Ital),
    "expose_italic_color": render(ItalColor),
    "control_bold": render(BoldOnly),
    "mask_italic_codetag": render(Ital, codetag=True),
}, ensure_ascii=False))
