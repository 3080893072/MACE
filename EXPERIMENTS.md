# Experiments and Evidence Status

This file records what was actually run, with which model, and where the
evidence lives. Model identity is implementation detail: the method claim does
not depend on a particular model family.

**Evidence levels used below**

| Label | Meaning |
|---|---|
| **A — per-call artifacts** | Raw request/response logs, config and per-task result files are in `runs/`. Numbers can be recomputed. |
| **B — frozen aggregate** | A frozen result file or scoring output exists, but the raw per-call log for that batch is not in the repository. |
| **C — reported complete, no verifiable data in current files** | The run is described in a report, but neither per-call logs nor a result file can be found. Used only where true. |

## 1. Run matrix

| Method | Dataset | Model | Status | Primary evidence |
|---|---|---|---|---|
| C0 — Graph/AST only | MACE-Bench v2.1 DEV | none | A | `results/MACE_v2_1_dev_final.json`, `runs/candidate_discovery_v2_1/` |
| Full MACE | MACE-Bench v2.1 DEV | `qwen2.5-coder:32b` | A | `runs/candidate_discovery_v2_1/raw/` |
| Direct Qwen | MACE-Bench v2.1 DEV | `qwen2.5-coder:32b` | A | `results/MACE_direct_Qwen_v2_1_DEV_completed.json`, `runs/direct_qwen_v2_1/` |
| Direct GLM | MACE-Bench v2.1 DEV | `glm-4.7-flash:q4_K_M` | A | `results/MACE_direct_GLM_v2_1_dev.json`, `runs/direct_glm_v2_1/` |
| C0 / Full / Direct Qwen / Direct GLM | MACE-Bench v2.1 HELDOUT | as above | B | frozen predictions + `results/heldout/MACE_HELDOUT_v2_1_official_scores.json` |
| 7B full MACE | historical 6 fixtures | `qwen2.5-coder:7b` | B (aggregate only) | `results/summary_7b.md`, `docs/M1_report.md` |
| 14B / 32B guard study | historical 6 fixtures | `qwen2.5-coder:14b` / `:32b` | B (aggregate only) | `results/summary_14b.md`, `results/summary_32b.md` |
| Qwen semantic feedback v1 | 6 pilot tasks | `qwen2.5-coder:32b` | A | `runs/v3_semantic_feedback_v1/`, `docs/MACE_semantic_feedback_v1_results.md` |

No experiment was run with a proprietary API model. No GPU is required to
audit the frozen results; only re-running a model-backed method needs one.

## 2. Full MACE + Qwen 32B (main method)

Frozen configuration (`results/MACE_v2_1_frozen_config.json`):

- model `qwen2.5-coder:32b`, Q4_K_M, digest
  `b92d6a0bd47ee79114298de0177bf920c05a706d12633950b3936778492bef41`
- temperature 0, seed 42, retries 0
- `num_ctx` 16384, `num_predict` 4096, timeout 900 s
- candidate budget per input 16, `max_ops` 6, search deadline 2700 s

Results (21-task primary cohort, 25 masking inputs):

| Metric | Value |
|---|---|
| Strict MSMS exact | 18/25 |
| False relations | 5 |
| Unmatched sets | 2 |
| Non-empty predictions | 19/25 |
| Probes executed | 276 |
| Wall clock | 747.53 s |
| Prompt / completion tokens | 145,939 / 11,288 |
| Paired vs C0 | 6 better, 14 equal, 1 worse |

Source: `results/MACE_v2_1_dev_final.json`; per-task rows in
`results/dev/MACE_v2_1_dev_per_task.csv`. Candidate provenance
(`U_ast` / `U_qwen` / `U_union`) is in
`docs/MACE_candidate_discovery_v2_1_dev_results.md`.

Note two denominators that must not be mixed:

- **21 tasks / 25 inputs** — the paper's main table, after the v2.1 role fix.
- **21 tasks / 27 inputs** — the as-run record under the legacy role
  definition (C0 14, Full 19). Preserved in the frozen config; never quoted as
  the paper denominator.

## 3. Qwen 7B

What was run:

- Hardware: AutoDL RTX 4090 D, 24 GB; Ollama with
  `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=1`, `KEEP_ALIVE=-1`.
- Model: `qwen2.5-coder:7b`, Q4_K_M, 7.6 B parameters, 4.7 GB, 100% resident
  on GPU.
- Decoding: temperature 0, seed 42, `format=json`, `num_ctx=8192`.
- Controls: `qwen2.5-coder:14b` (9.0 GB) and `qwen2.5-coder:0.5b`
  (397 MB, JSON-channel smoke only).
- Batch: six fixtures (`dedup_channel`, `sort_channel`, `swap_channels`,
  `alt_masking`, `modulo_absorb`, `overwrite_channel`) in four modes
  (`direct`, `fixed`, `generic`, `mace`).

Result, fixture-level guard accuracy (`results/summary_7b.md`):

| Mode | Guard verified |
|---|---|
| direct | 0/6 |
| fixed template | 0/6 |
| generic prompt | 0/6 |
| full MACE | 0/6 |

Per-call token and latency rows are in the same file (e.g. full MACE on
`sort_channel`: 6,192 prompt + 1,000 completion tokens, 22.4 s).

Separately, `docs/M1_report.md` records the 7B full MACE output on three
fixtures: 11 proposed relations, of which 5 were `BOUNDED`, 4 `REFUTED`, 2
`INVALID`; 6 of 11 judged unreliable; 12 guard checks, 0 correct.

**What is missing.** No `events.jsonl` / `config.json` run record for the 7B
batch exists in `runs/`; only the per-call summary table and the M1 report
survive. No v2.1 strict-MSMS scoring was run with 7B. The claim "Qwen 7B
experiments are complete" is accurate for the fixture-level M1 pilot and false
for MACE-Bench v2.1.

**Do not treat these numbers as a v2.1 comparison.** The 7B batch predates the
v2.1 protocol: six hand-written fixtures rather than benchmark tasks, guard
verification rather than strict MSMS exact match, no block projection, no
DEV/HELDOUT split, and no per-project virtual environments. A table that placed
7B next to C0 / Full MACE 32B / Direct baselines would be comparing different
constructs. The v2.1 table contains four methods only.

## 4. Direct Qwen 32B

Protocol: one model call per task; no candidate universe, no search, no
verifier. `num_ctx` 8192, `num_predict` 4096, temperature 0, seed 42, retries 0.

| Cohort | Strict exact | False relations | Unmatched | Present |
|---|---|---|---|---|
| Full DEV (25 tasks / 30 inputs) | 5/30 | 119 | 61 | 16 |
| Primary 21-task cohort (25 inputs) | 2/25 | 110 | 55 | 13 |
| HELDOUT (20 inputs) | 4/20 | 74 | 40 | — |

Runtime on the full DEV set: 1,512.6 s; 97,999 prompt + 26,225 completion
tokens. Source: `results/MACE_direct_Qwen_v2_1_DEV_completed.json`,
`docs/MACE_direct_Qwen_v2_1_DEV_completion.md`.

**Serving artefact, disclosed:** prompt token counts cap at 4098 although
`num_ctx` was declared 8192. 6 of 10 reused calls and all 15 new calls show
the cap; 3 new tasks had prompts between 4098 and 8192 tokens and therefore
saw more context than the reused phase. This can only help the Direct
baseline; it is listed per task in `context_truncated` columns.

## 5. Direct GLM

Model `glm-4.7-flash:q4_K_M` via Ollama, same Direct protocol.

| Cohort | Strict exact | Precision | Recall | False | Unmatched |
|---|---|---|---|---|---|
| Full DEV (25 tasks / 30 inputs) | 9/30 | 0.4933 | 0.64 | 53 | 12 |
| Primary 21-task cohort (25 inputs) | 5/25 | — | — | 51 | 11 |
| HELDOUT (20 inputs) | 1/20 | — | — | 29 | 17 |

Runtime on DEV: 347.3 s, 98,370 prompt + 15,223 completion tokens, peak GPU
memory 18,909 MiB. Matched 10-task subset: GLM 4/15 vs Direct Qwen 3/15, with
8 vs 60 false relations.

**Serving artefact, disclosed:** usable prompt budget was ~4096 tokens
because the server reserved 4096 for output; 15 of 25 DEV tasks were
truncated. Per-task flags are in `results/MACE_direct_GLM_v2_1_per_task.csv`.

## 6. HELDOUT evaluation

The four prediction files were frozen, hashed, and only then scored with an
independent scorer (`scripts/score_heldout_v2_1.py`, v1.1). Scorer v1.0 had a
method-alias defect; only v1.1 numbers are used.

| Method | Strict exact | False | Unmatched | Stray |
|---|---|---|---|---|
| C0 | 7/20 | 8 | 3 | 3 |
| Full MACE | 12/20 | 5 | 2 | 4 |
| Direct Qwen | 4/20 | 74 | 40 | 63 |
| Direct GLM | 1/20 | 29 | 17 | 21 |

Exact McNemar p-values: Full vs C0 0.0625; Full vs Direct Qwen 0.0078; Full vs
Direct GLM 0.0010; C0 vs Direct Qwen 0.25; C0 vs Direct GLM 0.0703; Direct
Qwen vs Direct GLM 0.375. Only the two comparisons against the Direct LLM
baselines are significant at 0.05.

MMBS is not scored: no frozen method emits MMBS predictions, so the value is
`N/A`, not zero.

## 7. Historical / exploratory runs (not in the main table)

These runs informed the design but are not the v2.1 evaluation:

- M1–M6 contract-engine studies on hand-written fixtures (`m5/`, `m6/`,
  `docs/M1_report.md`, `docs/M5_diagnosis.md`, `docs/M6_decision.md`).
- M5/M6 used `qwen2.5-coder:32b`; the `m5/*.tgz` archives contain their
  per-call traces.
- Qwen semantic feedback v1 (`runs/v3_semantic_feedback_v1/`) tested whether
  model-written summaries improve candidate discovery: 0 new correct relations
  and 0/10 successful repairs. It is retained as a negative result.
- The earlier paper draft `docs/MACE_paper_draft_final.md` reports a negative
  result on 11 exploratory programs and is superseded by the v2.1 benchmark.

## 8. What was never run

- No recorded run used a hosted API model (GPT, Claude, Gemini or DashScope);
  every reported run went through local Ollama.
- No 7B run on MACE-Bench v2.1.
- No MMBS prediction by any method.
- No multi-seed or multi-model variance study on v2.1.
- No human evaluation of model rationales.
