"""Observation probe for docutils/frontend.py:272 (smart-quotes spec trim)."""
import json

from docutils.frontend import validate_smartquotes_locales


def observe(spec):
    try:
        return {"out": validate_smartquotes_locales(None, [spec], None)}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}


print(json.dumps({
    "mask_space_padding": observe("en: abcd "),
    "expose_tab_padding": observe("en:\tabcd\t"),
    "control_unpadded": observe("en:abcd"),
}, ensure_ascii=False))
