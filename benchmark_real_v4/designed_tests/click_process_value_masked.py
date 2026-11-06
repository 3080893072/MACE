"""DESIGNED test set for click Parameter.process_value.

These tests call the public Click object API with an explicit callback whose
return value does not depend on the type-cast input.  They pass with and
without the target statement at src/click/core.py:2482, because the callback
assignment that follows it supplies the returned value.

Marked DESIGNED: these are not upstream click tests.
"""
from __future__ import annotations

import click


def _option(callback):
    return click.Option(["--num"], type=click.INT, callback=callback)


def _context(option):
    return click.Context(click.Command("probe", params=[option]))


def test_masked_constant_callback():
    """The callback replaces any type-cast value with a constant."""
    option = _option(lambda ctx, param, value: "CONST")
    assert option.process_value(_context(option), "42") == "CONST"


def test_masked_callback_uses_param_name():
    """The callback returns a value derived from the parameter, not the input."""
    def callback(ctx, param, value):
        return param.name.upper()

    option = _option(callback)
    assert option.process_value(_context(option), "7") == "NUM"


def test_masked_second_constant():
    """A second legal input on the same masking path."""
    option = _option(lambda ctx, param, value: ("fixed", 1))
    assert option.process_value(_context(option), "123") == ("fixed", 1)
