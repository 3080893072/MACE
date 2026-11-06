"""Observation probe (generated)."""
import json

from coverage.files import _glob_to_regex

def observe(value):
    try:
        return {"out": _glob_to_regex(value)}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}

print(json.dumps({
    "mask_two_backslashes": observe('src\\a\\b.py'),
    "expose_three_backslashes": observe('src\\a\\b\\c.py'),
    "control_posix": observe('src/a/b.py'),
}, ensure_ascii=False))
