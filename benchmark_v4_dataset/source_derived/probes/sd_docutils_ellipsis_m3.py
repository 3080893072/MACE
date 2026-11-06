"""Observation probe (generated)."""
import json

from docutils.utils.smartquotes import educateEllipses

def observe(value):
    try:
        return {"out": educateEllipses(value)}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}

print(json.dumps({
    "mask_three_ellipses": observe('a...b...c...d'),
    "expose_four_ellipses": observe('a...b...c...d...e'),
    "control_plain": observe('plain text'),
}, ensure_ascii=False))
