"""Observation probe for pygments/formatters/latex.py:297 (italic command)."""
import json
from pygments.formatters import LatexFormatter
from pygments.style import Style
from pygments.token import Token


class Ital(Style):
    styles = {Token.Name: "italic"}


class ItalColor(Style):
    styles = {Token.Name: "italic #ff0000"}


class BoldOnly(Style):
    styles = {Token.Name: "bold"}


def defs(style, full):
    try:
        return {"defs": LatexFormatter(style=style, full=full).get_style_defs()}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}


print(json.dumps({
    "mask_inline_italic": defs(Ital, False),
    "mask_inline_italic_color": defs(ItalColor, False),
    "expose_full_italic": defs(Ital, True),
    "control_inline_bold": defs(BoldOnly, False),
}, ensure_ascii=False))
