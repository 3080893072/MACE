"""Exact excerpt from click 8.4.1 ``src/click/_textwrap.py``.

Upstream function: ``_truncate_visible`` (lines 11-35).
Only the module-level ANSI regex is copied with it.  The function name is
changed to ``program`` for the harness; the body is unchanged.
"""
from __future__ import annotations

import re


_ansi_re = re.compile(r"\033\[[;?0-9]*[a-zA-Z]")


def program(text: str, n: int) -> str:
    """Return the longest prefix of ``text`` containing at most ``n`` visible
    characters.

    ANSI escape sequences inside the prefix are kept intact and do not count
    toward the visible width. A cut is never placed inside an escape sequence.
    """
    if n <= 0:
        return ""

    visible = 0
    i = 0
    cut = 0  # TARGET_A
    end = len(text)
    while i < end:
        m = _ansi_re.match(text, i)
        if m is not None:
            i = m.end()
            continue
        visible += 1
        i += 1
        cut = i
        if visible >= n:
            break
    return text[:cut]
