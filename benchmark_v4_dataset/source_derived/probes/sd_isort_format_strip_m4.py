"""Observation probe (generated)."""
import json

from isort.format import format_simplified

def observe(value):
    try:
        return {"out": format_simplified(value)}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}

print(json.dumps({
    "mask_padded": observe(' a.b '),
    "expose_tab_newline": observe('\ta.b\n'),
    "control_plain": observe('a.b'),
}, ensure_ascii=False))
