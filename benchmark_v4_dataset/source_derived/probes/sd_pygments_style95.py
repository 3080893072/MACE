"""Observation probe for pygments/style.py:95 (shared style cache entry)."""
import json
from pygments.style import Style
from pygments.token import Token


class S(Style):
    styles = {Token.Keyword: "italic", Token.Text: ""}


def lookup(token):
    try:
        d = S.style_for_token(token)
        return {k: d[k] for k in ("color", "bold", "italic", "underline")}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}


print(json.dumps({
    "mask_text": lookup(Token.Text),
    "mask_name_other": lookup(Token.Name.Other),
    "expose_keyword": lookup(Token.Keyword),
    "mask_operator_inherited": lookup(Token.Operator),
}, ensure_ascii=False))
