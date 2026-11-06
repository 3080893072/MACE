# M6 phase 4: bounded condition induction

Implementation SHA-256: `7b514fda833186ebff50a87c0ce1b9a616819136a56e5739212dc99106875b54`; git HEAD: `7599e20bb0faf06ad64d385b0f02e1b8f8099829`. Sets: held1, held2; pool levels: full.

The guard predicts whether replacing A by `pass` leaves every returned channel unchanged. Selection uses the fit half only; the eval half is disjoint and is not used for candidate choice. All verdicts are bounded (`BOUNDED`/`TESTED`), never `PROVEN`.

## held1

| method | cases | exact | sound | complete | tokens | wall s |
|---|---|---|---|---|---|---|
| Direct Qwen | 3 | 2 | 2 | 2 | 4421 | 19.15 |
| Full MACE (A) | 3 | 2 | 2 | 3 | 29157 | 155.94 |
| Induction (full, sufficient) | 3 | 2 | 3 | 2 | 0 | 1.11 |
| Induction (full, necessary) | 3 | 0 | 1 | 0 | 0 | 1.11 |

| fixture | direction | guard | check | unsound | incomplete | nodes | clauses | eval kind | seconds |
|---|---|---|---|---|---|---|---|---|---|
| dead_flag/full | sufficient | `len(xs) > 0` | REFUTED | 0 | 1 | 8 | 1 | sufficient | 0.33 |
| dead_flag/full | necessary | `not (((sum(xs) != 1) and ((count(xs, xs[-1] + 1) > 0) if len(xs) > 0 else False)) or ((distinct(xs) < len(xs)) and ((min(xs) == max(xs)) if len(xs) > 0 else True)) or ((count(xs, 0) > 0) and (count(xs, 1) > 0) and (distinct(xs) == len(xs))) or ((sum(xs) != 1) and (sum(xs) % 2 != 0) and (distinct(xs) < len(xs)) and ((xs[0] == min(xs)) if len(xs) > 0 else False)))` | REFUTED | 0 | 20 | 165 | 4 | sufficient | 0.33 |
| dict_slot/full | sufficient | `mode` | BOUNDED | 0 | 0 | 2 | 1 | exact | 0.34 |
| dict_slot/full | necessary | `not (((mode) and (sum(xs) % 5 != 2) and ((min(xs) == max(xs)) if len(xs) > 0 else True)) or ((mode) and (sum(xs) % 5 != 0) and (sum(xs) % 5 != 1) and ((count(xs, xs[-1] + 1) > 0) if len(xs) > 0 else False)) or ((sum(xs) % 5 != 0) and (sum(xs) % 5 != 2) and (sum(xs) % 5 != 3) and ((min(xs) == max(xs)) if len(xs) > 0 else True)) or ((not mode) and (count(xs, 1) > 0) and (sum(xs) % 5 != 2) and (sum(xs) % 5 != 3)) or ((mode) and (sum(xs) % 5 != 0) and (sum(xs) % 5 != 1) and (distinct(xs) < len(xs)) and ((xs[0] == min(xs)) if len(xs) > 0 else False)))` | REFUTED | 26 | 22 | 249 | 5 | neither | 0.34 |
| parity_snap/full | sufficient | `(even) and (sum(xs) % 2 != 1)` | BOUNDED | 0 | 0 | 15 | 1 | exact | 0.43 |
| parity_snap/full | necessary | `not (((count(xs, 2) > 0) and ((min(xs) == max(xs)) if len(xs) > 0 else True)) or ((count(xs, 2) > 0) and ((count(xs, xs[-1] + 1) > 0) if len(xs) > 0 else False) and ((count(xs, xs[-1] + 2) > 0) if len(xs) > 0 else False)) or ((sum(xs) <= 1) and (count(xs, 2) > 0) and ((count(xs, xs[-1] + 1) > 0) if len(xs) > 0 else False)) or ((not even) and (distinct(xs) < len(xs)) and ((min(xs) == max(xs)) if len(xs) > 0 else True)) or ((even) and (count(xs, 0) > 0) and (sum(xs) % 2 != 1)) or ((even) and (sum(xs) <= 0) and (sum(xs) % 2 != 1)) or ((not even) and (distinct(xs) < len(xs)) and ((count(xs, xs[0] + 1) > 0) if len(xs) > 0 else False) and ((count(xs, xs[-1] + 1) > 0) if len(xs) > 0 else False)) or ((count(xs, 0) > 0) and (sum(xs) % 2 != 1) and (distinct(xs) < len(xs)) and ((count(xs, xs[-1] + 1) > 0) if len(xs) > 0 else False)) or ((even) and (sum(xs) % 2 != 0) and (distinct(xs) == len(xs)) and ((count(xs, xs[-1] + 1) > 0) if len(xs) > 0 else False)) or ((not even) and (count(xs, 2) > 0) and (sum(xs) % 2 != 1) and ((count(xs, xs[-1] + 2) > 0) if len(xs) > 0 else False)) or ((even) and (sum(xs) != 1) and (distinct(xs) < len(xs)) and ((count(xs, xs[-1] + 2) > 0) if len(xs) > 0 else False)) or ((not even) and (sum(xs) == 1) and (distinct(xs) < len(xs)) and ((count(xs, xs[-1] + 2) > 0) if len(xs) > 0 else False)) or ((not even) and (distinct(xs) == len(xs)) and ((xs[-1] == max(xs)) if len(xs) > 0 else False) and ((count(xs, xs[0] + 1) > 0) if len(xs) > 0 else False)) or ((sum(xs) <= 1) and (distinct(xs) == len(xs)) and ((xs[-1] == max(xs)) if len(xs) > 0 else False) and ((count(xs, xs[0] + 1) > 0) if len(xs) > 0 else False)) or ((sum(xs) != 1) and (sum(xs) % 2 != 0) and (distinct(xs) < len(xs)) and ((count(xs, xs[0] + 1) > 0) if len(xs) > 0 else False)) or ((sum(xs) % 2 != 1) and (distinct(xs) == len(xs)) and ((xs[-1] == max(xs)) if len(xs) > 0 else False) and ((count(xs, xs[0] + 2) > 0) if len(xs) > 0 else False)) or ((not even) and (sum(xs) % 2 != 1) and (distinct(xs) == len(xs)) and ((count(xs, xs[0] + 2) > 0) if len(xs) > 0 else False)) or ((not even) and (sum(xs) <= 1) and (distinct(xs) < len(xs)) and ((xs[-1] == max(xs)) if len(xs) > 0 else False)) or ((sum(xs) != 2) and (sum(xs) % 2 != 1) and (distinct(xs) < len(xs)) and ((xs[-1] == max(xs)) if len(xs) > 0 else False)) or ((len(xs) == 3) and (sum(xs) != 2) and (sum(xs) % 2 != 1) and ((xs[-1] == max(xs)) if len(xs) > 0 else False)) or ((even) and (sum(xs) <= 1) and (distinct(xs) == len(xs)) and ((xs[0] == min(xs)) if len(xs) > 0 else False)) or ((sum(xs) != 1) and (count(xs, 0) > 0) and (sum(xs) % 2 != 0) and (distinct(xs) < len(xs))) or ((even) and (sum(xs) != 1) and (sum(xs) >= 0) and (count(xs, 1) > 0) and (sum(xs) % 2 != 0) and (distinct(xs) < len(xs))))` | REFUTED | 50 | 35 | 1216 | 23 | neither | 0.43 |

## held2

| method | cases | exact | sound | complete | tokens | wall s |
|---|---|---|---|---|---|---|
| Direct Qwen | 2 | 0 | 0 | 0 | 4983 | 21.68 |
| Full MACE (A) | 2 | 0 | 1 | 0 | 31417 | 160.88 |
| Induction (full, sufficient) | 2 | 2 | 2 | 2 | 0 | 0.66 |
| Induction (full, necessary) | 2 | 0 | 0 | 0 | 0 | 0.66 |

| fixture | direction | guard | check | unsound | incomplete | nodes | clauses | eval kind | seconds |
|---|---|---|---|---|---|---|---|---|---|
| clamp_absorb/full | sufficient | `(cap) and (sum(xs) >= 10)` | BOUNDED | 0 | 0 | 12 | 1 | exact | 0.4 |
| clamp_absorb/full | necessary | `not (((cap) and ((count(xs, xs[-1] + 1) > 0) if len(xs) > 0 else False)) or ((sum(xs) == 10) and (count(xs, 0) > 0) and ((xs[-1] == max(xs)) if len(xs) > 0 else False)) or ((count(xs, 0) > 0) and (distinct(xs) == len(xs)) and ((xs[0] == min(xs)) if len(xs) > 0 else False)) or ((not cap) and (sum(xs) % 10 != 2) and ((xs[0] == min(xs)) if len(xs) > 0 else False) and ((count(xs, xs[0] + 1) > 0) if len(xs) > 0 else False)) or ((cap) and (count(xs, 0) > 0) and (sum(xs) % 10 != 1) and ((xs[0] == min(xs)) if len(xs) > 0 else False)) or ((not cap) and (sum(xs) >= 10) and (sum(xs) % 10 != 0) and (sum(xs) % 10 != 1)) or ((not cap) and (sum(xs) % 10 != 1) and (sum(xs) % 10 != 5) and (distinct(xs) == len(xs)) and ((min(xs) == max(xs)) if len(xs) > 0 else True)) or ((cap) and (sum(xs) % 10 != 1) and (sum(xs) % 10 != 2) and (sum(xs) % 10 != 3) and (sum(xs) % 10 != 5) and (sum(xs) % 10 != 6) and (sum(xs) % 10 != 8)) or ((sum(xs) % 10 != 1) and (sum(xs) % 10 != 2) and (sum(xs) % 10 != 3) and (sum(xs) % 10 != 5) and (sum(xs) % 10 != 6) and (sum(xs) % 10 != 7) and (distinct(xs) == len(xs)) and ((xs[-1] == max(xs)) if len(xs) > 0 else False)))` | REFUTED | 80 | 4 | 507 | 9 | neither | 0.4 |
| toggle_pair/full | sufficient | `(flag) or (n < 1)` | BOUNDED | 0 | 0 | 9 | 2 | exact | 0.26 |
| toggle_pair/full | necessary | `not ((k > 0) or (n == 1))` | REFUTED | 1 | 9 | 14 | 2 | neither | 0.26 |

## Witness and repair totals

| fixture/level | witnesses | masked | unmasked | pool | clauses | learn failures | repair steps |
|---|---|---|---|---|---|---|---|
| dead_flag/full | 40 | 40 | 0 | 35 | 1 | 0 | 0 |
| dict_slot/full | 80 | 40 | 40 | 75 | 1 | 0 | 0 |
| parity_snap/full | 170 | 43 | 127 | 46 | 1 | 0 | 0 |
| clamp_absorb/full | 170 | 11 | 159 | 62 | 1 | 0 | 1 |
| toggle_pair/full | 18 | 12 | 6 | 40 | 2 | 0 | 1 |
