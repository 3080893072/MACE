# MACE Direct Qwen 32B — v2.1 DEV Completion

Generated: 2026-11-05T12:24:30Z  
Dataset: `benchmark_v4_dataset/source_derived_v2_1` (formal v2.1, DEV only)

## 1. What was run

- Reused: 10 existing Direct Qwen tasks / 15 masking inputs (`runs/sd_direct_vs_full/raw/`), raw responses untouched.
- New: 15 missing DEV tasks / 15 masking inputs, one call each, temperature 0, seed 42, num_ctx 8192, num_predict 4096, retries 0.
- Model: `qwen2.5-coder:32b`, Ollama digest `b92d6a0bd47ee79114298de0177bf920c05a706d12633950b3936778492bef41` (matches the frozen Direct-Qwen record).
- Prompt/parser/limits: identical to the frozen Direct protocol; the 10 reused prompts were verified byte-identical to a v2.1 rebuild.

### Context handling note

- Declared protocol (both phases): `num_ctx=8192`, `num_predict=4096`, temperature 0, seed 42, retries 0.
- Observed prompt token counts in the 10 reused calls: [1860, 1956, 2630, 3306, 4098]. 6 of them hit exactly 4098 tokens, i.e. prompts above the serving budget were truncated; shorter prompts were fully evaluated.
- Observed prompt token counts in the 15 new calls: [1581, 2599, 4098, 4144, 6513, 7842]. 3 new task(s) fall between 4098 and 8192 tokens and were therefore evaluated with more context than the reused phase would have allowed; longer prompts still truncate to 4098.
- Consequence: for that narrow band the new arm saw more context. This is a serving-environment artefact, not a protocol change (both phases declare num_ctx=8192). It can only help the 15 new tasks, so the Direct baseline is not disadvantaged; the exact count is disclosed rather than silently pooled.

## 2. Full 25-task DEV (30 masking inputs)

| Method | Exact | False relations | Unmatched | Present |
|---|---|---|---|---|
| Direct Qwen 32B | **5/30** | 119 | 61 | 16 |
| Direct GLM (same 30 inputs) | 9/30 | 53 | 12 | — |
| Full MACE (21 v2.1 tasks + 4 v2 tasks) | 21/30 | — | — | — |
| C0 (same 30 inputs) | 13/30 | — | — | — |

C0 is **task-level only**: the frozen C0 artefacts record `c0_exact`/`masking_inputs` per task but no per-input prediction, so C0 cannot enter a paired McNemar test.

## 3. Primary 21-task cohort (25 masking inputs)

| Method | Exact | Denominator |
|---|---|---|
| C0 | 13 | 25 |
| Full MACE | 18 | 25 |
| Direct GLM | 5 | 25 |
| Direct Qwen 32B | **2** | 25 |

Direct Qwen on this cohort: false relations 110, unmatched sets 55, present 13.

## 4. By mechanism (full 25-task DEV)

| Mechanism | Tasks | Inputs | C0 | Full MACE | Direct GLM | Direct Qwen |
|---|---|---|---|---|---|---|
| M1_SINGLE_OPERATION | 8 | 9 | 8/9 | 7/9 | 1/9 | **0/9** |
| M2_TWO_OPERATION_COOPERATIVE | 5 | 6 | 1/6 | 6/6 | 3/6 | **2/6** |
| M3_THREE_OPERATION_COOPERATIVE | 3 | 3 | 0/3 | 3/3 | 2/3 | **0/3** |
| M4_ALTERNATIVE_PATHS | 2 | 2 | 0/2 | 1/2 | 2/2 | **1/2** |
| M5_CONDITIONAL_BRANCH | 2 | 2 | 2/2 | 2/2 | 0/2 | **1/2** |
| M6_CROSS_FUNCTION_STATE | 1 | 2 | 0/2 | 0/2 | 0/2 | **0/2** |
| M7_LOOP_STATE | 2 | 2 | 2/2 | 2/2 | 1/2 | **1/2** |
| M8_OBJECT_SHARED_STATE | 1 | 1 | 0/1 | 0/1 | 0/1 | **0/1** |
| M9_EXCEPTION_FALLBACK | 1 | 3 | 0/3 | 0/3 | 0/3 | **0/3** |

M10_NEGATIVE_CONTROL exists only in the sealed HELDOUT split; DEV contains M1–M9 only.

## 5. Paired per-input comparison (Full / GLM / Qwen)

C0 has no per-input predictions, so it is excluded from every paired test below; this is a coverage limit, not a null result.

| Pair | Cohort | Discordant (A only / B only) | Exact McNemar p |
|---|---|---|---|
| Full vs GLM | 30 inputs | 13 / 1 | 0.0018 |
| Full vs GLM | primary 25 | 13 / 0 | 0.0002 |
| Full vs Qwen | 30 inputs | 17 / 1 | 0.0001 |
| Full vs Qwen | primary 25 | 16 / 0 | <0.0001 |
| GLM vs Qwen | 30 inputs | 5 / 1 | 0.2188 |
| GLM vs Qwen | primary 25 | 4 / 1 | 0.375 |

## 6. Output validity and efficiency

- Valid output (>=1 mapped relation): 20/25 tasks, 25/30 masking inputs.
- Present (every hidden MSMS set found; frozen-artifact definition): 16/30.
- Tasks with no mapped relation (5/25): `sd_docutils_make_id_nonid_m2`, `sd_docutils_smartquotes_strip_m1`, `sd_tabulate_1052_strip_right`, `sd_tabulate_1056_strip_center`, `sd_toml_strict_num_strip_m1`.

| Split | Tasks | Runtime | Prompt tokens | Completion tokens |
|---|---|---|---|---|
| 15 new calls | 15 | 916.159 s | 63659 | 15123 |
| Full DEV (reused + new) | 25 | 1512.616 s | 97999 | 26225 |

## 7. Integrity

- Completed JSON SHA-256: `a2bf7424109500842ec94ce3775a2a22478a6ac211af2acc733536e4764ecce7`
- New-call file SHA-256: `7bd3082d9d300ffd3ec0c42a26bb9ce8fc8255a207ab183c150822cbb0aa6187`
- C0 per-input predictions: **absent** (task-level counts only); no McNemar statistic is reported against C0.
- HELDOUT: not read, not run, not scored in this round.