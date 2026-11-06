"""Restrict a pytest run to a frozen list of node ids.

The list is read from ``V3_SELECT_FILE`` (one node id per line).  Test files
are still passed on the command line, so unrelated modules are not collected;
this avoids OS command-line length limits.
"""
from __future__ import annotations

import os
from pathlib import Path


def pytest_configure(config) -> None:  # noqa: ANN001
    path = os.environ.get("V3_SELECT_FILE")
    if not path:
        raise RuntimeError("V3_SELECT_FILE is required")
    wanted = {
        line.strip()
        for line in Path(path).read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    config._v3_wanted_nodeids = wanted


def pytest_collection_modifyitems(config, items):  # noqa: ANN001
    wanted = getattr(config, "_v3_wanted_nodeids", set())
    selected = [item for item in items if item.nodeid in wanted]
    missing = wanted - {item.nodeid for item in items}
    if missing:
        raise RuntimeError(
            f"{len(missing)} selected tests were not collected; "
            f"first: {sorted(missing)[:3]}"
        )
    items[:] = selected
