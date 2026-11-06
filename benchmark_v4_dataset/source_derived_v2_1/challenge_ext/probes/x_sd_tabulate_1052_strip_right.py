"""Observation probe for tabulate/__init__.py:1052 (right-alignment strip)."""
import json
import tabulate


def render(rows):
    try:
        return {"out": tabulate.tabulate(
            rows, tablefmt="plain", colalign=("right",))}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}


print(json.dumps({
    "mask_spaces": render([["  a  "], ["b"]]),
    "expose_tabs": render([["\ta\t"], ["b"]]),
    "control_plain": render([["a"], ["b"]]),
    "control_center": {"out": tabulate.tabulate(
        [["  a  "], ["b"]], tablefmt="plain", colalign=("center",))},
}, ensure_ascii=False))
