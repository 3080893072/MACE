# Upstream test search evidence

These are static searches over the extracted PyPI sdists.  They are evidence
about what the released tests cover; they are not a substitute for executing
the upstream suite.

## Werkzeug 2.2.3, `url_unparse`

Command:

```bash
grep -rn "url_unparse\|to_url" <local-path>
```

Result: no call to `url_unparse` and no `URL.to_url()` call.  The only
`to_url` hits are custom converter methods in `tests/test_routing.py`
(lines 769, 821-822, 853-854), not the URL helper.

Status: `not_covered`.

## Werkzeug 2.2.3, `HeaderSet.update`

The released tests are in `tests/test_datastructures.py`, class
`TestHeaderSet` (line 864).  The class has one test, `test_basic_interface`
(line 867).  It calls:

```python
hs = self.storage_class()
hs.add("foo")
hs.add("bar")
```

`HeaderSet.add` calls `update((header,))`.  Both headers are absent from the
set, so `inserted_any = True` executes.  The test never calls `update([])` or
`update()` with only case-insensitive duplicates.

Status: `masked`.

## click 8.4.1, `_truncate_visible`

Command:

```bash
grep -rn "_truncate_visible" <local-path>
```

Result: the symbol appears only in `src/click/_textwrap.py` (definition at
line 11 and call at line 59).  The released test
`tests/test_formatting.py::test_wrap_text_visible_width` (line 471) covers:

- a styled initial indent,
- styled body chunks,
- a styled long word `"\x1b[31mabcdefghij\x1b[0m"` at width 5.

All covered long words contain visible characters, so `cut = i` executes.
There is no empty-string or ANSI-only long-word case.

Status: `masked`.

## Rejected-candidate spot checks

- `tests/test_routing.py` lines 91-97 and 148-152 construct
  `Rule(..., merge_slashes=False)`, so deleting `Rule.compile`'s
  `rule = self.rule` line is caught.
- `tests/test_datastructures.py` line 1042-1051 calls
  `Accept.best_match(..., default=None)` and checks the no-match fallback.
- `tests/test_routing.py` line 594 and 1246 call `Rule.empty()` both with and
  without defaults.
- `tests/test_debug.py` line 35 (`test_runtime_error`) exercises the
  non-TemplateSyntaxError branch of `rewrite_traceback_stack`.

These support the rejection reasons in `candidates.json`; no claim is made
that every rejection was confirmed by executing the upstream suite.
