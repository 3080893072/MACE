"""Executable input generators for the five pilot tasks.

The JSON task files carry explicit, frozen case lists.  These generators are
the executable form of the same domains; the builder and the scorer call them
instead of trusting a hand-copied list.
"""
from __future__ import annotations

import copy
from typing import Any, Dict

from . import specs


def controlled_cases(task_id: str) -> list[dict[str, Any]]:
    return copy.deepcopy(specs.CONTROLLED[task_id]["domain_cases"])


# --- real task 1: pluggy _formatdef -----------------------------------------

def _function1():
    pass


def _function2(arg1):
    pass


def _function3(arg1, arg2="qwe"):
    pass


def _function4(arg1, *args, **kwargs):
    pass


def _function5(a, b=2, *, c=3):
    pass


def _function6(*args, **kwargs):
    pass


def _function7(x: int, y: str = "z") -> bool:
    return True


def _function8():
    pass


_FORMATDEF_CASES = {
    "function1": _function1,
    "function2": _function2,
    "function3": _function3,
    "function4": _function4,
    "function5": _function5,
    "function6": _function6,
    "function7": _function7,
    "function8": _function8,
}


def formatdef_cases() -> Dict[str, Any]:
    """Case id -> function object.  The first four are the ones used by the
    real ``test_formatdef``; the last four extend the frozen domain."""
    return dict(_FORMATDEF_CASES)


# --- real task 2: pluggy set() on a keys view -------------------------------

_SETDIFF_CASES = {
    "empty_empty": ([], {}),
    "ab_a": (["a", "b"], {"a": 1}),
    "ab_ab": (["a", "b"], {"a": 1, "b": 2}),
    "a_extra": (["a"], {"a": 1, "b": 2}),
    "abc_none": (["a", "b", "c"], {}),
    "a_empty": (["a"], {}),
}


def setdiff_cases() -> Dict[str, tuple[list[str], dict[str, int]]]:
    return {k: (list(v[0]), dict(v[1])) for k, v in _SETDIFF_CASES.items()}


def real_cases(task_id: str) -> Dict[str, Any]:
    if task_id == "real_formatdef":
        return formatdef_cases()
    if task_id == "real_setdiff":
        return setdiff_cases()
    raise KeyError(task_id)
