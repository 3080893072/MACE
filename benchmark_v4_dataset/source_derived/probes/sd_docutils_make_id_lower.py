"""Observation probe for docutils/nodes.py:2231 (make_id case folding)."""
import json

from docutils import nodes


def observe(text):
    try:
        return {"out": nodes.make_id(text)}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}


print(json.dumps({
    "mask_ascii_mixed_case": observe("Hello World"),
    "expose_non_ascii": observe("Ärger im Büro"),
    "control_lowercase": observe("already_lower"),
}, ensure_ascii=False))
