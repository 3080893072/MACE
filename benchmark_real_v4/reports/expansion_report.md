# v4 expansion: real masking candidates

Static candidates: 632  
Mechanisms: attribute=89, augassign=36, cross_function=38, multiline=31, name-overwrite=417, subscript=21

## Screening funnel

Rows reviewed: 479; unique candidates: 471.  

| status | count |
| --- | ---: |
| TARGETED_TEST_DETECTS_DELETION | 207 |
| STATIC_REJECT_DEAD_BEFORE_READ | 205 |
| NO_ORIGINAL_TEST_EXECUTES_A | 33 |
| TEST_SURVIVING_DELETION | 26 |

| project | NO_ORIGINAL_TEST_EXECUTES_A | STATIC_REJECT_DEAD_BEFORE_READ | TARGETED_TEST_DETECTS_DELETION | TEST_SURVIVING_DELETION |
| --- | ---: | ---: | ---: | ---: |
| click-8.4.1 | 9 | 34 | 76 | 8 |
| itsdangerous-2.0.1 | 0 | 12 | 6 | 1 |
| packaging-23.1 | 0 | 28 | 34 | 1 |
| pyparsing-3.0.9 | 14 | 127 | 87 | 16 |
| six-1.16.0 | 10 | 4 | 4 | 0 |

## Survivors

### `click-8.4.1:src/click/_compat.py:505:cross_function:stream`

- project: click 8.4.1
- file/function: `src/click/_compat.py` / `should_strip_ansi`
- A: line 505 — `stream = sys.stdin`
- mechanism: cross_function
- later operations: L495
- P+ hit tests: 3
- P- applicable suite: passed
- qualification: ASSERTION_GAP=3
- witness: -
- release candidate: no release file

### `click-8.4.1:src/click/_textwrap.py:123:augassign:cur_len`

- project: click 8.4.1
- file/function: `src/click/_textwrap.py` / `_wrap_chunks`
- A: line 123 — `cur_len -= term_len(cur_line[-1])`
- mechanism: augassign
- later operations: L148
- P+ hit tests: 6
- P- applicable suite: passed
- qualification: INCONCLUSIVE=6
- witness: -
- release candidate: no release file

### `click-8.4.1:src/click/core.py:126:attribute:ctx`

- project: click 8.4.1
- file/function: `src/click/core.py` / `augment_usage_errors`
- A: line 126 — `e.ctx = ctx`
- mechanism: attribute
- later operations: L132
- P+ hit tests: 1
- P- applicable suite: passed
- qualification: INCONCLUSIVE=1
- witness: -
- release candidate: no release file

### `click-8.4.1:src/click/core.py:3383:source`

- project: click 8.4.1
- file/function: `src/click/core.py` / `consume_value`
- A: line 3383 — `source = ParameterSource.COMMANDLINE`
- mechanism: name-overwrite
- later operations: L3406, L3417
- P+ hit tests: 7
- P- applicable suite: passed
- qualification: NO_LOCAL_EFFECT=7
- witness: -
- release candidate: no release file

### `click-8.4.1:src/click/core.py:3406:source`

- project: click 8.4.1
- file/function: `src/click/core.py` / `consume_value`
- A: line 3406 — `source = ParameterSource.COMMANDLINE`
- mechanism: name-overwrite
- later operations: L3417
- P+ hit tests: 1
- P- applicable suite: passed
- qualification: NO_LOCAL_EFFECT=1
- witness: -
- release candidate: no release file

### `click-8.4.1:src/click/formatting.py:90:indent`

- project: click 8.4.1
- file/function: `src/click/formatting.py` / `wrap_text`
- A: line 90 — `indent = None`
- mechanism: name-overwrite
- later operations: L95
- P+ hit tests: 4
- P- applicable suite: passed
- qualification: ASSERTION_GAP=1, INCONCLUSIVE=3
- witness: -
- release candidate: no release file

### `click-8.4.1:src/click/shell_completion.py:607:args`

- project: click 8.4.1
- file/function: `src/click/shell_completion.py` / `_resolve_context`
- A: line 607 — `args = ctx._protected_args + ctx.args`
- mechanism: name-overwrite
- later operations: L626, L629
- P+ hit tests: 9
- P- applicable suite: passed
- qualification: NO_LOCAL_EFFECT=9
- witness: -
- release candidate: no release file

### `click-8.4.1:src/click/termui.py:315:cross_function:color`

- project: click 8.4.1
- file/function: `src/click/termui.py` / `get_pager_file`
- A: line 315 — `color = resolve_color_default(color)`
- mechanism: cross_function
- later operations: L315
- P+ hit tests: 7
- P- applicable suite: passed
- qualification: NO_LOCAL_EFFECT=7
- witness: -
- release candidate: no release file

### `itsdangerous-2.0.1:src/itsdangerous/jws.py:77:payload`

- project: itsdangerous 2.0.1
- file/function: `src/itsdangerous/jws.py` / `load_payload`
- A: line 77 — `payload = want_bytes(payload)`
- mechanism: name-overwrite
- later operations: L111
- P+ hit tests: 59
- P- applicable suite: passed
- qualification: NO_LOCAL_EFFECT=25
- witness: -
- release candidate: no release file

### `packaging-23.1:src/packaging/version.py:476:letter`

- project: packaging 23.1
- file/function: `src/packaging/version.py` / `_parse_letter_version`
- A: line 476 — `letter = "post"`
- mechanism: name-overwrite
- later operations: L482
- P+ hit tests: 2514
- P- applicable suite: passed
- qualification: ASSERTION_GAP=25
- witness: -
- release candidate: no release file

### `pyparsing-3.0.9:pyparsing/core.py:1460:other`

- project: pyparsing 3.0.9
- file/function: `pyparsing/core.py` / `__mul__`
- A: line 1460 — `other = ((0,) + other[1:] + (None,))[:2]`
- mechanism: name-overwrite
- later operations: L1465, L1466, L1468
- P+ hit tests: 212
- P- applicable suite: passed
- qualification: MASKED_EFFECT=25
- witness: exposing=[], masked=[0, 1, 2, 3], msms=True, mmbs=True
- release candidate: no release file

### `pyparsing-3.0.9:pyparsing/core.py:1647:key`

- project: pyparsing 3.0.9
- file/function: `pyparsing/core.py` / `__getitem__`
- A: line 1647 — `key = (key,)`
- mechanism: name-overwrite
- later operations: L1650
- P+ hit tests: 6
- P- applicable suite: passed
- qualification: INCONCLUSIVE=6
- witness: -
- release candidate: no release file

### `pyparsing-3.0.9:pyparsing/core.py:2107:success`

- project: pyparsing 3.0.9
- file/function: `pyparsing/core.py` / `run_tests`
- A: line 2107 — `success = success and failureTests`
- mechanism: name-overwrite
- later operations: L2113, L2116
- P+ hit tests: 61
- P- applicable suite: passed
- qualification: ASSERTION_GAP=9, NO_LOCAL_EFFECT=16
- witness: -
- release candidate: no release file

### `pyparsing-3.0.9:pyparsing/core.py:2606:subscript:results`

- project: pyparsing 3.0.9
- file/function: `pyparsing/core.py` / `parseImpl`
- A: line 2606 — `results["original"] = match_string`
- mechanism: subscript
- later operations: L2607
- P+ hit tests: 12
- P- applicable suite: passed
- qualification: ASSERTION_GAP=12
- witness: -
- release candidate: no release file

### `pyparsing-3.0.9:pyparsing/core.py:3111:quote_char`

- project: pyparsing 3.0.9
- file/function: `pyparsing/core.py` / `__init__`
- A: line 3111 — `quote_char = quoteChar or quote_char`
- mechanism: name-overwrite
- later operations: L3114
- P+ hit tests: 49
- P- applicable suite: passed
- qualification: NO_LOCAL_EFFECT=25
- witness: -
- release candidate: no release file

### `pyparsing-3.0.9:pyparsing/core.py:3228:ret`

- project: pyparsing 3.0.9
- file/function: `pyparsing/core.py` / `parseImpl`
- A: line 3228 — `ret = ret.replace(wslit, wschar)`
- mechanism: name-overwrite
- later operations: L3232, L3236
- P+ hit tests: 12
- P- applicable suite: passed
- qualification: NO_LOCAL_EFFECT=12
- witness: -
- release candidate: no release file

### `pyparsing-3.0.9:pyparsing/core.py:3310:augassign:loc`

- project: pyparsing 3.0.9
- file/function: `pyparsing/core.py` / `parseImpl`
- A: line 3310 — `loc += 1`
- mechanism: augassign
- later operations: L3313
- P+ hit tests: 50
- P- applicable suite: passed
- qualification: INCONCLUSIVE=25
- witness: -
- release candidate: no release file

### `pyparsing-3.0.9:pyparsing/core.py:3386:augassign:loc`

- project: pyparsing 3.0.9
- file/function: `pyparsing/core.py` / `parseImpl`
- A: line 3386 — `loc += 1`
- mechanism: augassign
- later operations: L3390
- P+ hit tests: 18
- P- applicable suite: passed
- qualification: -
- witness: -
- release candidate: no release file

### `pyparsing-3.0.9:pyparsing/core.py:3603:attribute:exprs`

- project: pyparsing 3.0.9
- file/function: `pyparsing/core.py` / `__init__`
- A: line 3603 — `self.exprs: List[ParserElement]`
- mechanism: attribute
- later operations: L3608, L3610, L3619, L3622, L3624
- P+ hit tests: 956
- P- applicable suite: passed
- qualification: -
- witness: -
- release candidate: no release file

### `pyparsing-3.0.9:pyparsing/core.py:3605:exprs`

- project: pyparsing 3.0.9
- file/function: `pyparsing/core.py` / `__init__`
- A: line 3605 — `exprs = list(exprs)`
- mechanism: name-overwrite
- later operations: L3612
- P+ hit tests: 1
- P- applicable suite: passed
- qualification: ASSERTION_GAP=1
- witness: -
- release candidate: no release file

### `pyparsing-3.0.9:pyparsing/core.py:3964:maxExcLoc`

- project: pyparsing 3.0.9
- file/function: `pyparsing/core.py` / `parseImpl`
- A: line 3964 — `maxExcLoc = -1`
- mechanism: name-overwrite
- later operations: L3970, L3976, L4004
- P+ hit tests: 6
- P- applicable suite: passed
- qualification: NO_LOCAL_EFFECT=6
- witness: -
- release candidate: no release file

### `pyparsing-3.0.9:pyparsing/core.py:3970:maxExcLoc`

- project: pyparsing 3.0.9
- file/function: `pyparsing/core.py` / `parseImpl`
- A: line 3970 — `maxExcLoc = err.loc`
- mechanism: name-overwrite
- later operations: L3976, L4004
- P+ hit tests: 74
- P- applicable suite: passed
- qualification: ASSERTION_GAP=23, MASKED_EFFECT=2
- witness: -
- release candidate: no release file

### `pyparsing-3.0.9:pyparsing/core.py:5524:subscript:tokenlist`

- project: pyparsing 3.0.9
- file/function: `pyparsing/core.py` / `postParse`
- A: line 5524 — `tokenlist[ikey] = _ParseResultsWithOffset("", i)`
- mechanism: subscript
- later operations: L5527, L5544, L5546
- P+ hit tests: 12
- P- applicable suite: passed
- qualification: -
- witness: -
- release candidate: no release file

### `pyparsing-3.0.9:pyparsing/helpers.py:112:intExpr`

- project: pyparsing 3.0.9
- file/function: `pyparsing/helpers.py` / `counted_array`
- A: line 112 — `intExpr = intExpr or int_expr`
- mechanism: name-overwrite
- later operations: L123, L125
- P+ hit tests: 30
- P- applicable suite: passed
- qualification: NO_LOCAL_EFFECT=25
- witness: -
- release candidate: no release file

### `pyparsing-3.0.9:pyparsing/results.py:223:augassign:i`

- project: pyparsing 3.0.9
- file/function: `pyparsing/results.py` / `__delitem__`
- A: line 223 — `i += mylen`
- mechanism: augassign
- later operations: L224
- P+ hit tests: 6
- P- applicable suite: passed
- qualification: -
- witness: -
- release candidate: no release file

### `pyparsing-3.0.9:pyparsing/util.py:177:s`

- project: pyparsing 3.0.9
- file/function: `pyparsing/util.py` / `_escape_regex_range_chars`
- A: line 177 — `s = s.replace("\n", r"\n")`
- mechanism: name-overwrite
- later operations: L178
- P+ hit tests: 117
- P- applicable suite: passed
- qualification: NO_LOCAL_EFFECT=25
- witness: -
- release candidate: no release file

## Designed-test recoveries

These candidates did not survive the original-suite funnel, but their
target statements are real and their declared tests are explicitly
marked DESIGNED.  All five were promoted only after execution showed
the designed tests still pass under P-.

| candidate | original screening | A | designed tests | qualification | witness |
| --- | --- | --- | ---: | --- | --- |
| `click-8.4.1:src/click/core.py:2482:value` | TARGETED_TEST_DETECTS_DELETION | `value = self.type_cast_value(ctx, value)` | 3 | MASKED_EFFECT=3 | masked=[0, 2], exposing=[1, 3] |
| `click-8.4.1:src/click/core.py:3428:value` | NO_ORIGINAL_TEST_EXECUTES_A | `value = False` | 3 | MASKED_EFFECT=3 | masked=[0], exposing=[1, 2] |
| `click-8.4.1:src/click/parser.py:63:args` | TARGETED_TEST_DETECTS_DELETION | `args = deque(args)` | 3 | INCONCLUSIVE=1, MASKED_EFFECT=2 | masked=[0, 1, 2], exposing=[3] |
| `pyparsing-3.0.9:pyparsing/core.py:3371:attribute:maxLen` | NO_ORIGINAL_TEST_EXECUTES_A | `self.maxLen = max` | 3 | MASKED_EFFECT=3 | masked=[0, 1], exposing=[2] |
| `pyparsing-3.0.9:pyparsing/core.py:823:tokens` | TARGETED_TEST_DETECTS_DELETION | `tokens = self.postParse(instring, loc, tokens)` | 3 | MASKED_EFFECT=3 | masked=[0, 1, 2], exposing=[3, 4] |

## Original-suite survivors rejected on review (0 of 26 promoted)

| candidate | qualification | reason |
| --- | --- | --- |
| `click-8.4.1:src/click/_compat.py:505:cross_function:stream` | ASSERTION_GAP=3 | Targeted and applicable full suites pass under P-. |
| `click-8.4.1:src/click/_textwrap.py:123:augassign:cur_len` | INCONCLUSIVE=6 | Targeted and applicable full suites pass under P-. |
| `click-8.4.1:src/click/core.py:126:attribute:ctx` | INCONCLUSIVE=1 | Targeted and applicable full suites pass under P-. |
| `click-8.4.1:src/click/core.py:3383:source` | NO_LOCAL_EFFECT=7 | Targeted and applicable full suites pass under P-. |
| `click-8.4.1:src/click/core.py:3406:source` | NO_LOCAL_EFFECT=1 | Targeted and applicable full suites pass under P-. |
| `click-8.4.1:src/click/formatting.py:90:indent` | ASSERTION_GAP=1, INCONCLUSIVE=3 | Targeted and applicable full suites pass under P-. |
| `click-8.4.1:src/click/shell_completion.py:607:args` | NO_LOCAL_EFFECT=9 | Targeted and applicable full suites pass under P-. |
| `click-8.4.1:src/click/termui.py:315:cross_function:color` | NO_LOCAL_EFFECT=7 | Targeted and applicable full suites pass under P-. |
| `itsdangerous-2.0.1:src/itsdangerous/jws.py:77:payload` | NO_LOCAL_EFFECT=25 | Targeted and applicable full suites pass under P-. |
| `packaging-23.1:src/packaging/version.py:476:letter` | ASSERTION_GAP=25 | Targeted and applicable full suites pass under P-. |
| `pyparsing-3.0.9:pyparsing/core.py:1460:other` | MASKED_EFFECT=25 | Targeted and applicable full suites pass under P-. |
| `pyparsing-3.0.9:pyparsing/core.py:1647:key` | INCONCLUSIVE=6 | Targeted and applicable full suites pass under P-. |
| `pyparsing-3.0.9:pyparsing/core.py:2107:success` | ASSERTION_GAP=9, NO_LOCAL_EFFECT=16 | Targeted and applicable full suites pass under P-. |
| `pyparsing-3.0.9:pyparsing/core.py:2606:subscript:results` | ASSERTION_GAP=12 | Targeted and applicable full suites pass under P-. |
| `pyparsing-3.0.9:pyparsing/core.py:3111:quote_char` | NO_LOCAL_EFFECT=25 | Targeted and applicable full suites pass under P-. |
| `pyparsing-3.0.9:pyparsing/core.py:3228:ret` | NO_LOCAL_EFFECT=12 | Targeted and applicable full suites pass under P-. |
| `pyparsing-3.0.9:pyparsing/core.py:3310:augassign:loc` | INCONCLUSIVE=25 | Targeted and applicable full suites pass under P-. |
| `pyparsing-3.0.9:pyparsing/core.py:3386:augassign:loc` | - | Targeted and applicable full suites pass under P-. |
| `pyparsing-3.0.9:pyparsing/core.py:3603:attribute:exprs` | - | Targeted and applicable full suites pass under P-. |
| `pyparsing-3.0.9:pyparsing/core.py:3605:exprs` | ASSERTION_GAP=1 | Targeted and applicable full suites pass under P-. |
| `pyparsing-3.0.9:pyparsing/core.py:3964:maxExcLoc` | NO_LOCAL_EFFECT=6 | Targeted and applicable full suites pass under P-. |
| `pyparsing-3.0.9:pyparsing/core.py:3970:maxExcLoc` | ASSERTION_GAP=23, MASKED_EFFECT=2 | Targeted and applicable full suites pass under P-. |
| `pyparsing-3.0.9:pyparsing/core.py:5524:subscript:tokenlist` | - | Targeted and applicable full suites pass under P-. |
| `pyparsing-3.0.9:pyparsing/helpers.py:112:intExpr` | NO_LOCAL_EFFECT=25 | Targeted and applicable full suites pass under P-. |
| `pyparsing-3.0.9:pyparsing/results.py:223:augassign:i` | - | Targeted and applicable full suites pass under P-. |
| `pyparsing-3.0.9:pyparsing/util.py:177:s` | NO_LOCAL_EFFECT=25 | Targeted and applicable full suites pass under P-. |

## Non-survivors worth keeping

| candidate | status | reason |
| --- | --- | --- |
| `click-8.4.1:src/click/_compat.py:272:cross_function:errors` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `click-8.4.1:src/click/_termui_impl.py:213:augassign:bar` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/_termui_impl.py:272:attribute:width` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `click-8.4.1:src/click/_termui_impl.py:278:attribute:max_width` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `click-8.4.1:src/click/_textwrap.py:168:augassign:initial_indent` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/_textwrap.py:169:augassign:subsequent_indent` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/_textwrap.py:59:cross_function:cut` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/core.py:1908:attribute:invoked_subcommand` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/core.py:2355:multiline:source` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/core.py:2828:cross_function:label` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/core.py:2874:attribute:type` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/core.py:2877:attribute:type` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/core.py:2891:attribute:type` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/core.py:2916:attribute:flag_value` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/core.py:3177:subscript:extra` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `click-8.4.1:src/click/core.py:3183:attribute:resilient_parsing` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/core.py:3215:multiline:default_string` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/core.py:3428:value` | NO_ORIGINAL_TEST_EXECUTES_A | No original test executes A; the declared test set must be designed explicitly. |
| `click-8.4.1:src/click/core.py:564:augassign:_depth` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/core.py:83:multiline:message` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/decorators.py:306:cross_function:cls` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/exceptions.py:195:augassign:msg` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `click-8.4.1:src/click/formatting.py:212:cross_function:indent` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/formatting.py:239:cross_function:widths` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/parser.py:171:subscript:opts` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/parser.py:173:subscript:opts` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/parser.py:249:attribute:allow_interspersed_args` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/parser.py:254:attribute:ignore_unknown_options` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/termui.py:828:cross_function:ed` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `click-8.4.1:src/click/termui.py:834:cross_function:filename` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `click-8.4.1:src/click/testing.py:403:attribute:FORCED_WIDTH` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/testing.py:483:attribute:visible_prompt_func` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/testing.py:484:attribute:hidden_prompt_func` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/testing.py:485:attribute:_getchar` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/testing.py:487:attribute:should_strip_ansi` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/testing.py:526:attribute:__init__` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/testing.py:538:subscript:environ` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/testing.py:555:attribute:should_strip_ansi` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/testing.py:635:attribute:_original_fd` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `click-8.4.1:src/click/testing.py:67:attribute:_paused` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/types.py:1000:attribute:name` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/types.py:998:attribute:name` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `click-8.4.1:src/click/utils.py:99:augassign:total_length` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `itsdangerous-2.0.1:src/itsdangerous/serializer.py:148:is_text` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `itsdangerous-2.0.1:src/itsdangerous/serializer.py:192:kwargs` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `itsdangerous-2.0.1:src/itsdangerous/serializer.py:228:last_exception` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `itsdangerous-2.0.1:src/itsdangerous/signer.py:145:salt` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `itsdangerous-2.0.1:src/itsdangerous/signer.py:157:cross_function:digest_method` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `itsdangerous-2.0.1:src/itsdangerous/timed.py:115:ts_int` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `itsdangerous-2.0.1:src/itsdangerous/timed.py:116:ts_dt` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `itsdangerous-2.0.1:src/itsdangerous/timed.py:199:last_exception` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `itsdangerous-2.0.1:src/itsdangerous/timed.py:95:result` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `itsdangerous-2.0.1:src/itsdangerous/timed.py:96:sig_error` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `itsdangerous-2.0.1:src/itsdangerous/url_safe.py:27:decompress` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `itsdangerous-2.0.1:src/itsdangerous/url_safe.py:54:is_compressed` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/_manylinux.py:210:too_old_glibc2` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/_manylinux.py:227:min_minor` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/_parser.py:229:augassign:parsed_specifiers` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/_parser.py:284:marker` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/_parser.py:97:url` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/markers.py:138:cross_function:groups` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/markers.py:150:lhs_value` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/markers.py:151:rhs_value` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/markers.py:87:cross_function:inner` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/requirements.py:49:attribute:url` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/specifiers.py:386:multiline:prefix` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/specifiers.py:611:yielded` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/specifiers.py:796:cross_function:specifier` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/tags.py:253:abi` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/tags.py:256:abi` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/tags.py:258:abi` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/tags.py:260:abi` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/tags.py:516:version` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/tags.py:534:cross_function:interp_name` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/tags.py:541:interp` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/tags.py:543:interp` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/utils.py:115:build` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/utils.py:124:file_stem` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/utils.py:47:parsed` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/version.py:527:_pre` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/version.py:531:_pre` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/version.py:537:_post` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `packaging-23.1:src/packaging/version.py:544:_dev` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:1025:attribute:recursion_memos` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:1071:attribute:packrat_cache` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:1220:loc` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `pyparsing-3.0.9:pyparsing/core.py:1222:augassign:loc` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:1224:loc` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:1511:ret` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:1513:ret` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:1515:ret` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:1518:ret` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:1902:file_contents` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:195:enable` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:203:enable` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2078:result` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `pyparsing-3.0.9:pyparsing/core.py:2100:result` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2108:result` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2113:success` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `pyparsing-3.0.9:pyparsing/core.py:2417:errloc` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2428:augassign:errmsg` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2429:errloc` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2432:augassign:errmsg` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2433:errloc` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2450:augassign:errmsg` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2453:errloc` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2715:attribute:bodyCharsOrig` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2716:attribute:bodyChars` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2728:attribute:minLen` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2731:attribute:maxLen` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2733:attribute:maxLen` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2747:repeat` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2754:multiline:reString` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2760:repeat` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2763:multiline:reString` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2770:repeat` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2772:repeat` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `pyparsing-3.0.9:pyparsing/core.py:2775:multiline:reString` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2784:attribute:re` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2801:multiline:base` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2833:throwException` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2835:throwException` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2837:throwException` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `pyparsing-3.0.9:pyparsing/core.py:2883:attribute:reString` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2938:attribute:_re` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:2957:attribute:parseImpl` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3139:augassign:inner_pattern` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3143:augassign:inner_pattern` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3148:augassign:inner_pattern` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3162:attribute:flags` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3163:augassign:inner_pattern` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3282:attribute:minLen` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3285:attribute:maxLen` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3287:attribute:maxLen` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3368:attribute:minLen` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3371:attribute:maxLen` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `pyparsing-3.0.9:pyparsing/core.py:3373:attribute:maxLen` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3608:attribute:exprs` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `pyparsing-3.0.9:pyparsing/core.py:3622:attribute:exprs` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `pyparsing-3.0.9:pyparsing/core.py:3696:attribute:_defaultName` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3697:augassign:mayReturnEmpty` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3698:augassign:mayIndexError` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3803:attribute:mayReturnEmpty` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3809:attribute:skipWhitespace` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3833:subscript:exprs` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3867:errorStop` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3932:attribute:mayReturnEmpty` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3941:attribute:saveAsList` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3950:maxExcLoc` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3951:maxException` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3960:attribute:__traceback__` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3963:maxException` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3967:attribute:__traceback__` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3969:maxException` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:3973:multiline:maxException` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `pyparsing-3.0.9:pyparsing/core.py:3976:maxExcLoc` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `pyparsing-3.0.9:pyparsing/core.py:4087:attribute:mayReturnEmpty` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4098:attribute:saveAsList` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4099:attribute:mayReturnEmpty` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4110:maxException` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4238:attribute:mayReturnEmpty` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4248:attribute:mayReturnEmpty` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4275:multiline:required` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4468:cross_function:anchor_loc` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4474:cross_function:indent_col` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4475:cross_function:peer_detect_expr` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4479:cross_function:sub_indent` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4480:cross_function:nested_block` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4488:cross_function:block` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4490:cross_function:trailing_undent` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4493:wrapper` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4628:attribute:exact` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4630:retreat` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4631:attribute:exact` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4633:retreat` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `pyparsing-3.0.9:pyparsing/core.py:4634:attribute:exact` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `pyparsing-3.0.9:pyparsing/core.py:4636:retreat` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4637:attribute:exact` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4656:last_expr` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4797:preloc` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:4964:tokens` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `pyparsing-3.0.9:pyparsing/core.py:4967:tokens` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:5217:stacklevel` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:5325:retString` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:5328:retString` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:671:attribute:parseAction` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:747:exprsFound` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:787:pre_loc` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:811:pre_loc` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/core.py:835:exc` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `pyparsing-3.0.9:pyparsing/core.py:919:augassign:packrat_cache_stats` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/exceptions.py:146:foundstr` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/exceptions.py:151:found` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/exceptions.py:154:foundstr` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:1012:multiline:smExpr` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:255:isequal` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:256:masks` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:257:parseElementClass` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:263:symbols` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:265:symbols` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:544:multiline:content` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:554:multiline:content` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:559:multiline:content` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:593:resname` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:601:multiline:openTag` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:642:attribute:tag` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:822:lastExpr` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:836:term_name` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:849:matchExpr` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:852:multiline:matchExpr` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:856:matchExpr` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:858:multiline:matchExpr` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:869:multiline:matchExpr` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/helpers.py:873:multiline:matchExpr` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/results.py:145:attribute:_toklist` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/results.py:147:multiline:_toklist` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/results.py:168:attribute:_name` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/results.py:181:attribute:_name` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/results.py:202:subscript:_tokdict` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/results.py:203:sub` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/results.py:206:sub` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/results.py:537:cross_function:ret` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/results.py:718:attribute:_parent` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `pyparsing-3.0.9:pyparsing/util.py:229:cross_function:ret` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `six-1.16.0:six.py:115:attribute:mod` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `six-1.16.0:six.py:151:attribute:mod` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `six-1.16.0:six.py:154:new_attr` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `six-1.16.0:six.py:157:attribute:attr` | STATIC_REJECT_DEAD_BEFORE_READ | Deleting A is a dead store on the static shape. |
| `six-1.16.0:six.py:731:_locs_` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `six-1.16.0:six.py:767:data` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `six-1.16.0:six.py:772:errors` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `six-1.16.0:six.py:777:want_unicode` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `six-1.16.0:six.py:778:sep` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `six-1.16.0:six.py:781:want_unicode` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `six-1.16.0:six.py:784:end` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `six-1.16.0:six.py:787:want_unicode` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `six-1.16.0:six.py:798:newline` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
| `six-1.16.0:six.py:799:space` | NO_ORIGINAL_TEST_EXECUTES_A | No P+ test executes A. |
