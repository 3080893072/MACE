# Extraction check

The target function bodies were compared by Python AST, ignoring line numbers,
function names, and source comments.  The command reads both files as data; it
does not import the upstream packages.

Comparison result:

```text
url_unparse: upstream L595 local L38 body_equal=True
update:      upstream L2261 local L57 body_equal=True
_truncate_visible: upstream L11 local L15 body_equal=True
```

The local body for `url_unparse` includes the `# TARGET_A` comment on the
initializer and uses the name `program`; comments and the function name are
not part of the AST body comparison.  `HeaderSet.update` and
`_truncate_visible` likewise match the released bodies.

Helper provenance:

- `_make_encode_wrapper` and `_check_str_tuple`: Werkzeug `_internal.py`
  lines 71-89, copied unchanged.
- `_ansi_re`: click `_textwrap.py` line 8, copied unchanged.
- `HeaderSet` support methods: copied from `datastructures.py` lines
  2218-2366; `to_header`/`http` omitted because unused.
