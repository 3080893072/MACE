"""Pytest plugin: per-test line hits and outcomes, written as JSON.

This plugin is loaded with ``-p realbench_trace_plugin``.  It does not change
test collection or assertions.  ``sys.settrace`` is installed only around the
test call, so ordinary pytest and library behavior is otherwise unchanged.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Tuple

import pytest

_TARGETS: List[Tuple[str, int, str]] = []
_HITS: Dict[str, Dict[str, int]] = {}
_REPORTS: Dict[str, Dict[str, Any]] = {}


def _load_targets() -> None:
    raw = os.environ.get("REALBENCH_TRACE_TARGETS", "")
    for entry in raw.split(";"):
        if not entry.strip():
            continue
        label, line, path = entry.split("|", 2)
        _TARGETS.append((label, int(line), os.path.abspath(path)))


def pytest_configure(config) -> None:  # noqa: ANN001 - pytest API
    _load_targets()


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):  # noqa: ANN001 - pytest API
    hits = {label: 0 for label, _, _ in _TARGETS}
    targets = tuple(_TARGETS)

    def tracer(frame, event, arg):  # noqa: ANN001 - trace API
        if event == "line":
            filename = os.path.abspath(frame.f_code.co_filename)
            for label, line, path in targets:
                if filename == path and frame.f_lineno == line:
                    hits[label] += 1
        return tracer

    old_trace = sys.gettrace()
    sys.settrace(tracer)
    try:
        yield
    finally:
        sys.settrace(old_trace)

    nonzero = {label: count for label, count in hits.items() if count}
    if nonzero:
        _HITS[item.nodeid] = nonzero


def pytest_runtest_logreport(report) -> None:  # noqa: ANN001 - pytest API
    if report.when not in ("setup", "call", "teardown"):
        return
    record = _REPORTS.setdefault(
        report.nodeid,
        {"nodeid": report.nodeid, "phases": {}, "outcome": None},
    )
    record["phases"][report.when] = {
        "outcome": report.outcome,
        "longrepr": str(report.longrepr) if report.longrepr else None,
    }
    if report.when == "call":
        record["outcome"] = report.outcome
    elif record["outcome"] is None and report.outcome == "failed":
        record["outcome"] = "failed"
    elif record["outcome"] is None and report.when == "teardown":
        record["outcome"] = report.outcome


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001 - pytest API
    out = os.environ.get("REALBENCH_TRACE_OUT")
    if not out:
        return
    modules = {}
    for name in ("click", "werkzeug"):
        module = sys.modules.get(name)
        if module is not None:
            modules[name] = getattr(module, "__file__", None)
    payload = {
        "exitstatus": int(exitstatus),
        "cwd": os.getcwd(),
        "sys_path": list(sys.path),
        "modules": modules,
        "targets": [
            {"label": label, "line": line, "path": path}
            for label, line, path in _TARGETS
        ],
        "hits": _HITS,
        "reports": _REPORTS,
    }
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
