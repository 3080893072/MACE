"""Frozen protocol-v2 configuration for the three existing real tasks.

This file changes test *organization*, not task construction or masking
semantics.  The target statement A, the masking operation B, the extracted
task bodies, the input domains, and all M1-M6 history remain unchanged.

Two test scopes are deliberately separate:

* ``T_task``: a small frozen set of original upstream tests selected from
  source association and P+ coverage.  Daily benchmark runs use only this set.
* ``T_project``: the project's applicable original suite.  It is run once when
  a task is created, cached, and reused for qualification.

Selection of ``T_task`` must never consult P- outcomes.  The selection code in
``selection.py`` has no P- input parameter; the only P+ input is the trace of
tests that hit the target line in the unmodified project.
"""
from __future__ import annotations

PROTOCOL_VERSION = "2"

# P+ coverage is loaded from the existing full-suite trace.  P- is deliberately
# absent from every selection input.
COVERAGE_SOURCE = (
    "benchmark_real_pilot/qualification/out/upstream_runs.json"
)

TASKS = {
    "real_click_truncate_visible": {
        "task_id": "real_click_truncate_visible",
        "project_id": "click-8.4.1",
        "project": "click",
        "version": "8.4.1",
        "package": "click",
        "source_file": "src/click/_textwrap.py",
        "source_symbol": "_truncate_visible",
        "target_upstream_line": 23,
        "target_expected": "cut = 0",
        "trace_label": "truncate_visible",
        "test_python": "D:/Anaconda3/python.exe",
        "test_pytest": "7.4.0",
        "allowed_test_files": ["tests/test_formatting.py"],
        "selection_reason": (
            "The only P+ trace hit for _truncate_visible is the styled "
            "long-word parameter of test_wrap_text_visible_width.  It is "
            "retained as the complete source-associated T_task; no unrelated "
            "formatting tests were added merely to reach five tests."
        ),
        "test_scope_note": (
            "One original upstream test.  It calls wrap_text and reaches "
            "_truncate_visible through _handle_long_word; it is not a direct "
            "call to the private helper.  No other original test traced to A."
        ),
        "project_suite": {
            "label": "click default released suite",
            "tests": ["tests"],
            "extra_args": [],
            "filter_note": (
                "No external -m filter.  click's own pytest.ini addopts "
                "deselects the stress marker (30000 deselected)."
            ),
            "cached_plus_key": "click-8.4.1:plus",
            "cached_minus_key": "click-8.4.1:minus_truncate_visible",
            "deselected_by_project": 30000,
            "deselected_by_protocol": 0,
            "full_unfiltered_suite_note": (
                "The declared T_project is click's released default suite; "
                "the 30000 stress tests are deselected by click's own config."
            ),
        },
    },
    "real_werkzeug_headerset_update": {
        "task_id": "real_werkzeug_headerset_update",
        "project_id": "werkzeug-2.2.3",
        "project": "Werkzeug",
        "version": "2.2.3",
        "package": "werkzeug",
        "source_file": "src/werkzeug/datastructures.py",
        "source_symbol": "HeaderSet.update",
        "target_upstream_line": 2266,
        "target_expected": "inserted_any = False",
        "trace_label": "headerset_update",
        "test_python": (
            "<local-path>"
        ),
        "test_pytest": "7.2.0",
        "allowed_test_files": [
            "tests/test_datastructures.py",
            "tests/test_http.py",
            "tests/test_wrappers.py",
        ],
        "selection_reason": (
            "All three P+ trace hits are original tests that reach "
            "HeaderSet.update through public HeaderSet or response-header "
            "operations.  They are the complete source-associated set; no "
            "other original test traced to A."
        ),
        "test_scope_note": (
            "Three original upstream tests: one direct HeaderSet test, one "
            "http.parse_set_header test that calls add(), and one response "
            "descriptor test that calls Vary/Allow add()."
        ),
        "project_suite": {
            "label": "Werkzeug applicable released suite",
            "tests": ["tests"],
            "extra_args": ["-m", "not dev_server"],
            "filter_note": (
                "24 dev_server tests are deselected because they require a "
                "working local dev-server connection on this Windows host."
            ),
            "cached_plus_key": "werkzeug-2.2.3:plus",
            "cached_minus_key": "werkzeug-2.2.3:minus_headerset_update",
            "deselected_by_project": 0,
            "deselected_by_protocol": 24,
            "full_unfiltered_suite_note": (
                "The unfiltered Werkzeug suite is not used: it has 15 failed "
                "and 8 errors from ConnectionRefusedError in dev-server tests. "
                "No claim is made that the whole unfiltered suite passes."
            ),
        },
    },
    "real_werkzeug_url_unparse": {
        "task_id": "real_werkzeug_url_unparse",
        "project_id": "werkzeug-2.2.3",
        "project": "Werkzeug",
        "version": "2.2.3",
        "package": "werkzeug",
        "source_file": "src/werkzeug/urls.py",
        "source_symbol": "url_unparse",
        "target_upstream_line": 605,
        "target_expected": 'url = s("")',
        "trace_label": "url_unparse",
        "test_python": (
            "<local-path>"
        ),
        "test_pytest": "7.2.0",
        "allowed_test_files": ["tests/test_urls.py"],
        "selection_reason": (
            "All P+ trace hits in tests/test_urls.py are retained.  These are "
            "the original tests for the public URL conversion surface that "
            "calls url_unparse (iri_to_uri, uri_to_iri, url_fix, url_join).  "
            "The other 201 P+ hit tests are incidental consumers in unrelated "
            "modules and are not part of the direct source-associated set."
        ),
        "test_scope_note": (
            "Eighteen original upstream tests from tests/test_urls.py.  They "
            "call public URL helpers that reach url_unparse indirectly; no "
            "original test imports url_unparse by name."
        ),
        "project_suite": {
            "label": "Werkzeug applicable released suite",
            "tests": ["tests"],
            "extra_args": ["-m", "not dev_server"],
            "filter_note": (
                "24 dev_server tests are deselected because they require a "
                "working local dev-server connection on this Windows host."
            ),
            "cached_plus_key": "werkzeug-2.2.3:plus",
            "cached_minus_key": "werkzeug-2.2.3:minus_url_unparse",
            "deselected_by_project": 0,
            "deselected_by_protocol": 24,
            "full_unfiltered_suite_note": (
                "The unfiltered Werkzeug suite is not used: it has 15 failed "
                "and 8 errors from ConnectionRefusedError in dev-server tests. "
                "No claim is made that the whole unfiltered suite passes."
            ),
        },
    },
}

# Qualification labels are independent fields.  Their names are fixed here so
# no report can silently replace one conclusion with another.
QUALIFICATION_LABELS = (
    "TASK_TESTS_SURVIVE",
    "PROJECT_SUITE_SURVIVES",
    "PROJECT_SUITE_DETECTS",
    "PROJECT_SUITE_NOT_FULLY_RUN",
    "ENVIRONMENT_BLOCKED",
)
