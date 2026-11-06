"""Expansion round: four additional independent upstream projects.

This round is deliberately separate from benchmark_real_v3.  It never writes
into the v3 evidence, candidate, task or release directories, and the v3
frozen package is read-only here.

The upstream trees are the released sdists already present under
``<local-path>``.  Test-time dependencies are installed in an
isolated venv; the project itself is always imported from the variant's own
source tree through PYTHONPATH.
"""
from __future__ import annotations

from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
V4 = KIT / "benchmark_real_v4"
PROJECTS_ROOT = Path("<local-path>")
WORK_ROOT = Path("<local-path>")
EVIDENCE = V4 / "evidence"
CANDIDATES = V4 / "candidates"

PY_VENV = "<local-path>"

# ``scan_files`` is the exact set of source files whose lines are traced and
# whose assignments become candidates.  ``source_dir`` is the directory added
# to PYTHONPATH when the project is imported.
PROJECTS = {
    "click-8.4.1": {
        "project_id": "click-8.4.1",
        "project": "click",
        "version": "8.4.1",
        "package": "click",
        "root": PROJECTS_ROOT / "click-8.4.1",
        "source_dir": "src",
        "scan_files": [
            "src/click/_compat.py",
            "src/click/_termui_impl.py",
            "src/click/_textwrap.py",
            "src/click/_utils.py",
            "src/click/core.py",
            "src/click/decorators.py",
            "src/click/exceptions.py",
            "src/click/formatting.py",
            "src/click/globals.py",
            "src/click/parser.py",
            "src/click/shell_completion.py",
            "src/click/termui.py",
            "src/click/testing.py",
            "src/click/types.py",
            "src/click/utils.py",
        ],
        "tests": ["tests"],
        "python": PY_VENV,
        "pytest": "7.4.0",
        "extra_args": [],
        "suite_note": (
            "click 8.4.1 released tests/ suite, 1562 passed, 94 skipped, "
            "1 xfailed in the isolated venv."
        ),
    },
    "itsdangerous-2.0.1": {
        "project_id": "itsdangerous-2.0.1",
        "project": "itsdangerous",
        "version": "2.0.1",
        "package": "itsdangerous",
        "root": PROJECTS_ROOT / "itsdangerous-2.0.1",
        "source_dir": "src",
        "scan_files": [
            "src/itsdangerous/encoding.py",
            "src/itsdangerous/jws.py",
            "src/itsdangerous/serializer.py",
            "src/itsdangerous/signer.py",
            "src/itsdangerous/timed.py",
            "src/itsdangerous/url_safe.py",
        ],
        "tests": ["tests"],
        "python": PY_VENV,
        "pytest": "7.4.0",
        "extra_args": [],
        "suite_note": (
            "itsdangerous 2.0.1 released tests/ suite, 421 tests, green in the "
            "isolated venv."
        ),
    },
    "packaging-23.1": {
        "project_id": "packaging-23.1",
        "project": "packaging",
        "version": "23.1",
        "package": "packaging",
        "root": PROJECTS_ROOT / "packaging-23.1",
        "source_dir": "src",
        "scan_files": [
            "src/packaging/_manylinux.py",
            "src/packaging/_musllinux.py",
            "src/packaging/_parser.py",
            "src/packaging/markers.py",
            "src/packaging/requirements.py",
            "src/packaging/specifiers.py",
            "src/packaging/tags.py",
            "src/packaging/utils.py",
            "src/packaging/version.py",
        ],
        "tests": ["tests"],
        "python": PY_VENV,
        "pytest": "7.4.0",
        "extra_args": [],
        "suite_note": (
            "packaging 23.1 released tests/ suite, 26430 passed and 1 skipped "
            "in the isolated venv."
        ),
    },
    "pyparsing-3.0.9": {
        "project_id": "pyparsing-3.0.9",
        "project": "pyparsing",
        "version": "3.0.9",
        "package": "pyparsing",
        "root": PROJECTS_ROOT / "pyparsing-3.0.9",
        "source_dir": ".",
        "scan_files": [
            "pyparsing/__init__.py",
            "pyparsing/core.py",
            "pyparsing/exceptions.py",
            "pyparsing/helpers.py",
            "pyparsing/results.py",
            "pyparsing/unicode.py",
            "pyparsing/util.py",
        ],
        "tests": ["tests"],
        "python": PY_VENV,
        "pytest": "7.4.0",
        "extra_args": [
            "--ignore=tests/test_diagram.py",
            "--deselect", "tests/test_unit.py::Test02_WithoutPackrat::testEmptyExpressionsAreHandledProperly",
            "--deselect", "tests/test_unit.py::Test04_WithPackrat::testEmptyExpressionsAreHandledProperly",
            "--deselect", "tests/test_unit.py::Test06_WithBoundedPackrat::testEmptyExpressionsAreHandledProperly",
            "--deselect", "tests/test_unit.py::Test08_WithUnboundedPackrat::testEmptyExpressionsAreHandledProperly",
            "--deselect", "tests/test_unit.py::Test09_WithLeftRecursionParsing::testEmptyExpressionsAreHandledProperly",
            "--deselect", "tests/test_unit.py::Test10_WithLeftRecursionParsingBoundedMemo::testEmptyExpressionsAreHandledProperly",
        ],
        "suite_note": (
            "pyparsing 3.0.9 released tests/ suite.  test_diagram.py is "
            "excluded because the optional railroad dependency is absent; the "
            "six testEmptyExpressionsAreHandledProperly variants on this "
            "Python (all import pyparsing.diagram -> jinja2) are deselected.  "
            "Applicable suite: 1470 passed."
        ),
    },
    "six-1.16.0": {
        "project_id": "six-1.16.0",
        "project": "six",
        "version": "1.16.0",
        "package": "six",
        "root": PROJECTS_ROOT / "six-1.16.0",
        "source_dir": ".",
        "scan_files": ["six.py"],
        "tests": ["test_six.py"],
        "python": PY_VENV,
        "pytest": "7.4.0",
        "extra_args": ["-k", "not test_getoutput and not dbm_ndbm"],
        "suite_note": (
            "six 1.16.0 test_six.py.  test_getoutput (interpreter repr changed "
            "on this Python) and test_move_items[dbm_ndbm] (optional dbm "
            "backend absent) are deselected as environment-dependent.  "
            "Applicable suite: 198 passed, 1 skipped."
        ),
    },
}

BUDGET = {
    "max_candidates_reviewed": 300,
    "max_targeted_minus_runs": 300,
    "max_full_suite_minus_runs": 80,
    "targeted_timeout": 180,
    "full_timeout": 900,
}
