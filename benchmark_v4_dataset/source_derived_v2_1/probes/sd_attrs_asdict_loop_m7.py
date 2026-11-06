"""Observation probe (generated)."""
import json

import attr

One = attr.make_class("One", ["x"])
Two = attr.make_class("Two", ["x", "y"])


def observe(value):
    try:
        if value == "single":
            return {"out": attr.asdict(One(1))}
        return {"out": attr.asdict(Two(1, 2))}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}

print(json.dumps({
    "mask_single_attr": observe("single"),
    "expose_two_attrs": observe("two"),
}, ensure_ascii=False))
