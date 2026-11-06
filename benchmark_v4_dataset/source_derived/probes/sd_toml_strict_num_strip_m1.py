"""Observation probe for toml/decoder.py:91 (_strictly_valid_num trim)."""
import json

from toml.decoder import _strictly_valid_num


def observe(text):
    try:
        return {"out": _strictly_valid_num(text)}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}


print(json.dumps({
    "mask_space_padded_leading_zero": observe(" 01 "),
    "expose_tab_padded_leading_zero": observe("\t01\t"),
    "control_plain_integer": observe("1"),
}, ensure_ascii=False))
