"""DESIGNED test set for pyparsing's postParse / parse-action overwrite.

``ParserElement._parseNoCache`` first normalizes the token list through
``self.postParse`` (pyparsing/core.py:823).  If the same element also has a
parse action, the action runs afterwards and replaces ``tokens`` with its own
return value (lines 833/856).  An action that ignores its input therefore
hides every post-parse normalization on that element.

These tests attach constant-returning actions to Group, Combine and Suppress,
whose ``postParse`` methods all change the token list.  Each test passes with
the post-parse call removed because the action supplies the observed value.

Marked DESIGNED: these are not upstream pyparsing tests.
"""
from __future__ import annotations

import pyparsing as pp


def _constant_action():
    return lambda s, l, t: ["CONST"]


def test_group_postparse_masked_by_constant_action():
    expr = pp.Group(pp.Word(pp.alphas))
    expr.add_parse_action(_constant_action())
    assert expr.parse_string("abc").as_list() == ["CONST"]


def test_combine_postparse_masked_by_constant_action():
    expr = pp.Combine(
        pp.Word(pp.alphas, exact=2) + pp.Word(pp.alphas, exact=2)
    )
    expr.add_parse_action(_constant_action())
    assert expr.parse_string("abcd").as_list() == ["CONST"]


def test_suppress_postparse_masked_by_constant_action():
    expr = pp.Suppress(pp.Word(pp.alphas))
    expr.add_parse_action(_constant_action())
    assert expr.parse_string("abc").as_list() == ["CONST"]
