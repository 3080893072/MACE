"""DESIGNED test set for the bool-flag UNSET branch in click Option.

The original click suite never calls ``Option.process_value`` with ``UNSET``
on a boolean flag, so no upstream test executes the target statement.  These
tests do, through the public Click object API, and use a callback whose return
value does not depend on the value supplied to it.  They pass with and without
the target statement at src/click/core.py:3428, because the callback
assignment that follows supplies the returned value in both variants.

Marked DESIGNED: these are not upstream click tests.
"""
from __future__ import annotations

import click


def _option(callback):
    return click.Option(["--flag/--no-flag"], is_flag=True, callback=callback)


def _context(option):
    return click.Context(click.Command("probe", params=[option]))


def test_unset_constant_callback():
    option = _option(lambda ctx, param, value: "CONST")
    assert option.process_value(_context(option), click.core.UNSET) == "CONST"


def test_unset_callback_uses_param_name():
    def callback(ctx, param, value):
        return param.name.upper()

    option = _option(callback)
    assert option.process_value(_context(option), click.core.UNSET) == "FLAG"


def test_unset_second_constant():
    option = _option(lambda ctx, param, value: ("fixed", 1))
    assert option.process_value(_context(option), click.core.UNSET) == ("fixed", 1)
