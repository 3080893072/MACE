# Paper numbers

| File | Contents |
|---|---|
| `MACE_paper_numbers_provenance.csv` | One row per number that appears in the paper: value, denominator, scope, source file, field path, whether it is derived, and a note on what must not be done with it. |
| `MACE_paper_table_status_matrix.csv` | Status of every paper cell at the time of the freeze: confirmed, measured on a partial cohort, or not run. |

`MACE_paper_numbers_provenance.csv` is the authoritative mapping. If a number
in the paper disagrees with it, the provenance file wins and the paper is
wrong.

Values that are frequently confused:

| | Paper value | As-run legacy value |
|---|---|---|
| DEV masking inputs | 25 | 27 |
| C0 strict exact | 13/25 | 14/27 |
| Full MACE strict exact | 18/25 | 19/27 |
| Full false relations | 5 | 5 |
| Full unmatched sets | 2 | 2 |

The legacy values are preserved in
`results/MACE_v2_1_frozen_config.json` under `final_numbers` and must not be
quoted as the paper denominator.

HELDOUT values postdate this matrix and are in
`results/heldout/MACE_HELDOUT_v2_1_official_scores.json`; the matrix records
their earlier "unscored" status and should be read with that in mind.
