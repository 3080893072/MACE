"""Frozen project configuration for the v3 real-source benchmark pilot.

Only fixed, already-downloaded upstream source trees are used.  The three
projects here are independent of the three v2 tasks and of every candidate
that was used during the earlier development rounds.  Candidate extraction
is automatic; task qualification is evidence-based and does not consult any
MACE or Qwen score.

V3 is a DEVELOPMENT/PILOT construction round, not a held-out test set:

* v2 tasks (real_click_truncate_visible, real_werkzeug_headerset_update,
  real_werkzeug_url_unparse) are excluded by id and line.
* prior development candidates (click Choice.normalize_choice,
  Werkzeug is_resource_modified, and all round-2/round-3 candidates) are
  excluded by project/file/line.
"""
from __future__ import annotations

from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
V3 = KIT / "benchmark_real_v3"
PROJECTS_ROOT = Path("<local-path>")
WORK_ROOT = Path("<local-path>")
EVIDENCE = V3 / "evidence"
CANDIDATES = V3 / "candidates"

PY_ANACONDA = "D:/Anaconda3/python.exe"
PY_WERKZEUG = "<local-path>"

PROJECTS = {
    "click-8.4.1": {
        "project_id": "click-8.4.1",
        "project": "click",
        "version": "8.4.1",
        "package": "click",
        "root": PROJECTS_ROOT / "click-8.4.1",
        "source_dir": "src",
        "tests": ["tests"],
        "python": PY_ANACONDA,
        "pytest": "7.4.0",
        "extra_args": [],
        "suite_note": (
            "click's released default suite.  Its own pytest configuration "
            "deselects the 30000 stress tests; no protocol-level deselection."
        ),
    },
    "jinja2-3.1.3": {
        "project_id": "jinja2-3.1.3",
        "project": "Jinja2",
        "version": "3.1.3",
        "package": "jinja2",
        "root": PROJECTS_ROOT / "jinja2-3.1.3",
        "source_dir": "src",
        "tests": ["tests"],
        "python": PY_ANACONDA,
        "pytest": "7.4.0",
        "extra_args": [],
        "suite_note": (
            "Jinja2's released default suite.  No tests are deselected by "
            "this protocol."
        ),
    },
    "werkzeug-2.2.3": {
        "project_id": "werkzeug-2.2.3",
        "project": "Werkzeug",
        "version": "2.2.3",
        "package": "werkzeug",
        "root": PROJECTS_ROOT / "werkzeug-2.2.3",
        "source_dir": "src",
        "tests": ["tests"],
        "python": PY_WERKZEUG,
        "pytest": "7.2.0",
        "extra_args": ["-m", "not dev_server"],
        "suite_note": (
            "Werkzeug applicable released suite.  24 dev_server tests are "
            "protocol-deselected because they require a local dev server on "
            "this Windows host.  The unfiltered suite is not claimed to pass."
        ),
    },
}

# Candidate ids or (project, file, line) that must not be reused in v3.
EXCLUDED_TASK_IDS = {
    "real_click_truncate_visible",
    "real_werkzeug_headerset_update",
    "real_werkzeug_url_unparse",
    "click_choice_normalize_choice",
    "werkzeug_is_resource_modified",
}

EXCLUDED_LINES = {
    # v2 tasks
    ("click-8.4.1", "src/click/_textwrap.py", 23),
    ("werkzeug-2.2.3", "src/werkzeug/datastructures.py", 2266),
    ("werkzeug-2.2.3", "src/werkzeug/urls.py", 605),
    # prior development candidates
    ("click-8.4.1", "src/click/types.py", 333),
    ("werkzeug-2.2.3", "src/werkzeug/sansio/http.py", 49),
    ("click-8.4.1", "src/click/formatting.py", 90),
    ("jinja2-3.1.3", "src/jinja2/utils.py", 282),
    ("packaging-23.1", "src/packaging/version.py", 464),
    ("werkzeug-2.2.3", "src/werkzeug/_reloader.py", 148),
}

# Corrected screening budget (v3.1, declared before the corrected rerun).
#
# The first screening pass used a scanner that also attributed nested-function
# assignments to their enclosing function (852 rows, 815 distinct ids) and a
# review budget of 160 with a non-enforced targeted sub-budget of 140.  Those
# logs are retained as superseded evidence.  The corrected scanner removes the
# double attribution (799 distinct candidates), and this pass reviews every
# distinct eligible candidate, so selection cannot depend on P- outcomes.
BUDGET = {
    "max_candidates_reviewed": 403,
    "max_targeted_minus_runs": 403,
    "max_full_suite_minus_runs": 60,
    "max_witness_candidates": 20,
}
