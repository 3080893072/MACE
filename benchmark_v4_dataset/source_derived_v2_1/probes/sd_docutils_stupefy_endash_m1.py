"""Observation probe (generated)."""
import json

from docutils.utils.smartquotes import stupefyEntities

def observe(value):
    try:
        return {"out": stupefyEntities(value)}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}

print(json.dumps({
    "mask_one_endash": observe('left–right'),
    "expose_two_endashes": observe('a–b–c'),
    "control_plain": observe('plain text'),
}, ensure_ascii=False))
