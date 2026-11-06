"""Pytest plugin: per-test A/U execution, local state and observations.

Loaded by :mod:`benchmark_real_v3.story_validation`; the task configuration is
read from ``MACE_STORY_CONFIG`` and the output path from ``MACE_STORY_OUT``.
The plugin does not import any benchmark controller module and does not modify
the tested project.

Tracing is restricted to the handful of source files that contain A, U or an
observation function.  For A and single-line U records ``after`` is captured
at the next event in the same frame (normally the next source line), not at
function return; for a U block it is captured when execution leaves the
declared line range.  This prevents a later U overwrite from being attributed
to A.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

_CONFIG: Dict[str, Any] = {}
_TESTS: Dict[str, Dict[str, Any]] = {}
_REPORTS: Dict[str, Dict[str, Any]] = {}
_CURRENT: Dict[str, Any] | None = None
_OBS_SEQ = 0
_EXC: Dict[int, tuple] = {}
_WATCHED: set[str] = set()
_CODE_INFO: Dict[int, Tuple[str, bool]] = {}


def _safe(value: Any, depth: int = 0) -> Any:
    """Small JSON-safe rendering; never call user code beyond repr()."""
    try:
        if value is None or isinstance(value, (bool, int, float)):
            return value
        if isinstance(value, str):
            return value if len(value) <= 1000 else value[:1000] + "...<truncated>"
        if isinstance(value, (bytes, bytearray)):
            return {
                "type": type(value).__name__,
                "length": len(value),
                "repr": repr(bytes(value[:80])),
            }
        if depth < 2 and isinstance(value, (list, tuple)):
            return {
                "type": type(value).__name__,
                "items": [_safe(item, depth + 1) for item in value[:12]],
                "length": len(value),
            }
        if depth < 2 and isinstance(value, dict):
            return {
                "type": "dict",
                "keys": [repr(key)[:80] for key in list(value)[:12]],
                "length": len(value),
            }
        text = repr(value)
        return {
            "type": type(value).__name__,
            "repr": text[:300] + ("..." if len(text) > 300 else ""),
        }
    except BaseException as exc:  # noqa: BLE001 - instrumentation must not fail
        return {"type": type(value).__name__, "repr_error": type(exc).__name__}


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _same(left: Any, right: Any) -> bool:
    return _canon(left) == _canon(right)


def _abs(root: str, rel: str) -> str:
    return os.path.normcase(os.path.realpath(os.path.join(root, rel)))


def _class_name(frame) -> str:
    self_obj = frame.f_locals.get("self")
    return type(self_obj).__name__ if self_obj is not None else ""


def _class_matches(frame, wanted: str) -> bool:
    """Inherited methods run with a subclass ``self``; accept the MRO."""
    self_obj = frame.f_locals.get("self")
    if self_obj is None:
        return False
    return wanted in [klass.__name__ for klass in type(self_obj).__mro__]


def _matches_obs(frame) -> Dict[str, Any] | None:
    key, watched = _frame_info(frame)
    if not watched:
        return None
    for spec in _CONFIG.get("observations", []):
        if key != spec["_abs_file"]:
            continue
        if frame.f_code.co_name != spec["co_name"]:
            continue
        if spec.get("class_name") and not _class_matches(
                frame, spec["class_name"]):
            continue
        return spec
    return None


def _frame_info(frame) -> Tuple[str, bool]:
    code = frame.f_code
    cid = id(code)
    info = _CODE_INFO.get(cid)
    if info is None:
        key = os.path.normcase(os.path.realpath(code.co_filename))
        info = (key, key in _WATCHED)
        _CODE_INFO[cid] = info
    return info


def _mapping(value: Dict[str, Any]) -> Dict[str, Any]:
    """Serialize a small controller-owned mapping with its values intact."""
    return {key: _safe(item, 1) for key, item in value.items()}


def _target_value(frame, spec: Dict[str, Any]) -> Any:
    """Read the stored location named by an A/U spec (local, attr or item)."""
    kind = spec.get("key_kind", "name")
    if kind == "attr":
        obj = frame.f_locals.get(spec.get("key_obj", "self"))
        return _safe(getattr(obj, spec.get("var", ""), "<missing>"))
    if kind == "sub":
        obj = frame.f_locals.get(spec.get("key_obj", ""))
        try:
            return _safe(obj[spec.get("key_index")])
        except BaseException:  # noqa: BLE001 - instrumentation only
            return "<missing>"
    return _safe(frame.f_locals.get(spec.get("var", ""), "<unbound>"))


def _obs_value(frame, spec: Dict[str, Any], arg: Any) -> Any:
    kind = spec.get("kind", "value")
    if kind == "value":
        return _safe(arg)
    if kind == "adapter":
        return _mapping({
            "server_name": getattr(arg, "server_name", "<missing>"),
            "subdomain": getattr(arg, "subdomain", "<missing>"),
        })
    if kind == "local_var":
        return _safe(frame.f_locals.get(spec.get("var", ""), "<missing>"))
    if kind == "attribute":
        obj = frame.f_locals.get(spec.get("obj_var", "self"))
        return _safe(getattr(obj, spec.get("attr", ""), "<missing>"))
    if kind == "item":
        obj = frame.f_locals.get(spec.get("obj_var", ""))
        try:
            return _safe(obj[spec.get("index")])
        except BaseException:  # noqa: BLE001
            return "<missing>"
    if kind == "item_all":
        obj = frame.f_locals.get(spec.get("obj_var", ""))
        try:
            return {"type": type(obj).__name__, "repr": repr(obj)[:500]}
        except BaseException:  # noqa: BLE001
            return "<missing>"
    if kind == "self_filename":
        self_obj = frame.f_locals.get("self")
        value = getattr(self_obj, "filename", "<missing>")
        return _mapping({
            "filename": value,
            "filename_type": type(value).__name__,
        })
    return _safe(arg)


def _record(bucket: Dict[int, Dict[str, Any]], key: str, fid: int,
            frame, lineno: int | None) -> None:
    pending = bucket.pop(fid, None)
    if pending is None:
        return
    pending["after"] = _target_value(frame, pending)
    pending["changed"] = not _same(pending["before"], pending["after"])
    pending["after_lineno"] = lineno
    _CURRENT[key].append(pending)


def _finalize_pending(frame, event: str, lineno: int | None) -> None:
    """Close A / U records at the right moment for this frame."""
    assert _CURRENT is not None
    fid = id(frame)
    _record(_CURRENT["a_pending"], "a_executions", fid, frame, lineno)

    u_pending = _CURRENT["u_pending"].get(fid)
    if u_pending is not None and u_pending.get("block"):
        if event == "line" and lineno is not None:
            # A multi-line statement can emit more than one line event at its
            # opener, so do not treat a repeat of first_line as the end.
            if u_pending["first_line"] <= lineno <= u_pending["last_line"]:
                return  # still executing the block
        elif event == "exception" and lineno is not None:
            if u_pending["first_line"] <= lineno <= u_pending["last_line"]:
                return  # may be caught inside the block; wait for return
    _record(_CURRENT["u_pending"], "u_executions", fid, frame, lineno)


def _trace(frame, event, arg):
    assert _CURRENT is not None
    key, watched = _frame_info(frame)
    if not watched:
        return None
    fid = id(frame)
    lineno = frame.f_lineno if event in ("line", "exception") else None

    if event == "line":
        _EXC.pop(fid, None)
    _finalize_pending(frame, event, lineno)

    if event == "line":
        target = _CONFIG.get("target")
        if (target is not None
                and key == target["_abs_file"]
                and frame.f_lineno == target["line"]):
            _CURRENT["a_pending"][fid] = {
                "seq": len(_CURRENT["a_executions"]) + 1,
                "function": frame.f_code.co_name,
                "file": target["file"],
                "line": frame.f_lineno,
                "var": target["var"],
                "key_kind": target.get("key_kind", "name"),
                "key_obj": target.get("key_obj", ""),
                "key_index": target.get("key_index"),
                "before": _target_value(frame, target),
            }
        for op in _CONFIG.get("u_operations", []):
            if key == op["_abs_file"] and frame.f_lineno == op["first_line"]:
                _CURRENT["u_pending"][fid] = {
                    "seq": len(_CURRENT["u_executions"]) + 1,
                    "id": op["id"],
                    "function": frame.f_code.co_name,
                    "file": op["file"],
                    "first_line": op["first_line"],
                    "last_line": op["last_line"],
                    "block": op["first_line"] != op["last_line"],
                    "var": op["var"],
                    "key_kind": op.get("key_kind", "name"),
                    "key_obj": op.get("key_obj", ""),
                    "key_index": op.get("key_index"),
                    "before": _target_value(frame, op),
                }
        return _trace

    if event == "exception":
        _EXC[fid] = arg
        return _trace

    if event == "return":
        spec = _matches_obs(frame)
        if spec is not None:
            global _OBS_SEQ
            _OBS_SEQ += 1
            exc = _EXC.pop(fid, None)
            if exc is not None:
                value = {
                    "seq": _OBS_SEQ,
                    "function": spec["co_name"],
                    "kind": spec["kind"],
                    "outcome": "raise",
                    "type": getattr(exc[0], "__name__", str(exc[0])),
                    "message": str(exc[1])[:500],
                }
            else:
                value = {
                    "seq": _OBS_SEQ,
                    "function": spec["co_name"],
                    "kind": spec["kind"],
                    "outcome": "return",
                    "value": _obs_value(frame, spec, arg),
                }
            _CURRENT["observations"].append(value)
        return _trace
    return _trace


def pytest_configure(config) -> None:  # noqa: ANN001
    global _CONFIG
    path = os.environ.get("MACE_STORY_CONFIG")
    if not path:
        raise RuntimeError("MACE_STORY_CONFIG is required")
    _CONFIG = json.loads(Path(path).read_text(encoding="utf-8"))
    root = _CONFIG["root"]
    if _CONFIG.get("target") is not None:
        _CONFIG["target"]["_abs_file"] = _abs(
            root, _CONFIG["target"]["file"])
        _WATCHED.add(_CONFIG["target"]["_abs_file"])
    for op in _CONFIG.get("u_operations", []):
        op["_abs_file"] = _abs(root, op["file"])
        _WATCHED.add(op["_abs_file"])
    for spec in _CONFIG.get("observations", []):
        spec["_abs_file"] = _abs(root, spec["file"])
        _WATCHED.add(spec["_abs_file"])
    _CODE_INFO.clear()


def pytest_runtest_call(item) -> None:  # noqa: ANN001
    # Fixtures are resolved by the time this hook runs.
    if _CURRENT is None:
        return
    if getattr(item, "callspec", None) is not None:
        _CURRENT["param_id"] = item.callspec.id
        _CURRENT["params"] = {
            key: _safe(value) for key, value in item.callspec.params.items()
        }
    _CURRENT["funcargs"] = {
        key: _safe(value) for key, value in item.funcargs.items()
        if key not in ("self", "request")
    }


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):  # noqa: ANN001
    global _CURRENT, _OBS_SEQ
    _CURRENT = {
        "nodeid": item.nodeid,
        "location": {
            "file": item.location[0],
            "line": item.location[1] + 1,
            "name": item.location[2],
        },
        "param_id": None,
        "params": {},
        "funcargs": {},
        "a_pending": {},
        "u_pending": {},
        "a_executions": [],
        "u_executions": [],
        "observations": [],
        "setup_call_teardown": True,
    }
    _OBS_SEQ = 0
    _EXC.clear()
    old = sys.gettrace()
    sys.settrace(_trace)
    try:
        yield
    finally:
        sys.settrace(old)
        _TESTS[item.nodeid] = _CURRENT
        _CURRENT = None


def pytest_runtest_logreport(report) -> None:  # noqa: ANN001
    if report.when not in ("setup", "call", "teardown"):
        return
    row = _REPORTS.setdefault(
        report.nodeid,
        {"nodeid": report.nodeid, "phases": {}, "outcome": None},
    )
    row["phases"][report.when] = {
        "outcome": report.outcome,
        "longrepr": str(report.longrepr)[:2000] if report.longrepr else None,
    }
    if report.when == "call":
        row["outcome"] = report.outcome
    elif row["outcome"] is None and report.outcome == "failed":
        row["outcome"] = "failed"


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001
    out = os.environ.get("MACE_STORY_OUT")
    if not out:
        return
    payload = {
        "task_id": _CONFIG.get("task_id"),
        "variant": _CONFIG.get("variant"),
        "exitstatus": int(exitstatus),
        "tests": {
            nodeid: {
                **_TESTS.get(nodeid, {}),
                "reports": _REPORTS.get(nodeid, {}),
            }
            for nodeid in sorted(set(_TESTS) | set(_REPORTS))
        },
    }
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
