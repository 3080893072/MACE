"""DESIGNED test set for pyparsing White's max/exact priority.

The original pyparsing suite never constructs ``White`` with both ``max`` and
``exact`` set, so no upstream test executes the target statement at
pyparsing/core.py:3371.  These tests do, through the public ``White``
constructor, and only use the masked configuration where ``exact`` overrides
``max``: the assignment at 3371 is overwritten by the assignment at 3376, so
the final attributes are the same with and without 3371.

Marked DESIGNED: these are not upstream pyparsing tests.
"""
from __future__ import annotations

from pyparsing import White


def test_exact_overrides_max():
    ws = White(max=3, exact=2)
    assert ws.maxLen == 2
    assert ws.minLen == 2


def test_exact_overrides_larger_max():
    ws = White(min=1, max=5, exact=3)
    assert ws.maxLen == 3
    assert ws.minLen == 3


def test_exact_overrides_max_with_custom_whitespace():
    ws = White(" ", max=4, exact=1)
    assert ws.maxLen == 1
    assert ws.minLen == 1
