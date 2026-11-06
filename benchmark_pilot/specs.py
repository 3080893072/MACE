"""Public task metadata: domains, existing tests, observables, provenance.

Nothing in this module says which operation masks A.  The private operation
maps and the reference guards live in ``benchmark_pilot/private/controlled.py``
and are used only by the builder's design self-check.  The independent scorer
reads ``tasks.json`` / ``oracle.json`` / ``attribution.json`` and never imports
the private module.
"""
from __future__ import annotations

# ---------------------------------------------------------------------------
# Controlled tasks (synthetic; no real-maintenance claim)
# ---------------------------------------------------------------------------

_CONTROLLED_DOMAIN_01 = [
    {"mode": 0, "x": 0},
    {"mode": 0, "x": 1},
    {"mode": 0, "x": 2},
    {"mode": 1, "x": 0},
    {"mode": 1, "x": 1},
    {"mode": 1, "x": 2},
]

_CONTROLLED_DOMAIN_02 = [
    {"x": x, "c": c, "d": d}
    for x in range(1, 7)
    for c in (0, 1)
    for d in (0, 1)
]

# ctrl_03 does not use the full 2^5 Cartesian product: the legal domain is the
# union of five control regimes, frozen before any submission exists.  The
# regimes are exactly the cases named in the task spec (B alone, E alone, B&E,
# C&D, no operation).  Cross-regime combinations are outside the declared
# domain and are never used to score anybody.
_CONTROLLED_DOMAIN_03 = [
    *[{"p": 0, "q": 1, "x": x, "c": 1, "d": 1} for x in (3, 4, 5, 6)],  # B
    *[{"p": 1, "q": 0, "x": x, "c": 1, "d": 1} for x in (3, 4, 5, 6)],  # E
    *[{"p": 0, "q": 0, "x": x, "c": 1, "d": 1} for x in (3, 4, 5, 6)],  # B&E
    *[{"p": 1, "q": 1, "x": x, "c": 0, "d": 0} for x in (3, 4, 5, 6)],  # C&D
    *[{"p": 1, "q": 1, "x": x, "c": 1, "d": 1} for x in (3, 4, 5, 6)],  # none
]

_CONTROLLED_TESTS = {
    "ctrl_01": [
        {
            "name": "t_mode0_x0",
            "input": {"mode": 0, "x": 0},
            "source": "def t_mode0_x0():\n    assert program(0, 0) == 0\n",
        },
        {
            "name": "t_mode0_x1",
            "input": {"mode": 0, "x": 1},
            "source": "def t_mode0_x1():\n    assert program(0, 1) == 1\n",
        },
    ],
    "ctrl_02": [
        {
            "name": "t_rounds_x3",
            "input": {"x": 3, "c": 0, "d": 0},
            "source": "def t_rounds_x3():\n    assert program(3, 0, 0) == 0\n",
        },
        {
            "name": "t_rounds_x5",
            "input": {"x": 5, "c": 0, "d": 0},
            "source": "def t_rounds_x5():\n    assert program(5, 0, 0) == 0\n",
        },
    ],
    "ctrl_03": [
        {
            "name": "t_b_only",
            "input": {"p": 0, "q": 1, "x": 5, "c": 1, "d": 1},
            "source": "def t_b_only():\n    assert program(0, 1, 5, 1, 1) == 5\n",
        },
        {
            "name": "t_e_only",
            "input": {"p": 1, "q": 0, "x": 6, "c": 1, "d": 1},
            "source": "def t_e_only():\n    assert program(1, 0, 6, 1, 1) == 6\n",
        },
        {
            "name": "t_coop",
            "input": {"p": 1, "q": 1, "x": 4, "c": 0, "d": 0},
            "source": "def t_coop():\n    assert program(1, 1, 4, 0, 0) == 0\n",
        },
        {
            "name": "t_both_overwrite",
            "input": {"p": 0, "q": 0, "x": 5, "c": 1, "d": 1},
            "source": (
                "def t_both_overwrite():\n"
                "    assert program(0, 0, 5, 1, 1) == 5\n"
            ),
        },
    ],
}

_WHY_A = {
    "ctrl_01": (
        "A developer added v = v + 1 and now suspects it is redundant: a "
        "downstream branch may overwrite v.  The suspicion is plausible from "
        "reading the code."
    ),
    "ctrl_02": (
        "A developer added v = v + 6 and notices that two nearby roundings "
        "may make the increment invisible on some inputs.  Neither rounding "
        "looks redundant on its own, so the suspicion is that they interact."
    ),
    "ctrl_03": (
        "A developer added v = v + 4 to a function with two overwrite "
        "branches, a floor-to-3 and a floor-to-7.  Several operations look "
        "individually able to hide the increment; the developer wants to "
        "know which combinations really do."
    ),
}

CONTROLLED = {
    "ctrl_01": {
        "kind": "controlled",
        "domain_cases": _CONTROLLED_DOMAIN_01,
        "tests": _CONTROLLED_TESTS["ctrl_01"],
        "observable": {
            "kind": "return_value",
            "equality": ("same return value; a raise in either version is a "
                         "distinguishable observation"),
        },
        "why_suspected_redundant": _WHY_A["ctrl_01"],
        "provenance": {
            "source": "synthetic controlled task, written for this pilot",
            "real_maintenance": False,
            "note": ("Operation roles are not disclosed in tasks.json.  The "
                     "task is a designed instrument, not a claim about a real "
                     "commit."),
        },
    },
    "ctrl_02": {
        "kind": "controlled",
        "domain_cases": _CONTROLLED_DOMAIN_02,
        "tests": _CONTROLLED_TESTS["ctrl_02"],
        "observable": {
            "kind": "return_value",
            "equality": ("same return value; a raise in either version is a "
                         "distinguishable observation"),
        },
        "why_suspected_redundant": _WHY_A["ctrl_02"],
        "provenance": {
            "source": "synthetic controlled task, written for this pilot",
            "real_maintenance": False,
            "note": "Operation roles are not disclosed in tasks.json.",
        },
    },
    "ctrl_03": {
        "kind": "controlled",
        "domain_cases": _CONTROLLED_DOMAIN_03,
        "tests": _CONTROLLED_TESTS["ctrl_03"],
        "observable": {
            "kind": "return_value",
            "equality": ("same return value; a raise in either version is a "
                         "distinguishable observation"),
        },
        "why_suspected_redundant": _WHY_A["ctrl_03"],
        "provenance": {
            "source": "synthetic controlled task, written for this pilot",
            "real_maintenance": False,
            "note": "Operation roles are not disclosed in tasks.json.",
        },
    },
}


# ---------------------------------------------------------------------------
# Real maintenance tasks (pytest-dev/pluggy, MIT)
# ---------------------------------------------------------------------------

_PLUGGY_ENV = {
    "python": "3.11.7",
    "pytest": "7.4.0",
    "platform": "Windows 11 (win32)",
    "command": "PYTHONPATH=src python -m pytest testing -q",
}

_FORMATDEF_TEST_SOURCE = '''def test_formatdef():
    def function1():
        pass

    assert program(function1) == "function1()"

    def function2(arg1):
        pass

    assert program(function2) == "function2(arg1)"

    def function3(arg1, arg2="qwe"):
        pass

    assert program(function3) == "function3(arg1, arg2='qwe')"

    def function4(arg1, *args, **kwargs):
        pass

    assert program(function4) == "function4(arg1, *args, **kwargs)"
'''

REAL = {
    "real_formatdef": {
        "kind": "real",
        "source_plus": '''import inspect


def program(func):
    return "%s%s" % (func.__name__, str(inspect.signature(func)))  # TARGET_A
''',
        "source_minus": '''import inspect


def program(func):
    return "%s%s" % (func.__name__, inspect.signature(func))  # TARGET_A
''',
        "domain_cases": [
            {"id": "function1"},
            {"id": "function2"},
            {"id": "function3"},
            {"id": "function4"},
            {"id": "function5"},
            {"id": "function6"},
            {"id": "function7"},
            {"id": "function8"},
        ],
        "generator": "benchmark_pilot.generators:formatdef_cases",
        "tests": [
            {
                "name": "test_formatdef",
                "input": {"case_ids": ["function1", "function2",
                                       "function3", "function4"]},
                "source": _FORMATDEF_TEST_SOURCE,
                "extraction": (
                    "_formatdef was renamed to program; the test body is "
                    "otherwise verbatim from testing/test_helpers.py at the "
                    "parent commit."
                ),
            }
        ],
        "observable": {
            "kind": "return_value",
            "equality": "same return value (a string)",
        },
        "why_suspected_redundant": (
            "The commit message is exactly \"Remove redundant str() in "
            "_formatdef\".  The developer believed str() around "
            "inspect.signature(func) was unnecessary and deleted it."
        ),
        "provenance": {
            "source": "real maintenance commit",
            "real_maintenance": True,
            "repository": "https://github.com/pytest-dev/pluggy",
            "license": "MIT (LICENSE at the parent commit)",
            "commit": "0999f64a8c2ab7c7d968ab2e8c8849629a6d891c",
            "parent_commit": "6011c43de0a1ba729e950f066a44ea8932cecb05",
            "commit_date": "2020-06-26T11:28:01Z",
            "commit_message": "Remove redundant str() in _formatdef",
            "author": "Ran Benita <ran@unusedvar.com>",
            "source_path": "src/pluggy/manager.py",
            "source_line": 364,
            "diff": ("-    return \"%s%s\" % (func.__name__, "
                     "str(inspect.signature(func)))\n"
                     "+    return \"%s%s\" % (func.__name__, "
                     "inspect.signature(func))"),
            "why_developer_suspected": (
                "Developers deleted the str() call in a one-line commit whose "
                "message calls it redundant; this is the developer's own "
                "suspicion, not a reconstruction."
            ),
            "existing_tests": {
                "command": _PLUGGY_ENV["command"],
                "result_parent": "79 passed",
                "result_child": "79 passed",
                "logs": [
                    "benchmark_pilot/logs/real_formatdef_parent_pytest.log",
                    "benchmark_pilot/logs/real_formatdef_child_commit_pytest.log",
                ],
                "specific_test": "testing/test_helpers.py::test_formatdef",
            },
            "environment": _PLUGGY_ENV,
            "extraction": (
                "The two-line function is reproduced verbatim (including the "
                "outer %%s formatting) as a standalone module.  No domain "
                "restriction beyond finitely many function objects, declared "
                "below."
            ),
        },
    },
    "real_setdiff": {
        "kind": "real",
        "source_plus": '''def program(declared, provided):
    notincall = set(declared) - set(provided.keys())  # TARGET_A
    return sorted(notincall)
''',
        "source_minus": '''def program(declared, provided):
    notincall = set(declared) - provided.keys()  # TARGET_A
    return sorted(notincall)
''',
        "domain_cases": [
            {"id": "empty_empty", "declared": [], "provided": {}},
            {"id": "ab_a", "declared": ["a", "b"], "provided": {"a": 1}},
            {"id": "ab_ab", "declared": ["a", "b"],
             "provided": {"a": 1, "b": 2}},
            {"id": "a_extra", "declared": ["a"],
             "provided": {"a": 1, "b": 2}},
            {"id": "abc_none", "declared": ["a", "b", "c"], "provided": {}},
            {"id": "a_empty", "declared": ["a"], "provided": {}},
        ],
        "generator": "benchmark_pilot.generators:setdiff_cases",
        "tests": [],
        "suite_result": {
            "command": _PLUGGY_ENV["command"],
            "result_parent": "79 passed",
            "result_child": "79 passed",
            "logs": [
                "benchmark_pilot/logs/real_setdiff_parent_pytest.log",
                "benchmark_pilot/logs/real_setdiff_child_pytest.log",
            ],
            "note": ("No test in the suite calls _HookCaller.__call__ with a "
                     "missing declared argument, so the changed warning path "
                     "is not exercised at this commit."),
        },
        "observable": {
            "kind": "return_value",
            "equality": "same sorted list of missing argument names",
        },
        "why_suspected_redundant": (
            "The commit message is \"Remove redundant set() on dict keys "
            "view\", with the body \"A dict keys view supports set-like "
            "operations.\"  The developer explicitly judged the inner set() "
            "call redundant."
        ),
        "provenance": {
            "source": "real maintenance commit",
            "real_maintenance": True,
            "repository": "https://github.com/pytest-dev/pluggy",
            "license": "MIT (LICENSE at the parent commit)",
            "commit": "98f1b58bf3650e529373dbcc203fcca9619637ec",
            "parent_commit": "656bc3d04d3b452d501cfd955c53c5e724a61bc5",
            "commit_date": "2020-06-29T12:49:33Z",
            "commit_message": ("Remove redundant set() on dict keys view\n\n"
                               "A dict keys view supports set-like operations."),
            "author": "Ran Benita <ran@unusedvar.com>",
            "source_path": "src/pluggy/hooks.py",
            "source_line": 251,
            "diff": ("-            notincall = set(self.spec.argnames) - "
                     "set(kwargs.keys())\n"
                     "+            notincall = set(self.spec.argnames) - "
                     "kwargs.keys()"),
            "why_developer_suspected": (
                "The commit body states the justification directly: a keys "
                "view supports set-like operations."
            ),
            "existing_tests": {
                "command": _PLUGGY_ENV["command"],
                "result_parent": "79 passed",
                "result_child": "79 passed",
                "logs": [
                    "benchmark_pilot/logs/real_setdiff_parent_pytest.log",
                    "benchmark_pilot/logs/real_setdiff_child_pytest.log",
                ],
                "specific_test": None,
            },
            "environment": _PLUGGY_ENV,
            "extraction": (
                "The expression is extracted from _HookCaller.__call__ into a "
                "standalone function.  self.spec.argnames becomes declared and "
                "kwargs becomes provided; the deleted operation is exactly the "
                "inner set() call.  The warning/return that follows the "
                "assignment is replaced by returning the missing names, which "
                "is the only value the deleted operation can affect."
            ),
        },
    },
}

TASKS = {**CONTROLLED, **REAL}
