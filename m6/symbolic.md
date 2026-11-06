# M6 phase 3: symbolic engine vs stored Qwen/MACE guards

Every guard is re-checked on the full declared finite domain; a pass is `BOUNDED`, never `PROVEN`. `pure` disables helper summaries and therefore has no way to model the helper functions. Symbolic runtime is wall-clock on this machine (CPU, no model).

## dev6

| method | cases | derived | UNKNOWN | exact | sound | complete | median nodes | max nodes | tokens | wall s |
|---|---|---|---|---|---|---|---|---|---|---|
| Direct Qwen | 6 | 6 | 0 | 3 | 4 | 3 | 14 | 24 | 14222 | 61.48 |
| Full MACE (A) | 6 | 6 | 0 | 1 | 2 | 3 | 12 | 49 | 80507 | 387.69 |
| Pure Symbolic | 6 | 2 | 4 | 2 | 2 | 2 | 0 | 12 | 0 | 0.01 |
| Symbolic + summaries | 6 | 6 | 0 | 6 | 6 | 6 | 15 | 88 | 0 | 0.01 |

## held1

| method | cases | derived | UNKNOWN | exact | sound | complete | median nodes | max nodes | tokens | wall s |
|---|---|---|---|---|---|---|---|---|---|---|
| Direct Qwen | 3 | 3 | 0 | 2 | 2 | 2 | 2 | 17 | 4421 | 19.15 |
| Full MACE (A) | 3 | 3 | 0 | 2 | 2 | 3 | 2 | 21 | 29157 | 155.94 |
| Pure Symbolic | 3 | 3 | 0 | 3 | 3 | 3 | 2 | 15 | 0 | 0.0 |
| Symbolic + summaries | 3 | 3 | 0 | 3 | 3 | 3 | 2 | 15 | 0 | 0.0 |

## held2

| method | cases | derived | UNKNOWN | exact | sound | complete | median nodes | max nodes | tokens | wall s |
|---|---|---|---|---|---|---|---|---|---|---|
| Direct Qwen | 2 | 2 | 0 | 0 | 0 | 0 | 40 | 40 | 4983 | 21.68 |
| Full MACE (A) | 2 | 2 | 0 | 0 | 1 | 0 | 11 | 11 | 31417 | 160.88 |
| Pure Symbolic | 2 | 2 | 0 | 2 | 2 | 2 | 12 | 12 | 0 | 0.0 |
| Symbolic + summaries | 2 | 2 | 0 | 2 | 2 | 2 | 12 | 12 | 0 | 0.0 |

## Per-fixture checks

| fixture | method | guard | status | exact | unsound | incomplete | nodes | paths | coverage | wall s |
|---|---|---|---|---|---|---|---|---|---|---|
| alt_masking | Direct Qwen | `mode == 0 or mode == 1` | BOUNDED | yes | 0 | 0 | 12 | - | - | 5.324 |
| alt_masking | Full MACE (A) | `mode == 0 or mode == 1` | BOUNDED | yes | 0 | 0 | 12 | - | - | 72.7 |
| alt_masking | Pure Symbolic | `mode == 0 or mode == 1` | BOUNDED | yes | 0 | 0 | 12 | 6 | 0.667 | 0.003 |
| alt_masking | Symbolic + summaries | `mode == 0 or mode == 1` | BOUNDED | yes | 0 | 0 | 12 | 6 | 0.667 | 0.002 |
| dedup_channel | Direct Qwen | `distinct(xs) == distinct(xs + [xs[0] + 1])` | BOUNDED | yes | 0 | 0 | 24 | - | - | 8.507 |
| dedup_channel | Full MACE (A) | `len(xs) == 0 or (pre and distinct(xs) and len(fn_0(xs)) == len(fn_0(xs + [xs[0] + 1])))` | INVALID | no | 0 | 0 | 49 | - | - | 69.231 |
| dedup_channel | Pure Symbolic | `-` | ABSENT | no | None | None | 0 | - | 0.091 | 0.001 |
| dedup_channel | Symbolic + summaries | `count(xs, xs[0] + 1) > 0` | BOUNDED | yes | 0 | 0 | 16 | 2 | 0.818 | 0.001 |
| modulo_absorb | Direct Qwen | `cap and (fn_0(xs) + 1) % 10 == 0` | REFUTED | no | 47 | 212 | 18 | - | - | 13.549 |
| modulo_absorb | Full MACE (A) | `cap and (fn_0(xs) - fn_0(xs) % 10) == fn_0(xs) + 1 if not cap else fn_0(xs)` | INVALID | no | 0 | 0 | 39 | - | - | 66.653 |
| modulo_absorb | Pure Symbolic | `-` | ABSENT | no | None | None | 0 | - | 0.091 | 0.001 |
| modulo_absorb | Symbolic + summaries | `cap and sum(xs) % 10 != 9` | BOUNDED | yes | 0 | 0 | 15 | 2 | 0.818 | 0.001 |
| overwrite_channel | Direct Qwen | `fn_0(xs) == 0 if not keep else True` | BOUNDED | yes | 0 | 0 | 14 | - | - | 7.695 |
| overwrite_channel | Full MACE (A) | `keep or not keep` | REFUTED | no | 28 | 0 | 8 | - | - | 66.874 |
| overwrite_channel | Pure Symbolic | `-` | ABSENT | no | None | None | 0 | - | 0.091 | 0.001 |
| overwrite_channel | Symbolic + summaries | `keep or sum(xs) == 0` | BOUNDED | yes | 0 | 0 | 12 | 2 | 0.818 | 0.001 |
| sort_channel | Direct Qwen | `use_left == False and use_right == False` | REFUTED | no | 1134 | 6452 | 12 | - | - | 17.82 |
| sort_channel | Full MACE (A) | `xs == sorted(xs)` | REFUTED | no | 0 | 7046 | 9 | - | - | 50.318 |
| sort_channel | Pure Symbolic | `-` | ABSENT | no | None | None | 0 | - | 0.037 | 0.002 |
| sort_channel | Symbolic + summaries | `use_left and use_right or pre or (not use_left and (not use_right) and (max(xs) == xs[-1]) and (min(xs) == xs[0])) or (not use_left and min(xs) == xs[0] and use_right) or (not use_right and max(xs) == xs[-1] and use_left)` | BOUNDED | yes | 0 | 0 | 88 | 8 | 0.926 | 0.005 |
| swap_channels | Direct Qwen | `not show_gap` | REFUTED | no | 0 | 4 | 4 | - | - | 8.584 |
| swap_channels | Full MACE (A) | `True` | REFUTED | no | 12 | 0 | 1 | - | - | 61.913 |
| swap_channels | Pure Symbolic | `not show_gap or k == n` | BOUNDED | yes | 0 | 0 | 12 | 2 | 0.833 | 0.001 |
| swap_channels | Symbolic + summaries | `not show_gap or k == n` | BOUNDED | yes | 0 | 0 | 12 | 2 | 0.833 | 0.001 |
| dead_flag | Direct Qwen | `True` | BOUNDED | yes | 0 | 0 | 1 | - | - | 4.893 |
| dead_flag | Full MACE (A) | `True` | BOUNDED | yes | 0 | 0 | 1 | - | - | 17.796 |
| dead_flag | Pure Symbolic | `True` | BOUNDED | yes | 0 | 0 | 1 | 1 | 0.833 | 0.001 |
| dead_flag | Symbolic + summaries | `True` | BOUNDED | yes | 0 | 0 | 1 | 1 | 0.833 | 0.001 |
| dict_slot | Direct Qwen | `mode` | BOUNDED | yes | 0 | 0 | 2 | - | - | 2.785 |
| dict_slot | Full MACE (A) | `mode` | BOUNDED | yes | 0 | 0 | 2 | - | - | 51.765 |
| dict_slot | Pure Symbolic | `mode` | BOUNDED | yes | 0 | 0 | 2 | 2 | 0.667 | 0.001 |
| dict_slot | Symbolic + summaries | `mode` | BOUNDED | yes | 0 | 0 | 2 | 2 | 0.667 | 0.001 |
| parity_snap | Direct Qwen | `sum(xs) % 2 == 0 and not even` | REFUTED | no | 43 | 43 | 17 | - | - | 11.471 |
| parity_snap | Full MACE (A) | `even and sum(xs) % 2 == 0 or not even` | REFUTED | no | 85 | 0 | 21 | - | - | 86.375 |
| parity_snap | Pure Symbolic | `even and sum(xs) % 2 == 0` | BOUNDED | yes | 0 | 0 | 15 | 2 | 0.667 | 0.001 |
| parity_snap | Symbolic + summaries | `even and sum(xs) % 2 == 0` | BOUNDED | yes | 0 | 0 | 15 | 2 | 0.667 | 0.001 |
| clamp_absorb | Direct Qwen | `sum(xs) + 1 == min(sum(xs) + 1, 10) if cap else sum(xs) + 1 == sum(xs)` | REFUTED | no | 74 | 11 | 40 | - | - | 12.089 |
| clamp_absorb | Full MACE (A) | `total_post <= 10 or not cap` | INVALID | no | 0 | 0 | 11 | - | - | 89.208 |
| clamp_absorb | Pure Symbolic | `cap and sum(xs) >= 10` | BOUNDED | yes | 0 | 0 | 12 | 2 | 0.667 | 0.001 |
| clamp_absorb | Symbolic + summaries | `cap and sum(xs) >= 10` | BOUNDED | yes | 0 | 0 | 12 | 2 | 0.667 | 0.001 |
| toggle_pair | Direct Qwen | `not flag` | REFUTED | no | 6 | 9 | 4 | - | - | 9.595 |
| toggle_pair | Full MACE (A) | `flag` | REFUTED | no | 0 | 3 | 2 | - | - | 71.677 |
| toggle_pair | Pure Symbolic | `flag or n == 0` | BOUNDED | yes | 0 | 0 | 9 | 2 | 0.714 | 0.001 |
| toggle_pair | Symbolic + summaries | `flag or n == 0` | BOUNDED | yes | 0 | 0 | 9 | 2 | 0.714 | 0.001 |

## Explanation and cost

| fixture | method | explanation units | tokens | source stmts covered |
|---|---|---|---|---|
| alt_masking | Direct Qwen | - | 701 | -/- |
| alt_masking | Full MACE (A) | relations=5, rationales=5, source_lines=11 | 13280 | -/- |
| alt_masking | Pure Symbolic | paths=4, channel_rules=4 | 0 | 6/9 |
| alt_masking | Symbolic + summaries | paths=4, channel_rules=4 | 0 | 6/9 |
| dedup_channel | Direct Qwen | - | 1573 | -/- |
| dedup_channel | Full MACE (A) | relations=6, rationales=6, source_lines=7 | 12087 | -/- |
| dedup_channel | Pure Symbolic | - | 0 | 1/11 |
| dedup_channel | Symbolic + summaries | paths=2, channel_rules=2 | 0 | 9/11 |
| modulo_absorb | Direct Qwen | - | 2793 | -/- |
| modulo_absorb | Full MACE (A) | relations=5, rationales=5, source_lines=8 | 13931 | -/- |
| modulo_absorb | Pure Symbolic | - | 0 | 1/11 |
| modulo_absorb | Symbolic + summaries | paths=1, channel_rules=1 | 0 | 9/11 |
| overwrite_channel | Direct Qwen | - | 2634 | -/- |
| overwrite_channel | Full MACE (A) | relations=5, rationales=5, source_lines=5 | 15024 | -/- |
| overwrite_channel | Pure Symbolic | - | 0 | 1/11 |
| overwrite_channel | Symbolic + summaries | paths=2, channel_rules=4 | 0 | 9/11 |
| sort_channel | Direct Qwen | - | 3720 | -/- |
| sort_channel | Full MACE (A) | relations=4, rationales=4, source_lines=4 | 11886 | -/- |
| sort_channel | Pure Symbolic | - | 0 | 1/27 |
| sort_channel | Symbolic + summaries | paths=8, channel_rules=16 | 0 | 25/27 |
| swap_channels | Direct Qwen | - | 2801 | -/- |
| swap_channels | Full MACE (A) | relations=5, rationales=5, source_lines=12 | 14299 | -/- |
| swap_channels | Pure Symbolic | paths=2, channel_rules=6 | 0 | 5/6 |
| swap_channels | Symbolic + summaries | paths=2, channel_rules=6 | 0 | 5/6 |
| dead_flag | Direct Qwen | - | 1319 | -/- |
| dead_flag | Full MACE (A) | relations=4, rationales=4, source_lines=4 | 1558 | -/- |
| dead_flag | Pure Symbolic | paths=1, channel_rules=2 | 0 | 5/6 |
| dead_flag | Symbolic + summaries | paths=1, channel_rules=2 | 0 | 5/6 |
| dict_slot | Direct Qwen | - | 642 | -/- |
| dict_slot | Full MACE (A) | relations=5, rationales=5, source_lines=7 | 12729 | -/- |
| dict_slot | Pure Symbolic | paths=1, channel_rules=2 | 0 | 4/6 |
| dict_slot | Symbolic + summaries | paths=1, channel_rules=2 | 0 | 4/6 |
| parity_snap | Direct Qwen | - | 2460 | -/- |
| parity_snap | Full MACE (A) | relations=8, rationales=8, source_lines=13 | 14870 | -/- |
| parity_snap | Pure Symbolic | paths=1, channel_rules=1 | 0 | 4/6 |
| parity_snap | Symbolic + summaries | paths=1, channel_rules=1 | 0 | 4/6 |
| clamp_absorb | Direct Qwen | - | 2404 | -/- |
| clamp_absorb | Full MACE (A) | relations=7, rationales=7, source_lines=12 | 15391 | -/- |
| clamp_absorb | Pure Symbolic | paths=1, channel_rules=1 | 0 | 4/6 |
| clamp_absorb | Symbolic + summaries | paths=1, channel_rules=1 | 0 | 4/6 |
| toggle_pair | Direct Qwen | - | 2579 | -/- |
| toggle_pair | Full MACE (A) | relations=5, rationales=5, source_lines=7 | 16026 | -/- |
| toggle_pair | Pure Symbolic | paths=2, channel_rules=4 | 0 | 5/7 |
| toggle_pair | Symbolic + summaries | paths=2, channel_rules=4 | 0 | 5/7 |
