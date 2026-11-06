### Dev set: the six original fixtures

| method | cases | typed | sound | complete | exact | contract all-pass | attribution | tokens | s |
|---|---|---|---|---|---|---|---|---|---|
| MACE A (Qwen contract + Qwen guard) | 6 | 4 | 2 | 3 | 1 | 0 | 19/30 | 73694 | 388 |
| MACE B (Qwen contract + deterministic composition) | 6 | 3 | 3 | 1 | 1 | 0 | 19/30 | 73694 | 388 |
| direct guard prompt, 3 rounds | 6 | 6 | 4 | 3 | 3 | 0 | n/a | 13450 | 61 |
| generic masking prompt, 3 rounds | 6 | 4 | 1 | 3 | 1 | 0 | n/a | 20113 | 143 |
| fixed guard template, 3 rounds | 6 | 5 | 3 | 4 | 2 | 0 | n/a | 15775 | 68 |
| direct guard prompt, 12 rounds (token-matched) | 6 | 6 | 3 | 3 | 3 | 0 | n/a | 109206 | 258 |
| C reviewed contract + Qwen guard (diagnostic only) | 6 | 6 | 4 | 3 | 3 | 6 | 19/19 | 10345 | 49 |
| D reviewed contract + composition (diagnostic only) | 6 | 6 | 6 | 6 | 6 | 6 | 19/19 | 10345 | 49 |

### Held-out batch 1 (used during the parser-fix diagnosis)

| method | cases | typed | sound | complete | exact | contract all-pass | attribution | tokens | s |
|---|---|---|---|---|---|---|---|---|---|
| C reviewed contract + Qwen guard (diagnostic only) | 3 | 3 | 2 | 3 | 2 | 3 | 8/8 | 3785 | 13 |
| D reviewed contract + composition (diagnostic only) | 3 | 3 | 3 | 3 | 3 | 3 | 8/8 | 3785 | 13 |
| MACE (pre parser fix) | 3 | 2 | 2 | 2 | 2 | 1 | 14/14 | 21482 | 150 |
| direct guard prompt, 3 rounds (pre fix) | 3 | 3 | 2 | 2 | 2 | 0 | n/a | 4117 | 19 |
| generic masking prompt, 3 rounds (pre fix) | 3 | 2 | 2 | 2 | 2 | 0 | n/a | 4636 | 45 |
| fixed guard template, 3 rounds (pre fix) | 3 | 2 | 2 | 2 | 2 | 0 | n/a | 4292 | 17 |
| MACE A, rerun after parser fix | 3 | 3 | 2 | 3 | 2 | 1 | 17/17 | 26316 | 156 |
| MACE B, rerun after parser fix | 3 | 2 | 2 | 2 | 2 | 1 | 17/17 | 26316 | 156 |

### Held-out batch 2 (never used before this evaluation)

| method | cases | typed | sound | complete | exact | contract all-pass | attribution | tokens | s |
|---|---|---|---|---|---|---|---|---|---|
| MACE A (Qwen contract + Qwen guard) | 2 | 1 | 1 | 0 | 0 | 0 | 12/12 | 28502 | 161 |
| direct guard prompt, 3 rounds | 2 | 2 | 0 | 0 | 0 | 0 | n/a | 4680 | 22 |
| generic masking prompt, 3 rounds | 2 | 1 | 0 | 1 | 0 | 0 | n/a | 5997 | 44 |
| fixed guard template, 3 rounds | 2 | 1 | 0 | 1 | 0 | 0 | n/a | 5826 | 16 |
Notes
-----
* ``typed`` = guard parsed and type-checked; ``sound`` = typed and accepts no
  exposed input; ``complete`` = typed and rejects no masked input; ``exact`` =
  bounded-domain equality with the true mask.  Sound/complete are one-sided and
  are reported even when the overall verdict is REFUTED.
* ``contract all-pass`` means every non-guard relation reached BOUNDED/TESTED.
* ``attribution`` counts relations whose cited lines intersect the reviewed
  contract's cited lines.  It measures source-line overlap, not logical
  support; it is n/a where no relations were produced.
* Tokens are prompt tokens as reported by Ollama; s is model wall time, not
  including verification.
* Cells C/D are diagnostics on human-reviewed contracts, never system scores.
