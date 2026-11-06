"""Observation probe for tabulate/__init__.py:1056 (center-alignment strip)."""
import json
import tabulate


def render(rows, align):
    try:
        return {"out": tabulate.tabulate(
            rows, tablefmt="plain", colalign=(align,))}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}


print(json.dumps({
    "mask_numeric": render([["  12  "], ["7"]], "center"),
    "expose_alpha": render([["  ab  "], ["c"]], "center"),
    "control_right_numeric": render([["  12  "], ["7"]], "right"),
    "control_no_space": render([["12"], ["7"]], "center"),
}, ensure_ascii=False))
