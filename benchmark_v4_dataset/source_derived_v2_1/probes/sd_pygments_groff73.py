"""Observation probe for pygments/formatters/groff.py:73 (italic reset)."""
import json
from pygments import highlight
from pygments.formatters import GroffFormatter
from pygments.lexers import PythonLexer
from pygments.style import Style
from pygments.token import Token


class Ital(Style):
    styles = {Token.Name: "italic"}


class BoldOnly(Style):
    styles = {Token.Name: "bold"}


def render(style, monospaced):
    try:
        return {"out": highlight("abc = 1", PythonLexer(),
                                 GroffFormatter(style=style,
                                                monospaced=monospaced))}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}


print(json.dumps({
    "mask_italic_mono": render(Ital, True),
    "expose_italic_nonmono": render(Ital, False),
    "control_bold_mono": render(BoldOnly, True),
}, ensure_ascii=False))
