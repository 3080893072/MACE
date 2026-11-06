# Real-project case audit (CPU, no model calls)

* Frozen M1-M6 through commit `94912c12466054dcfc809e3bf45224137501ad9b` (manifest commit `7b3d2f5`).
* Audit git HEAD: `7b3d2f5df6b2a787363bac5004eeb25003051d14`; tracked tree dirty: **True** (this audit adds post-freeze files).
* Direct Qwen and Full MACE are **not run**: this phase forbids new model calls and there are no stored runs for these programs.
* Every guard check is `BOUNDED` on the declared finite domain; `PROVEN` is never emitted.

## Per-method totals

| method | cases | measured | derived | exact | sound | complete | UNKNOWN | tokens | wall s |
|---|---|---|---|---|---|---|---|---|---|
| Direct Qwen | 10 | 0 | - | - | - | - | - | not run | not run |
| Full MACE | 10 | 0 | - | - | - | - | - | not run | not run |
| Pure Symbolic | 10 | 10 | 5 | 2 | 2 | 2 | 5 | 0 | 0.489 |
| Symbolic + summaries | 10 | 10 | 5 | 2 | 2 | 2 | 5 | 0 | 0.482 |
| Human reference (not a system score) | 10 | 10 | - | 10 | 10 | 10 | 0 | 0 | 1.053 |
| Induction (generic pool, diagnostic) | 10 | 10 | 10 | 1 | 6 | 2 | 0 | 0 | 3.637 |
| Induction (full pool, diagnostic) | 10 | 10 | 10 | 1 | 5 | 2 | 0 | 0 | 3.548 |

* Symbolic + summaries is identical to Pure Symbolic on these ten cases: none has a user-defined helper with a declared signature that the summary builder could use. The blockers are builtins, recursion, control-flow divergence, and one `while` loop.
* Direct Qwen and Full MACE are not run, so their rows are `not_run`, never zero-accuracy results.

## Per-case results

| case | domain | direct | full MACE | human | pure | symbolic | induct generic | induct full |
|---|---|---|---|---|---|---|---|---|
| cpython_leapdays | 55 | not run | not run | `(y1 % 4 != 0) or (y1 % 100 == 0 and y1 % 400 != 0)` BOUNDED u=0 i=0 | `(y2 - 1) // 4 - (y1 - 1) // 4 - ((y2 - 1) // 100 - (y1 - 1) // 100) + ` BOUNDED u=0 i=0 | `(y2 - 1) // 4 - (y1 - 1) // 4 - ((y2 - 1) // 100 - (y1 - 1) // 100) + ` BOUNDED u=0 i=0 | `(y1 % 4 != 0) or (y1 == 100) or ((y1 != y2) and (y1 >= 100) and (y2 >=` REFUTED u=1 i=3 | `(y1 % 4 != 0) or (y1 == 100) or ((y1 != y2) and (y1 >= 100) and (y2 >=` REFUTED u=1 i=3 |
| babel_cldr_modulo | 95 | not run | not run | `a >= 0 or a % b == 0 or 2 * ((-a) % abs(b)) == abs(b)` BOUNDED u=0 i=0 | `not a < 0 or (-1 * (-1 * a % (-1 * b)) == -1 * (a % (-1 * b)) and 1 an` INVALID u=0 i=0 | `not a < 0 or (-1 * (-1 * a % (-1 * b)) == -1 * (a % (-1 * b)) and 1 an` INVALID u=0 i=0 | `(a >= 0) or (b % 2 == 0) or (b <= 1)` REFUTED u=0 i=4 | `(a >= 0) or (b % 2 == 0) or (b <= 1)` REFUTED u=0 i=4 |
| fpdf2_int32 | 11 | not run | not run | `0 <= n and n < 4294967296` BOUNDED u=0 i=0 | `(n & 4294967295 ^ 2147483648) - 2147483648 == (n ^ 2147483648) - 21474` INVALID u=0 i=0 | `(n & 4294967295 ^ 2147483648) - 2147483648 == (n ^ 2147483648) - 21474` INVALID u=0 i=0 | `(n == 0) or (n == 1)` REFUTED u=0 i=3 | `(n == 0) or (n == 1)` REFUTED u=0 i=3 |
| fonttools_flagbest_xsame | 70 | not run | not run | `x != 0` BOUNDED u=0 i=0 | `not onCurve and (not y == 0) and (not y > 0) and (-255 <= y <= 255) an` INVALID u=0 i=0 | `not onCurve and (not y == 0) and (not y > 0) and (-255 <= y <= 255) an` INVALID u=0 i=0 | `x != 0` BOUNDED u=0 i=0 | `x != 0` BOUNDED u=0 i=0 |
| numba_adjust_indices | 196 | not run | not run | `end >= 0 or end + length <= 0` BOUNDED u=0 i=0 | UNKNOWN (A changes control flow: path conditions differ) | UNKNOWN (A changes control flow: path conditions differ) | `(end >= 0) or (length <= 1) or (start == end) or ((end % 2 != 1) and (` REFUTED u=5 i=8 | `(end >= 0) or (length <= 1) or (start == end) or ((end % 2 != 1) and (` REFUTED u=5 i=8 |
| mpl_norm_angle | 17 | not run | not run | `(a + 360) % 360 <= 180` BOUNDED u=0 i=0 | `not (a + 360) % 360 > 180 or (360 + a) % 360 - 360 == (360 + a) % 360` BOUNDED u=0 i=0 | `not (a + 360) % 360 > 180 or (360 + a) % 360 - 360 == (360 + a) % 360` BOUNDED u=0 i=0 | `a % 2 == 0` REFUTED u=0 i=4 | `a % 2 == 0` REFUTED u=0 i=4 |
| scipy_range_prod_mid | 60 | not run | not run | `lo + k >= hi or k <= 1 or ((hi + lo) // 2 - hi) % k == 0` BOUNDED u=0 i=0 | UNKNOWN (no semantic summary for helper 'program') | UNKNOWN (no semantic summary for helper 'program') | `(hi == 2) or (k != 2) or (lo > 1) or ((hi % 2 != 0) and (lo % 2 != 0))` REFUTED u=3 i=3 | `(hi == 2) or (k != 2) or (lo > 1) or ((hi % 2 != 0) and (lo % 2 != 0))` REFUTED u=3 i=3 |
| condaindex_make_seconds | 7 | not run | not run | `timestamp <= 253402300799` BOUNDED u=0 i=0 | UNKNOWN (no semantic summary for helper 'int') | UNKNOWN (no semantic summary for helper 'int') | `(timestamp % 2 == 1) or (timestamp <= 1)` REFUTED u=1 i=0 | `(timestamp % 2 == 1) or (timestamp <= 1)` REFUTED u=1 i=0 |
| cpython_median_low | 36 | not run | not run | `(len(data) == 2 and data[0] == min(data)) or (len(data) == 3 and (coun` BOUNDED u=0 i=0 | UNKNOWN (A changes control flow: path conditions differ) | UNKNOWN (A changes control flow: path conditions differ) | `False` REFUTED u=0 i=23 | `((data == sorted(data)) if len(data) > 0 else True) or ((distinct(data` REFUTED u=3 i=1 |
| cpython_punycode_adapt | 328 | not run | not run | `(36 * (((delta // 700) if first else (delta // 2)) + (((delta // 700) ` BOUNDED u=0 i=0 | UNKNOWN (unsupported statement While at line 8) | UNKNOWN (unsupported statement While at line 8) | `(delta <= numchars) or (first)` REFUTED u=0 i=13 | `(delta <= numchars) or (first)` REFUTED u=0 i=13 |

Induction necessary direction: 0/10 exact (full pool). The necessary direction overfits, as in M6.


## Source and cost

| case | source | target | pure s | symbolic s | induction s | witnesses | pool |
|---|---|---|---|---|---|---|---|
| cpython_leapdays | Lib/calendar.py::leapdays | `y1 -= 1` | 0.097 | 0.096 | 0.35 | 55 | 70 |
| babel_cldr_modulo | babel/plural.py::cldr_modulo | `a *= -1` | 0.095 | 0.095 | 0.30 | 95 | 38 |
| fpdf2_int32 | fpdf/encryption.py::int32 | `n = n & 0xFFFFFFFF` | 0.095 | 0.097 | 0.29 | 11 | 16 |
| fonttools_flagbest_xsame | fontTools/ttLib/tables/_g_l_y_f.py::flagBest | `flag = flag | flagXsame (inside 'if x == 0')` | 0.099 | 0.094 | 0.43 | 70 | 104 |
| numba_adjust_indices | numba/cpython/unicode.py::_adjust_indices | `end += length` | 0.004 | 0.003 | 0.48 | 196 | 66 |
| mpl_norm_angle | mpl_toolkits/mplot3d/art3d.py::_norm_angle | `a = a - 360` | 0.096 | 0.093 | 0.27 | 17 | 16 |
| scipy_range_prod_mid | scipy/special/_basic.py::_range_prod | `mid = mid - ((mid - hi) % k)` | 0.001 | 0.001 | 0.38 | 60 | 84 |
| condaindex_make_seconds | conda_index/index/__init__.py::_make_seconds | `timestamp //= 1000` | 0.001 | 0.000 | 0.29 | 7 | 16 |
| cpython_median_low | Lib/statistics.py::median_low | `data = sorted(data)` | 0.001 | 0.001 | 0.31 | 36 | 46 |
| cpython_punycode_adapt | Lib/encodings/punycode.py::adapt | `delta += delta // numchars` | 0.001 | 0.001 | 0.46 | 328 | 88 |

## Notes

* **cpython_leapdays**: The decrement matters only when it changes a floor-division boundary: y1 divisible by 4 but not 100, or divisible by 400. Verbatim. Docstring shortened; the y1<=y2 precondition is kept as a comment.
* **babel_cldr_modulo**: If a is non-negative the branch is not taken. For negative a the sign restoration hides a % |b| that is either zero or exactly half of |b|; the half case was found by exhaustive comparison and is not part of the first-guess guard. Verbatim; docstring removed.
* **fpdf2_int32**: For an unsigned 32-bit value the mask is the identity; outside that window it changes the intermediate. Verbatim; docstring kept.
* **fonttools_flagbest_xsame**: The X-same bit is only assigned when the x delta is zero; otherwise the branch is not taken. Verbatim; module constants inlined. The second 'flagXsame' assignment (x > 0 branch) is unchanged.
* **numba_adjust_indices**: A negative end is clamped to zero when the shifted value is still negative, so the add is absorbed; a non-negative end never enters the branch. Verbatim body; the @register_jitable decorator was removed (it has no runtime semantics in this extraction).
* **mpl_norm_angle**: After the first normalization the branch is entered only for the (180, 360) part of the residue class. Verbatim; docstring kept.
* **scipy_range_prod_mid**: The adjustment is unobservable when the recursive split is not entered, when k == 1, or when mid is already aligned to k. Verbatim; docstring removed. Recursive by construction.
* **condaindex_make_seconds**: Milliseconds are converted only above the 9999-12-31 cutoff; at or below it the branch is not taken. Verbatim; comment shortened.
* **cpython_median_low**: Sorting is unobservable for two points when the first is already the minimum, and for three points when the middle element is the median: either it is tied with another point, or it is neither the unique minimum nor the unique maximum. All subterms are total on length 2..3, which the non-short-circuiting guard language requires. The unreachable empty-input StatisticsError branch was removed. Domain restricted to length 2..3: the term language has no local bindings and does not short-circuit `and`, so a guard that indexes data[1] cannot be written for length 1 without a partial index. On the declared domain the extraction is semantics-preserving.
* **cpython_punycode_adapt**: human condition is an output-equivalence restatement, not a compact semantic predicate The first-guess condition (increment == 0) is sound but incomplete: at delta 10/11/16/17 with first=False the increment is nonzero yet the final saturating formula returns the same value. The exact guard has to restate that formula before and after the increment, so it is verified but not a compact semantic predicate. Verbatim; docstring removed. Domain keeps numchars >= 1.
