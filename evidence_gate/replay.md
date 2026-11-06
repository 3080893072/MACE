# Evidence-Gated Local Relations — controlled replay

Stored M5/M6 proposals are held fixed; no model call is made. `compose` and `gated` use the same deterministic composer and differ only in whether unverified relations are admitted. Every guard is re-checked on the full declared finite domain (`BOUNDED`, never `PROVEN`). The 11 fixtures were inspected in M5/M6, so this is exploratory evidence, not a held-out test.

## dev6

| method | cases | exact | sound | incomplete | invalid | unknown | unsound | tokens | wall s |
|---|---|---|---|---|---|---|---|---|---|
| Direct Qwen | 6 | 3 | 4 | 1 | 0 | 0 | 2 | 14222 | 0.0 |
| Full MACE | 6 | 1 | 2 | 1 | 2 | 0 | 2 | 80507 | 387.69 |
| Composer (gate OFF) | 6 | 1 | 3 | 2 | 0 | 3 | 0 | 0 | 0.0 |
| Evidence-gated composer | 6 | 1 | 2 | 1 | 0 | 4 | 0 | 0 | 0.0 |

## held1

| method | cases | exact | sound | incomplete | invalid | unknown | unsound | tokens | wall s |
|---|---|---|---|---|---|---|---|---|---|
| Direct Qwen | 3 | 2 | 2 | 0 | 0 | 0 | 1 | 4421 | 0.0 |
| Full MACE | 3 | 2 | 2 | 0 | 0 | 0 | 1 | 29157 | 155.94 |
| Composer (gate OFF) | 3 | 2 | 2 | 0 | 0 | 1 | 0 | 0 | 0.0 |
| Evidence-gated composer | 3 | 2 | 2 | 0 | 0 | 1 | 0 | 0 | 0.0 |

## held2

| method | cases | exact | sound | incomplete | invalid | unknown | unsound | tokens | wall s |
|---|---|---|---|---|---|---|---|---|---|
| Direct Qwen | 2 | 0 | 0 | 0 | 0 | 0 | 2 | 4983 | 0.0 |
| Full MACE | 2 | 0 | 1 | 1 | 1 | 0 | 0 | 31417 | 160.88 |
| Composer (gate OFF) | 2 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0.0 |
| Evidence-gated composer | 2 | 0 | 0 | 0 | 0 | 2 | 0 | 0 | 0.0 |

## Overall

| method | cases | exact | sound | incomplete | invalid | unknown | unsound | tokens |
|---|---|---|---|---|---|---|---|---|
| Direct Qwen | 11 | 5 | 6 | 1 | 0 | 0 | 5 | 23626 |
| Full MACE | 11 | 3 | 5 | 2 | 3 | 0 | 3 | 141081 |
| Composer (gate OFF) | 11 | 3 | 5 | 2 | 0 | 6 | 0 | 0 |
| Evidence-gated composer | 11 | 3 | 4 | 1 | 0 | 7 | 0 | 0 |

## Gate effect at fixed proposals

* gate ON gains exact guards: none
* gate ON loses exact guards: none

* relations accepted by the original verifier: 25/59
* rejected by the gate: 1
* rejected relations that the gate-off composer had used: 1

| fixture | relation | kind | verifier | gate | reason | used by composer |
|---|---|---|---|---|---|---|
| dedup_channel | O0 | observer | BOUNDED | UNVERIFIED | no domain input both satisfied the condition and produced a supporting observation | yes |

## Per-fixture guards

| fixture | set | Direct | Full MACE | Composer (gate OFF) | Gated | gate counts (W/R/U) |
|---|---|---|---|---|---|---|
| alt_masking | dev6 | exact | exact | exact | exact | 2/3/0 |
| dedup_channel | dev6 | exact | invalid | incomplete | unknown | 1/2/3 |
| modulo_absorb | dev6 | unsound | invalid | unknown | unknown | 2/3/0 |
| overwrite_channel | dev6 | exact | unsound | unknown | unknown | 1/4/0 |
| sort_channel | dev6 | unsound | incomplete | incomplete | incomplete | 3/1/0 |
| swap_channels | dev6 | incomplete | unsound | unknown | unknown | 3/2/0 |
| dead_flag | held1 | exact | exact | exact | exact | 4/0/0 |
| dict_slot | held1 | exact | exact | unknown | unknown | 3/2/0 |
| parity_snap | held1 | unsound | unsound | exact | exact | 3/5/0 |
| clamp_absorb | held2 | unsound | invalid | unknown | unknown | 1/1/5 |
| toggle_pair | held2 | unsound | incomplete | unknown | unknown | 1/4/0 |

## Per-fixture guard strings

| fixture | method | guard | status | unsound | incomplete |
|---|---|---|---|---|---|
| alt_masking | Direct Qwen | `mode == 0 or mode == 1` | BOUNDED | 0 | 0 |
| alt_masking | Full MACE | `mode == 0 or mode == 1` | BOUNDED | 0 | 0 |
| alt_masking | Composer (gate OFF) | `((mode == 0 or mode == 1))` | BOUNDED | 0 | 0 |
| alt_masking | Evidence-gated composer | `((mode == 0 or mode == 1))` | BOUNDED | 0 | 0 |
| dedup_channel | Direct Qwen | `distinct(xs) == distinct(xs + [xs[0] + 1])` | BOUNDED | 0 | 0 |
| dedup_channel | Full MACE | `len(xs) == 0 or (pre and distinct(xs) and len(fn_0(xs)) == len(fn_0(xs + [xs[0] + 1])))` | INVALID | 0 | 0 |
| dedup_channel | Composer (gate OFF) | `((len(xs) == 0))` | REFUTED | 0 | 100 |
| dedup_channel | Evidence-gated composer | `-` | ABSENT | None | None |
| modulo_absorb | Direct Qwen | `cap and (fn_0(xs) + 1) % 10 == 0` | REFUTED | 47 | 212 |
| modulo_absorb | Full MACE | `cap and (fn_0(xs) - fn_0(xs) % 10) == fn_0(xs) + 1 if not cap else fn_0(xs)` | INVALID | 0 | 0 |
| modulo_absorb | Composer (gate OFF) | `-` | ABSENT | None | None |
| modulo_absorb | Evidence-gated composer | `-` | ABSENT | None | None |
| overwrite_channel | Direct Qwen | `fn_0(xs) == 0 if not keep else True` | BOUNDED | 0 | 0 |
| overwrite_channel | Full MACE | `keep or not keep` | REFUTED | 28 | 0 |
| overwrite_channel | Composer (gate OFF) | `-` | ABSENT | None | None |
| overwrite_channel | Evidence-gated composer | `-` | ABSENT | None | None |
| sort_channel | Direct Qwen | `use_left == False and use_right == False` | REFUTED | 1134 | 6452 |
| sort_channel | Full MACE | `xs == sorted(xs)` | REFUTED | 0 | 7046 |
| sort_channel | Composer (gate OFF) | `(((xs == sorted(xs))) and ((xs == sorted(xs))))` | REFUTED | 0 | 7046 |
| sort_channel | Evidence-gated composer | `(((xs == sorted(xs))) and ((xs == sorted(xs))))` | REFUTED | 0 | 7046 |
| swap_channels | Direct Qwen | `not show_gap` | REFUTED | 0 | 4 |
| swap_channels | Full MACE | `True` | REFUTED | 12 | 0 |
| swap_channels | Composer (gate OFF) | `-` | ABSENT | None | None |
| swap_channels | Evidence-gated composer | `-` | ABSENT | None | None |
| dead_flag | Direct Qwen | `True` | BOUNDED | 0 | 0 |
| dead_flag | Full MACE | `True` | BOUNDED | 0 | 0 |
| dead_flag | Composer (gate OFF) | `(((True)) and ((True)))` | BOUNDED | 0 | 0 |
| dead_flag | Evidence-gated composer | `(((True)) and ((True)))` | BOUNDED | 0 | 0 |
| dict_slot | Direct Qwen | `mode` | BOUNDED | 0 | 0 |
| dict_slot | Full MACE | `mode` | BOUNDED | 0 | 0 |
| dict_slot | Composer (gate OFF) | `-` | ABSENT | None | None |
| dict_slot | Evidence-gated composer | `-` | ABSENT | None | None |
| parity_snap | Direct Qwen | `sum(xs) % 2 == 0 and not even` | REFUTED | 43 | 43 |
| parity_snap | Full MACE | `even and sum(xs) % 2 == 0 or not even` | REFUTED | 85 | 0 |
| parity_snap | Composer (gate OFF) | `((even and sum(xs) % 2 == 0))` | BOUNDED | 0 | 0 |
| parity_snap | Evidence-gated composer | `((even and sum(xs) % 2 == 0))` | BOUNDED | 0 | 0 |
| clamp_absorb | Direct Qwen | `sum(xs) + 1 == min(sum(xs) + 1, 10) if cap else sum(xs) + 1 == sum(xs)` | REFUTED | 74 | 11 |
| clamp_absorb | Full MACE | `total_post <= 10 or not cap` | INVALID | 0 | 0 |
| clamp_absorb | Composer (gate OFF) | `-` | ABSENT | None | None |
| clamp_absorb | Evidence-gated composer | `-` | ABSENT | None | None |
| toggle_pair | Direct Qwen | `not flag` | REFUTED | 6 | 9 |
| toggle_pair | Full MACE | `flag` | REFUTED | 0 | 3 |
| toggle_pair | Composer (gate OFF) | `-` | ABSENT | None | None |
| toggle_pair | Evidence-gated composer | `-` | ABSENT | None | None |

## Cost

| fixture | method | tokens | model wall s | verification calls | verification program runs | evaluation program runs |
|---|---|---|---|---|---|---|
| alt_masking | Direct Qwen | 701 | 0.0 | 0 | 0 | 320 |
| alt_masking | Full MACE | 13280 | 72.7 | 3 | 960 | 320 |
| alt_masking | Composer (gate OFF) | 0 | 0.0 | 0 | 0 | 320 |
| alt_masking | Evidence-gated composer | 0 | 0.0 | 0 | 0 | 320 |
| dedup_channel | Direct Qwen | 1573 | 0.0 | 0 | 0 | 480 |
| dedup_channel | Full MACE | 12087 | 69.231 | 3 | 1440 | 480 |
| dedup_channel | Composer (gate OFF) | 0 | 0.0 | 0 | 0 | 480 |
| dedup_channel | Evidence-gated composer | 0 | 0.0 | 0 | 0 | 480 |
| modulo_absorb | Direct Qwen | 2793 | 0.0 | 0 | 0 | 1036 |
| modulo_absorb | Full MACE | 13931 | 66.653 | 3 | 3108 | 1036 |
| modulo_absorb | Composer (gate OFF) | 0 | 0.0 | 0 | 0 | 1036 |
| modulo_absorb | Evidence-gated composer | 0 | 0.0 | 0 | 0 | 1036 |
| overwrite_channel | Direct Qwen | 2634 | 0.0 | 0 | 0 | 160 |
| overwrite_channel | Full MACE | 15024 | 66.874 | 3 | 480 | 160 |
| overwrite_channel | Composer (gate OFF) | 0 | 0.0 | 0 | 0 | 160 |
| overwrite_channel | Evidence-gated composer | 0 | 0.0 | 0 | 0 | 160 |
| sort_channel | Direct Qwen | 3720 | 0.0 | 0 | 0 | 21824 |
| sort_channel | Full MACE | 11886 | 50.318 | 3 | 65472 | 21824 |
| sort_channel | Composer (gate OFF) | 0 | 0.0 | 0 | 0 | 21824 |
| sort_channel | Evidence-gated composer | 0 | 0.0 | 0 | 0 | 21824 |
| swap_channels | Direct Qwen | 2801 | 0.0 | 0 | 0 | 64 |
| swap_channels | Full MACE | 14299 | 61.913 | 3 | 192 | 64 |
| swap_channels | Composer (gate OFF) | 0 | 0.0 | 0 | 0 | 64 |
| swap_channels | Evidence-gated composer | 0 | 0.0 | 0 | 0 | 64 |
| dead_flag | Direct Qwen | 1319 | 0.0 | 0 | 0 | 80 |
| dead_flag | Full MACE | 1558 | 17.796 | 1 | 80 | 80 |
| dead_flag | Composer (gate OFF) | 0 | 0.0 | 0 | 0 | 80 |
| dead_flag | Evidence-gated composer | 0 | 0.0 | 0 | 0 | 80 |
| dict_slot | Direct Qwen | 642 | 0.0 | 0 | 0 | 160 |
| dict_slot | Full MACE | 12729 | 51.765 | 3 | 480 | 160 |
| dict_slot | Composer (gate OFF) | 0 | 0.0 | 0 | 0 | 160 |
| dict_slot | Evidence-gated composer | 0 | 0.0 | 0 | 0 | 160 |
| parity_snap | Direct Qwen | 2460 | 0.0 | 0 | 0 | 340 |
| parity_snap | Full MACE | 14870 | 86.375 | 3 | 1020 | 340 |
| parity_snap | Composer (gate OFF) | 0 | 0.0 | 0 | 0 | 340 |
| parity_snap | Evidence-gated composer | 0 | 0.0 | 0 | 0 | 340 |
| clamp_absorb | Direct Qwen | 2404 | 0.0 | 0 | 0 | 340 |
| clamp_absorb | Full MACE | 15391 | 89.208 | 3 | 1020 | 340 |
| clamp_absorb | Composer (gate OFF) | 0 | 0.0 | 0 | 0 | 340 |
| clamp_absorb | Evidence-gated composer | 0 | 0.0 | 0 | 0 | 340 |
| toggle_pair | Direct Qwen | 2579 | 0.0 | 0 | 0 | 36 |
| toggle_pair | Full MACE | 16026 | 71.677 | 3 | 108 | 36 |
| toggle_pair | Composer (gate OFF) | 0 | 0.0 | 0 | 0 | 36 |
| toggle_pair | Evidence-gated composer | 0 | 0.0 | 0 | 0 | 36 |

The gate adds no model calls and no program executions: it reuses the counters and paired rows already produced by the bounded checker. Evaluation runs are the re-check of each candidate guard and are not part of the method's inference cost.
