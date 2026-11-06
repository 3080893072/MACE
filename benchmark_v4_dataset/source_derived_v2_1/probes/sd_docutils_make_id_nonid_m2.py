"""Observation probe for docutils/nodes.py:2239 (non-identifier runs)."""
import json

from docutils import nodes


def observe(text):
    try:
        return {"out": nodes.make_id(text)}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}


print(json.dumps({
    "mask_two_runs": observe("a,b!c"),
    "expose_three_runs": observe("a,b!c?d"),
    "control_no_runs": observe("abc"),
}, ensure_ascii=False))
