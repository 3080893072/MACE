"""Repository path resolution shared by the experiment scripts.

The research runs were produced on a Windows workstation with the repository
at a fixed absolute path and per-project virtual environments under
``<local-path>``.  Nothing in the algorithm depends on those
locations, so the scripts resolve them in this order:

1. an explicit environment variable,
2. a path derived from the repository itself,
3. a path under the system temporary directory.

Environment variables
---------------------
MACE_KIT
    Repository root.  Used only when a caller cannot infer it from
    ``__file__`` (it defaults to the parent of this package).
MACE_WORK
    Scratch root for probe workspaces.  Default: ``<temp>/mace``.
MACE_VENVS
    Root holding one virtual environment per benchmark project, laid out as
    ``<root>/<project-slug>``.  Default: ``<MACE_WORK>/venvs``.
MACE_PYTHON
    Interpreter used for the per-project environments when a virtual
    environment has not been created yet.  Default: the running interpreter.

The defaults reproduce the historical layout only in the sense that both are
outside the repository; the exact ``<local-path>`` prefix is not assumed.
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

__all__ = ["KIT", "work_root", "venvs_root", "venv_python", "host_python"]


def _from_env(name: str, default: Path) -> Path:
    value = os.environ.get(name)
    return Path(value).expanduser() if value else default


KIT = _from_env("MACE_KIT", Path(__file__).resolve().parents[1])


def work_root(*parts: str) -> Path:
    """Scratch directory root; ``parts`` are appended to it."""
    root = _from_env("MACE_WORK", Path(tempfile.gettempdir()) / "mace")
    return root.joinpath(*parts) if parts else root


def venvs_root() -> Path:
    """Directory holding one virtual environment per project slug."""
    return _from_env("MACE_VENVS", work_root("venvs"))


def venv_python(slug: str) -> Path:
    """Interpreter inside the per-project virtual environment.

    Returns the conventional Windows path when it exists, then the POSIX
    path; if neither exists the Windows path is returned so callers fail with
    an actionable error instead of silently running the host interpreter.
    """
    root = venvs_root() / slug
    candidates = [root / "Scripts" / "python.exe", root / "bin" / "python"]
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return candidates[0]


def host_python() -> str:
    """Interpreter used to bootstrap a missing virtual environment."""
    return os.environ.get("MACE_PYTHON", sys.executable)
