"""Observation probe (generated)."""
import json

from humanize import naturalsize

def observe(value):
    try:
        return {"out": naturalsize(value[0], gnu=value[1])}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}

print(json.dumps({
    "mask_gnu_positive": observe([2048, True]),
    "expose_gnu_negative": observe([-4096, True]),
    "control_decimal": observe([2048, False]),
}, ensure_ascii=False))
