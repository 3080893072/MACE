# M6 phase 2: guard-retention replay

Split seed 20261030; fit and eval are disjoint halves of the declared finite domain. `best-ever` uses eval labels and is a ceiling, not an online policy.

## dev6

| method | cases | first | final | online | best-ever | online fit-valid |
|---|---|---|---|---|---|---|
| MACE A (Qwen guard) | 6 | 1 | 1 | 1 | 1 | 1 |
| C reviewed contract + Qwen guard | 6 | 3 | 3 | 3 | 3 | 3 |
| direct prompt, 12 rounds | 6 | 1 | 3 | 3 | 3 | 3 |
| direct prompt | 6 | 1 | 3 | 3 | 3 | 3 |
| fixed template | 6 | 1 | 2 | 2 | 2 | 2 |
| generic prompt | 6 | 1 | 1 | 1 | 1 | 1 |

## held1

| method | cases | first | final | online | best-ever | online fit-valid |
|---|---|---|---|---|---|---|
| MACE A (Qwen guard) | 3 | 2 | 2 | 3 | 3 | 3 |
| C reviewed contract + Qwen guard | 3 | 2 | 2 | 2 | 2 | 2 |
| H/direct | 3 | 1 | 2 | 2 | 2 | 2 |
| H/fixed | 3 | 2 | 2 | 2 | 2 | 2 |
| H/generic | 3 | 2 | 2 | 2 | 2 | 2 |
| H/qwen | 3 | 1 | 2 | 2 | 2 | 2 |
| MACE A (held-out rerun) | 3 | 2 | 2 | 3 | 3 | 3 |
| direct prompt, 12 rounds | 3 | 1 | 2 | 2 | 2 | 2 |
| direct prompt | 3 | 1 | 2 | 2 | 2 | 2 |
| fixed template | 3 | 2 | 2 | 2 | 2 | 2 |
| generic prompt | 3 | 2 | 2 | 2 | 2 | 2 |

## held2

| method | cases | first | final | online | best-ever | online fit-valid |
|---|---|---|---|---|---|---|
| H3/direct | 2 | 0 | 0 | 0 | 0 | 0 |
| H3/fixed | 2 | 0 | 0 | 0 | 0 | 0 |
| H3/generic | 2 | 0 | 0 | 0 | 0 | 0 |
| MACE A (held-out batch 2) | 2 | 0 | 0 | 0 | 0 | 0 |

## Runs where the final guard is worse than an earlier fit-valid guard

| method | fixture | valid rounds (fit) | final eval | online eval |
|---|---|---|---|---|
| A3/qwen | parity_snap | 1 | wrong (u=62, i=0) | exact (u=0, i=0) |
| H2/qwen | parity_snap | 1 | wrong (u=41, i=0) | exact (u=0, i=0) |
