"""Pytest plugin: record whether one source line executes during T_task.

Loaded only by ``acceptance_t_task_trace.py``.  The target file and line are
passed through environment variables so the plugin itself contains no task
metadata.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

_FILE = os.path.normcase(os.path.realpath(os.environ["MACE_TRACE_FILE"]))
_LINE = int(os.environ["MACE_TRACE_LINE"])
_MARKER = Path(os.environ["MACE_TRACE_MARKER"])
_state = {"executed": False}


def _tracer(frame, event, arg):
    if (event == "line"
            and frame.f_lineno == _LINE
            and os.path.normcase(os.path.realpath(frame.f_code.co_filename))
            == _FILE):
        _state["executed"] = True
    return _tracer


def pytest_runtest_setup(item):
    sys.settrace(_tracer)


def pytest_runtest_teardown(item, nextitem):
    sys.settrace(None)


def pytest_sessionfinish(session, exitstatus):
    _MARKER.parent.mkdir(parents=True, exist_ok=True)
    _MARKER.write_text("1" if _state["executed"] else "0", encoding="utf-8")
