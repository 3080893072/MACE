"""Exact excerpt from Werkzeug 2.2.3 ``src/werkzeug/urls.py``.

Upstream function: ``url_unparse`` (lines 595-623).
Helper excerpts: ``_make_encode_wrapper`` and ``_check_str_tuple`` from
``src/werkzeug/_internal.py`` (lines 71-89).
Only the imports needed by this excerpt were moved to the top; the target
function body and both helpers are otherwise unchanged.
"""
from __future__ import annotations

import operator
from typing import Any
from typing import Callable
from typing import Tuple


def _make_encode_wrapper(reference: Any) -> Callable[[str], Any]:
    """Create a function that will be called with a string argument. If
    the reference is bytes, values will be encoded to bytes.
    """
    if isinstance(reference, str):
        return lambda x: x

    return operator.methodcaller("encode", "latin1")


def _check_str_tuple(value: Tuple[Any, ...]) -> None:
    """Ensure tuple items are all strings or all bytes."""
    if not value:
        return

    item_type = str if isinstance(value[0], str) else bytes

    if any(not isinstance(item, item_type) for item in value):
        raise TypeError(f"Cannot mix str and bytes arguments (got {value!r})")


def program(components: Tuple[str, str, str, str, str]) -> str:
    """The reverse operation to :meth:`url_parse`.  This accepts arbitrary
    as well as :class:`URL` tuples and returns a URL as a string.

    :param components: the parsed URL as tuple which should be converted
                       into a URL string.
    """
    _check_str_tuple(components)
    scheme, netloc, path, query, fragment = components
    s = _make_encode_wrapper(scheme)
    url = s("")  # TARGET_A

    # We generally treat file:///x and file:/x the same which is also
    # what browsers seem to do.  This also allows us to ignore a schema
    # register for netloc utilization or having to differentiate between
    # empty and missing netloc.
    if netloc or (scheme and path.startswith(s("/"))):
        if path and path[:1] != s("/"):
            path = s("/") + path
        url = s("//") + (netloc or s("")) + path
    elif path:
        url += path
    if scheme:
        url = scheme + s(":") + url
    if query:
        url = url + s("?") + query
    if fragment:
        url = url + s("#") + fragment
    return url
