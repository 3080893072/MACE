"""DESIGNED test set for click's ``_unpack_args`` deque conversion.

The conversion at src/click/parser.py:63 turns the incoming argument sequence
into a deque so that wildcard (``nargs=-1``) handling can pop from either end.
When the argument specification is a pure wildcard, nothing is fetched from
the deque: the loop only records the wildcard position, then fills it with
``tuple(args)`` and clears ``args``.  These tests exercise that public path;
they pass with and without the conversion because the wildcard fill and the
subsequent clear produce the same result either way.

Marked DESIGNED: these are not upstream click tests.
"""
from __future__ import annotations

import click
from click.testing import CliRunner


def _variadic_cli():
    @click.command()
    @click.argument("files", nargs=-1)
    def cli(files):
        click.echo(",".join(files))

    return cli


def test_variadic_two_values():
    result = CliRunner().invoke(_variadic_cli(), ["alpha", "beta"])
    assert result.exit_code == 0
    assert result.output.strip() == "alpha,beta"


def test_variadic_single_value():
    result = CliRunner().invoke(_variadic_cli(), ["one"])
    assert result.exit_code == 0
    assert result.output.strip() == "one"


def test_variadic_no_values():
    result = CliRunner().invoke(_variadic_cli(), [])
    assert result.exit_code == 0
    assert result.output.strip() == ""
