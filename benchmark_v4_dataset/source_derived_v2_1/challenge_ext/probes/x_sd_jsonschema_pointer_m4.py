"""Observation probe (generated)."""
import json

from jsonschema.validators import RefResolver

def observe(value):
    try:
        resolver = RefResolver.from_schema({})
        cases = {
            "mask": ({"a/b": 1}, "/a~1b"),
            "expose": ({"a/b#c?d": 2}, "/a~1b#c?d"),
            "control": ({"abc": 3}, "/abc"),
        }
        document, fragment = cases[value]
        return {"out": resolver.resolve_fragment(document, fragment)}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}

print(json.dumps({
    "mask_plain_segment": observe('mask'),
    "expose_marker_segment": observe('expose'),
    "control_no_escape": observe('control'),
}, ensure_ascii=False))
