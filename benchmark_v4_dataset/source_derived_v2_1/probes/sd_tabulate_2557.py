"""Observation probe for tabulate/__init__.py:2557 (TextWrapper cur_len)."""
import json
from tabulate import _CustomTextWrap


def wrap(text, **kwargs):
    try:
        return {"lines": _CustomTextWrap(**kwargs).wrap(text)}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}


print(json.dumps({
    "mask_two_lines": wrap(
        "word word word word word", width=10, max_lines=2),
    "expose_three_lines": wrap(
        "one two three four five six seven eight", width=10, max_lines=3),
    "control_line_fits": wrap(
        "aaa bbb ccc ddd", width=8, max_lines=2),
    "control_no_max_lines": wrap(
        "word word word word word", width=10),
}, ensure_ascii=False))
