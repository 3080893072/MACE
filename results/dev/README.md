# DEV results

Copies of the aggregate DEV artifacts. The canonical files live one level up
in `results/` at the paths the scripts write; these copies are byte-identical
and exist for navigation. `reproduction/verify_frozen.py` checks the canonical
files.

| File | Contents |
|---|---|
| `MACE_v2_1_dev_final.json` | Final DEV result set: totals, per-task records, paired C0-vs-Full comparison, all-DEV descriptive block. |
| `MACE_v2_1_dev_per_task.csv` | One row per DEV task with per-task metrics. |
| `MACE_four_methods_DEV_comparison.csv` | C0 / Full / Direct Qwen / Direct GLM side by side on the shared DEV cohort. |

Related files kept at `results/` root:

- `MACE_candidate_discovery_v2_1_dev.json` — pre-closure candidate discovery
  record (hashed in the frozen config).
- `MACE_direct_Qwen_v2_1_DEV_completed.json` — Direct Qwen, full DEV.
- `MACE_direct_Qwen_v2_1_dev_new.json` — the 15 newly executed calls.
- `MACE_direct_GLM_v2_1_dev.json`, `MACE_direct_GLM_v2_1_per_task.csv` —
  Direct GLM, full DEV.
- `MACE_v2_1_dev_per_task.csv` — canonical per-task CSV.
- `MACE_v2_1_frozen_config.json` — hashes, model config and the as-run
  number block (21 tasks / 27 inputs / C0 14 / Full 19).

Two denominators appear in these files and must not be conflated:

- **25 masking inputs** — primary 21-task cohort after the v2.1 role fix; this
  is the paper denominator (C0 13, Full 18).
- **27 masking inputs** — as-run legacy role definition (C0 14, Full 19).

See `results/paper/MACE_paper_numbers_provenance.csv` for the authoritative
cell-by-cell mapping.
