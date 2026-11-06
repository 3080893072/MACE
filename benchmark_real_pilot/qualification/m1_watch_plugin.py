"""Pytest plugin: per-test outcome and a watched variable's local trace.

Loaded with ``-p m1_watch_plugin``.  The configuration file named by
``M1_WATCH_CONFIG`` is JSON::

    {"out": "...", "targets": [{
        "label": "A", "file": "abs/path.py", "function": "f",
        "firstlineno": 120, "a_line": 131, "a_end": 131,
        "func_end": 150, "var": "value"}]}

The tracer is installed for the whole runtest protocol (setup, call and
teardown).  Only the watched function's frame receives a local line tracer.
For every line in that frame after the target statement (and at return) the
plugin records ``repr(var)``.  The value at a given source line can therefore
be compared between a plus tree (target present) and a minus tree (target
replaced by ``pass``): the line still exists and still executes in both.

The plugin does not modify frames, tests or assertions.  Captures are capped
per line and per test so a pathological loop cannot exhaust memory; a capped
record is marked ``truncated``.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Any, Dict

import pytest

CAP_PER_LINE = 50
CAP_PER_TEST = 5000

_CONFIG: Dict[str, Any] = {}
_WATCH: Dict[tuple, Dict[str, Any]] = {}
_RECORDS: Dict[str, Dict[str, Any]] = {}


def _load() -> None:
    path = os.environ.get("M1_WATCH_CONFIG")
    if not path:
        return
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    _CONFIG.update(raw)
    for target in raw.get("targets", []):
        key = (os.path.abspath(target["file"]), target["function"],
               int(target["firstlineno"]))
        _WATCH[key] = target


def pytest_configure(config) -> None:  # noqa: ANN001 - pytest API
    _load()


def _record(nodeid: str) -> Dict[str, Any]:
    return _RECORDS.setdefault(
        nodeid,
        {"nodeid": nodeid, "phases": {}, "outcome": None, "hits": {},
         "values_by_line": {}, "return_values": [], "truncated": False},
    )


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_protocol(item, nextitem):  # noqa: ANN001 - pytest API
    record = _record(item.nodeid)

    def make_local(watch):  # noqa: ANN001 - closure
        a_end = int(watch["a_end"])
        func_end = int(watch["func_end"])
        var = watch["var"]
        label = watch["label"]
        state = {"count": 0}

        def capture(frame, bucket):  # noqa: ANN001 - closure
            if state["count"] >= CAP_PER_TEST:
                record["truncated"] = True
                return
            value = frame.f_locals.get(var, "<missing>")
            if len(bucket) >= CAP_PER_LINE:
                record["truncated"] = True
                return
            bucket.append(repr(value)[:200])
            state["count"] += 1

        def local_trace(frame, event, arg):  # noqa: ANN001 - trace API
            if event == "line":
                line = frame.f_lineno
                if line == int(watch["a_line"]):
                    record["hits"][label] = record["hits"].get(label, 0) + 1
                elif a_end < line <= func_end:
                    bucket = record["values_by_line"].setdefault(
                        str(line), [])
                    capture(frame, bucket)
            elif event == "return":
                capture(frame, record["return_values"])
            return local_trace

        return local_trace

    def global_trace(frame, event, arg):  # noqa: ANN001 - trace API
        if event == "call":
            key = (os.path.abspath(frame.f_code.co_filename),
                   frame.f_code.co_name, frame.f_code.co_firstlineno)
            watch = _WATCH.get(key)
            if watch is not None:
                return make_local(watch)
        return None

    old_trace = sys.gettrace()
    sys.settrace(global_trace)
    try:
        yield
    finally:
        sys.settrace(old_trace)


def pytest_runtest_logreport(report) -> None:  # noqa: ANN001 - pytest API
    if report.when not in ("setup", "call", "teardown"):
        return
    record = _record(report.nodeid)
    record["phases"][report.when] = {
        "outcome": report.outcome,
        "longrepr": str(report.longrepr)[:2000] if report.longrepr else None,
    }
    if report.when == "call":
        record["outcome"] = report.outcome
    elif record["outcome"] is None and report.outcome == "failed":
        record["outcome"] = "failed"
    elif record["outcome"] is None and report.when == "teardown":
        record["outcome"] = report.outcome


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001
    out = _CONFIG.get("out") or os.environ.get("M1_WATCH_OUT")
    if not out:
        return
    payload = {
        "exitstatus": int(exitstatus),
        "cwd": os.getcwd(),
        "targets": _CONFIG.get("targets", []),
        "records": _RECORDS,
    }
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8")
