"""Case construction and local-effect checks for the two real tasks."""
from __future__ import annotations

import inspect
from typing import Any, Dict, List, Tuple

from . import generators
from .engine import canonical


def case_args(task_id: str, case_id: str) -> Dict[str, Any]:
    if task_id == "real_formatdef":
        return {"func": generators.formatdef_cases()[case_id]}
    if task_id == "real_setdiff":
        declared, provided = generators.setdiff_cases()[case_id]
        return {"declared": declared, "provided": provided}
    raise KeyError(task_id)


def case_ids(task_id: str) -> List[str]:
    return [case["id"] for case in _domain(task_id)]


def cases_with_args(task_id: str) -> List[Tuple[str, Dict[str, Any]]]:
    return [(cid, case_args(task_id, cid)) for cid in case_ids(task_id)]


def _domain(task_id: str) -> List[Dict[str, Any]]:
    if task_id == "real_formatdef":
        from .specs import REAL
        return REAL[task_id]["domain_cases"]
    if task_id == "real_setdiff":
        from .specs import REAL
        return REAL[task_id]["domain_cases"]
    raise KeyError(task_id)


def local_effect(task_id: str) -> Dict[str, Any]:
    """Whether the deleted operation changes any local value, per case.

    For ``_formatdef`` there is no assignment: the deleted ``str()`` call
    changes the *type* of the value handed to the outer ``%s`` (str vs
    Signature), so we report the type difference of that intermediate value.
    For the keys-view case the assigned set is value-identical, so A has no
    local effect at all.
    """
    out: Dict[str, Any] = {}
    if task_id == "real_formatdef":
        for cid, args in cases_with_args(task_id):
            func = args["func"]
            sig = inspect.signature(func)
            out[cid] = {
                "local_effect": type(sig) is not type(str(sig)),
                "plus_type": "str",
                "minus_type": type(sig).__name__,
            }
        return out
    if task_id == "real_setdiff":
        for cid, args in cases_with_args(task_id):
            declared, provided = args["declared"], args["provided"]
            plus = set(declared) - set(provided.keys())
            minus = set(declared) - provided.keys()
            out[cid] = {
                "local_effect": canonical(plus) != canonical(minus),
                "plus": sorted(plus),
                "minus": sorted(minus),
            }
        return out
    raise KeyError(task_id)
