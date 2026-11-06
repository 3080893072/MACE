"""Test-organization protocol v2 for the real-source benchmark pilot."""
from __future__ import annotations

from .config import PROTOCOL_VERSION, QUALIFICATION_LABELS, TASKS
from .selection import (
    SELECTION_BASIS,
    build_selection,
    compute_selection_hash,
    freeze_selection,
    load_plus_coverage,
    load_selection,
    select_task_tests,
)

__all__ = [
    "PROTOCOL_VERSION",
    "QUALIFICATION_LABELS",
    "TASKS",
    "SELECTION_BASIS",
    "build_selection",
    "compute_selection_hash",
    "freeze_selection",
    "load_plus_coverage",
    "load_selection",
    "select_task_tests",
]
