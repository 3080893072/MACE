"""Observation probe for jsonschema/validators.py:1145 (JSON-pointer unescape)."""
import json
from jsonschema.validators import RefResolver

DOC = {"a~b": 1, "a/b": 2, "plain": 3, "nested": {"x~y": 4}}
RESOLVER = RefResolver(base_uri="", referrer={})


def resolve(fragment):
    try:
        return {"value": RESOLVER.resolve_fragment(DOC, fragment)}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}


print(json.dumps({
    "mask_tilde0": resolve("a~0b"),
    "mask_nested_tilde0": resolve("nested/x~0y"),
    "expose_tilde1": resolve("a~1b"),
    "control_plain": resolve("plain"),
}, ensure_ascii=False))
