"""Observation probe (generated)."""
import json

from docutils.utils.smartquotes import educateBackticks

def observe(value):
    try:
        return {"out": educateBackticks(value)}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}

print(json.dumps({
    "nc_one_pair": observe('a``b'),
    "nc_two_pairs": observe('a``b``c'),
    "nc_three_pairs": observe('a``b``c``d'),
}, ensure_ascii=False))
