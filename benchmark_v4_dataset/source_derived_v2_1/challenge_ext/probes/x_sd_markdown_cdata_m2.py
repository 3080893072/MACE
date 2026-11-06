"""Observation probe (generated)."""
import json

from markdown.serializers import _escape_cdata

def observe(value):
    try:
        return {"out": _escape_cdata(value)}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}

print(json.dumps({
    "mask_two_lt": observe('<a<b'),
    "expose_three_lt": observe('<a<b<c'),
    "control_plain": observe('ab'),
}, ensure_ascii=False))
