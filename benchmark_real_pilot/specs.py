"""Frozen task metadata, domains, and test-port records.

The task bodies live in ``benchmark_real_pilot/tasks/``.  Every body is an
exact excerpt of an upstream public release except for (a) the function name
``program`` where a standalone entry point is needed and (b) the
``# TARGET_A`` marker.  Upstream line numbers are recorded separately from
the local excerpt line numbers.

No metadata in this module says which operation masks A.  That information is
computed by ``run.py`` and stored in ``results/results.json``.
"""
from __future__ import annotations

TASKS = {
    "real_werkzeug_url_unparse": {
        "project": "Werkzeug",
        "version": "2.2.3",
        "license": "BSD-3-Clause",
        "upstream_path": "src/werkzeug/urls.py",
        "upstream_lines": "595-623",
        "upstream_symbol": "url_unparse",
        "local_path": "benchmark_real_pilot/tasks/werkzeug_url_unparse.py",
        "entry": "program",
        "local_target_line": 48,
        "local_operation_line": 57,
        "upstream_target_line": 605,
        "upstream_operation_line": 614,
        "target_variable": "url",
        "hypothetical_deletion": True,
        "cases": [
            {
                "id": "mask_netloc",
                "args": {"components": ("http", "example.com", "a", "q=1", "frag")},
                "role": "mask_witness",
            },
            {
                "id": "mask_absolute_path",
                "args": {"components": ("http", "", "/a", "", "")},
                "role": "ordinary",
            },
            {
                "id": "expose_path_only",
                "args": {"components": ("", "", "/a", "", "")},
                "role": "expose_witness",
            },
            {
                "id": "expose_scheme_relative",
                "args": {"components": ("http", "", "a", "", "")},
                "role": "ordinary",
            },
            {
                "id": "expose_empty",
                "args": {"components": ("", "", "", "", "")},
                "role": "ordinary",
            },
            {
                "id": "nonexecuted_mixed_types",
                "args": {"components": ("http", b"example.com", "a", "", "")},
                "role": "non_executed",
            },
        ],
        "upstream_tests": [],
        "upstream_test_status": "not_covered",
        "upstream_test_note": (
            "A static search of the Werkzeug 2.2.3 tests tree found no call to "
            "url_unparse or URL.to_url; the function is not exercised by the "
            "released test suite."
        ),
    },
    "real_werkzeug_headerset_update": {
        "project": "Werkzeug",
        "version": "2.2.3",
        "license": "BSD-3-Clause",
        "upstream_path": "src/werkzeug/datastructures.py",
        "upstream_lines": "2261-2274",
        "upstream_symbol": "HeaderSet.update",
        "local_path": "benchmark_real_pilot/tasks/werkzeug_headerset_update.py",
        "entry": "program",
        "local_target_line": 62,
        "local_operation_line": 68,
        "upstream_target_line": 2266,
        "upstream_operation_line": 2272,
        "target_variable": "inserted_any",
        "hypothetical_deletion": True,
        "cases": [
            {
                "id": "mask_new_header",
                "args": {"headers": ["foo"], "iterable": ["bar"]},
                "role": "mask_witness",
            },
            {
                "id": "mask_duplicate_then_new",
                "args": {"headers": ["foo"], "iterable": ["foo", "bar"]},
                "role": "ordinary",
            },
            {
                "id": "expose_all_duplicates",
                "args": {"headers": ["foo"], "iterable": ["foo", "FOO"]},
                "role": "expose_witness",
            },
            {
                "id": "expose_empty",
                "args": {"headers": [], "iterable": []},
                "role": "ordinary",
            },
            {
                "id": "expose_initial_only",
                "args": {"headers": ["foo"], "iterable": []},
                "role": "ordinary",
            },
        ],
        "upstream_tests": [
            {
                "name": "test_basic_interface_add",
                "source": (
                    "def test_basic_interface_add():\n"
                    "    hs = HeaderSet()\n"
                    "    hs.add('foo')\n"
                    "    hs.add('bar')\n"
                    "    assert 'Bar' in hs\n"
                    "    assert hs.find('foo') == 0\n"
                    "    assert hs.find('BAR') == 1\n"
                    "    assert hs.find('baz') < 0\n"
                ),
                "upstream_reference": (
                    "tests/test_datastructures.py::TestHeaderSet::"
                    "test_basic_interface"
                ),
                "note": (
                    "First half of the upstream test, copied as data.  Every "
                    "add() calls update() with a header not already present, "
                    "so the target initializer is always overwritten."
                ),
            }
        ],
        "upstream_test_status": "masked",
        "upstream_test_note": (
            "The released test passes add() only with new headers.  It never "
            "calls update([]) or update() with only case-insensitive "
            "duplicates, the inputs on which the initializer is live."
        ),
    },
    "real_click_truncate_visible": {
        "project": "click",
        "version": "8.4.1",
        "license": "BSD-3-Clause",
        "upstream_path": "src/click/_textwrap.py",
        "upstream_lines": "11-35",
        "upstream_symbol": "_truncate_visible",
        "local_path": "benchmark_real_pilot/tasks/click_truncate_visible.py",
        "entry": "program",
        "local_target_line": 27,
        "local_operation_line": 36,
        "upstream_target_line": 23,
        "upstream_operation_line": 32,
        "target_variable": "cut",
        "hypothetical_deletion": True,
        "cases": [
            {
                "id": "mask_plain_long_word",
                "args": {"text": "abcdefghij", "n": 3},
                "role": "mask_witness",
            },
            {
                "id": "mask_styled_long_word",
                "args": {"text": "\x1b[31mabcdefghij\x1b[0m", "n": 5},
                "role": "ordinary",
            },
            {
                "id": "mask_short_text",
                "args": {"text": "ab", "n": 5},
                "role": "ordinary",
            },
            {
                "id": "expose_empty",
                "args": {"text": "", "n": 3},
                "role": "expose_witness",
            },
            {
                "id": "expose_ansi_only",
                "args": {"text": "\x1b[31m\x1b[0m", "n": 3},
                "role": "ordinary",
            },
            {
                "id": "nonexecuted_n_zero",
                "args": {"text": "abcdefghij", "n": 0},
                "role": "non_executed",
            },
        ],
        "upstream_tests": [
            {
                "name": "test_styled_long_word_prefix",
                "source": (
                    "def test_styled_long_word_prefix():\n"
                    "    assert program('\\x1b[31mabcdefghij\\x1b[0m', 5) "
                    "== '\\x1b[31mabcde'\n"
                ),
                "upstream_reference": (
                    "tests/test_formatting.py::test_wrap_text_visible_width"
                    "[styled-long-word-breaks-on-visible-width]"
                ),
                "note": (
                    "The upstream test calls wrap_text; this port calls the "
                    "same helper with the same styled long-word input and the "
                    "prefix that the upstream test requires."
                ),
            }
        ],
        "upstream_test_status": "masked",
        "upstream_test_note": (
            "The released test covers long words containing visible "
            "characters.  It does not cover an empty string or an ANSI-only "
            "chunk, where the initializer is live."
        ),
    },
}
