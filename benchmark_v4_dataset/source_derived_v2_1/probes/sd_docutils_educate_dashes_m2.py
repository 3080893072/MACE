"""Observation probe (generated)."""
import json

from docutils.utils.smartquotes import educateDashes

def observe(value):
    try:
        return {"out": educateDashes(value)}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}

print(json.dumps({
    "mask_two_triple": observe('a---b---c'),
    "expose_three_triple": observe('a---b---c---d'),
    "control_plain": observe('a-b'),
}, ensure_ascii=False))
