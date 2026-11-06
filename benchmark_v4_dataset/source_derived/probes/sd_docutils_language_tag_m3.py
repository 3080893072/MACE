"""Observation probe for docutils/utils/__init__.py:704 (language tag)."""
import json

from docutils.utils import normalize_language_tag


def observe(tag):
    try:
        return {"out": normalize_language_tag(tag)}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}


print(json.dumps({
    "mask_two_separators": observe("de-AT-1901"),
    "expose_three_separators": observe("de-AT-1901-x"),
    "control_single_subtag": observe("en"),
}, ensure_ascii=False))
