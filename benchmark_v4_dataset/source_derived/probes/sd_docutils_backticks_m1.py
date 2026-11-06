"""Observation probe (generated)."""
import json

from docutils.utils.smartquotes import educateBackticks

def observe(value):
    try:
        return {"out": educateBackticks(value)}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}

print(json.dumps({
    "mask_one_backtick": observe('a``b'),
    "expose_two_backticks": observe('a``b``c'),
    "control_plain": observe('plain text'),
}, ensure_ascii=False))
