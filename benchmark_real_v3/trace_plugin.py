"""Pytest plugin recording per-test source-line execution for v3.

Environment:
  V3_TRACE_ROOT   project copy root
  V3_TRACE_FILES  newline-separated project-relative source files
  V3_TRACE_OUT    output JSON path
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path
from typing import Dict, Set

import pytest

_FILES: Dict[str, str] = {}
_HITS: Dict[str, Dict[str, Set[int]]] = {}
_REPORTS: Dict[str, Dict] = {}


def pytest_configure(config) -> None:  # noqa: ANN001
    root = os.environ.get("V3_TRACE_ROOT", "").strip()
    raw = os.environ.get("V3_TRACE_FILES", "")
    if not root:
        raise RuntimeError("V3_TRACE_ROOT is required")
    for rel in raw.splitlines():
        rel = rel.strip()
        if not rel:
            continue
        _FILES[os.path.abspath(Path(root) / rel)] = rel


@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):  # noqa: ANN001
    seen: Dict[str, Set[int]] = {}

    def tracer(frame, event, arg):  # noqa: ANN001
        if event == "line":
            rel = _FILES.get(os.path.abspath(frame.f_code.co_filename))
            if rel is not None:
                seen.setdefault(rel, set()).add(frame.f_lineno)
        return tracer

    old = sys.gettrace()
    sys.settrace(tracer)
    try:
        yield
    finally:
        sys.settrace(old)
    if seen:
        _HITS[item.nodeid] = {
            rel: sorted(lines) for rel, lines in seen.items()
        }


def pytest_runtest_logreport(report) -> None:  # noqa: ANN001
    if report.when not in ("setup", "call", "teardown"):
        return
    row = _REPORTS.setdefault(
        report.nodeid,
        {"nodeid": report.nodeid, "phases": {}, "outcome": None},
    )
    row["phases"][report.when] = {
        "outcome": report.outcome,
        "longrepr": str(report.longrepr) if report.longrepr else None,
    }
    if report.when == "call":
        row["outcome"] = report.outcome
    elif row["outcome"] is None and report.outcome == "failed":
        row["outcome"] = "failed"


def pytest_sessionfinish(session, exitstatus) -> None:  # noqa: ANN001
    out = os.environ.get("V3_TRACE_OUT")
    if not out:
        return
    payload = {
        "exitstatus": int(exitstatus),
        "cwd": os.getcwd(),
        "files": sorted(set(_FILES.values())),
        "hits": {
            nodeid: {rel: lines for rel, lines in sorted(files.items())}
            for nodeid, files in sorted(_HITS.items())
        },
        "reports": _REPORTS,
    }
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    Path(out).write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
