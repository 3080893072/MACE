# MACE — Masking-Aware Counterfactual Exploration

MACE is an LLM-guided, source-grounded framework for discovering and verifying
minimal masking explanations through executable counterfactual interventions.

Given a program operation `A` whose deletion leaves observable behaviour
unchanged, MACE answers a precise question: **which other operations, kept or
deleted, explain that invariance — and can the explanation be executed and
checked for minimality?**

This repository contains the MACE engine, the MACE-Bench v2.1 benchmark, the
Graph/AST-only baseline (C0), the LLM-guided Full MACE pipeline, the Direct LLM
baselines, the frozen predictions and scores reported in the paper, and the
scripts needed to audit or re-run each stage.

---

## Project Overview

A *masking relation* is a set of operations `S` in a program `P` such that
deleting `A` and also deleting everything outside `S` leaves the observable
behaviour identical to deleting `A` alone. Such a relation matters for program
comprehension: it says which upstream computations actually matter for the
effect of `A`, and which are absorbed by downstream state.

MACE treats the discovery of these relations as a search problem over
**executable** interventions, not as a text-similarity or explanation-ranking
problem:

1. **Graph/AST-only baseline (C0).** A deterministic static analysis proposes a
   candidate universe `U_graph` from the target function and its reachable
   same-file context.
2. **LLM-guided expansion (Full MACE).** A local language model proposes
   additional operations `U_qwen`, which are grounded back to real AST
   statements. The union `U_union = U_graph ∪ U_qwen` retains provenance, and
   nothing from `U_graph` is removed.
3. **Bounded executable search.** For every declared input, MACE deletes
   candidate subsets in an isolated copy of the project and observes the
   program, under a fixed operation budget.
4. **Strict minimality verification.** A kept set is accepted only if it is
   non-empty, sufficient (`obs(S) == obs(P+)`), and minimal. The result is
   reported as MSMS; the dual breaking sets are reported as MMBS only when the
   deletion baseline is separable.

The LLM is a **candidate generator**, never an oracle. Every candidate is
mapped to an executable statement and every claimed relation is re-executed and
re-checked. Verdicts are bounded: the verifier can return `BOUNDED`, `TESTED`,
`REFUTED`, `UNKNOWN` or `INVALID`; it never emits `PROVEN`.

## Motivation

Existing LLM-based program-explanation work typically asks a model to describe
why a line matters and then evaluates the description as text. That protocol
cannot distinguish a plausible explanation from a correct one, and it cannot
express *sets* of operations whose joint deletion is what preserves behaviour.

MACE instead fixes a falsifiable target: a declarative masking relation over a
finite, declared input domain, verified by execution. This makes three things
possible that text-based evaluation cannot offer:

- **Executable ground truth.** Every relation is checked by running the
  program, not by comparing rationales.
- **Set-valued explanations.** Cooperative mechanisms (two or three operations
  masking each other) are representable and scorable.
- **Honest negative results.** A model that proposes nothing useful scores
  zero, and an incomplete search is reported as `SEARCH_INCOMPLETE` instead of
  being silently counted as a failure of the method.

## Methodology

**Problem setting.** A task fixes a source file, a target operation `A`
(identified by file, line and code text), a legal input API, and a finite set
of declared inputs. The input roles (`masking`, `exposing`, `control`,
`negative_control`) are hidden from every method and used only by the scorer.

**Candidate universe.** C0 derives `U_graph` with AST discovery plus a
role-separated graph search (`benchmark_v3_baselines/`). Full MACE adds `U_qwen`
from a frozen prompt and maps each proposal to an AST statement with a
line-exact grounding step; proposals that cannot be grounded are dropped and
counted.

**Bounded search.** Each input has a budget of 16 subset executions and the
candidate universe is capped at 6 operations after ranking. Executions happen
in throwaway copies of the project inside the per-project virtual environment,
with bytecode writing disabled and a fixed hash seed.

**Verification.** For each masking input MACE computes minimal non-empty
sufficient kept sets (MSMS). When the deletion baseline `P−` and the original
`P+` are separable it also computes minimal breaking disabled sets (MMBS);
otherwise the input is marked `NOT_SEPARABLE` and MMBS is not scored. Empty
kept sets suppress non-empty MSMS and are never reported as minimal sets.

**What the method does not do.** There is no cross-view attention, no learned
scorer, and no claim that the model "understands" the program. The only
model-dependent step is candidate proposal. See [Limitations](#limitations).

## Repository Structure

```
.
├── mace/                        # core engine: terms, contracts, verifier, composer,
│                                # sandbox runner, Qwen client, CLI, path resolution
├── scripts/                     # experiment entry points (see below)
├── tests/                       # 391 unit/integration tests (pytest)
├── fixtures/                    # small hand-written programs used by the core tests
├── benchmark_v3_baselines/      # C0: AST discovery, subgraph, graph search
├── benchmark_v4_dataset/        # MACE-Bench v2.1 (see DATASET.md)
│   ├── source_derived_v2_1/     # 25 DEV + 25 HELDOUT tasks, cases, probes, evidence
│   ├── tools/                   # dataset construction, acceptance, execution harness
│   ├── discovery/               # pinned sdist registry + screening metadata
│   └── PROTOCOL.md              # acceptance criteria (AC1–AC12) and relation definitions
├── configs/                     # frozen run config, LLM backend parameters
├── results/                     # frozen results (see results/*/README.md)
│   ├── dev/                     # DEV aggregate tables
│   ├── heldout/                 # HELDOUT scores and comparisons
│   └── paper/                   # paper-number provenance and status matrix
├── runs/                        # raw per-call traces for the reported runs
├── docs/                        # experiment reports and audit notes
│   └── legacy/                  # superseded READMEs, kept for provenance
├── reproduction/                # frozen-artifact audit, sdist fetch, export helpers
├── README.md
├── DATASET.md
├── EXPERIMENTS.md
├── REPRODUCIBILITY.md
├── THIRD_PARTY_LICENSES.md
├── CITATION.cff
├── LICENSE
└── pyproject.toml
```

`benchmark_v4_dataset/source_derived_v2_1` is the MACE-Bench v2.1 release; the
directory name is kept for compatibility with the scripts that produced the
reported numbers. Earlier `benchmark_*` directories are historical generations
retained for the record; nothing in the paper depends on them.
`mace_qwen_pilot.py` and `mace_semantic_core_poc.py` at the repository root are
the original single-file pilots. No engine module, test or experiment script
imports them; they are kept so the early reports in `docs/legacy/` stay
traceable.

## Installation

The engine and all experiment scripts use the Python standard library only.
Python 3.10+ is required; the reported runs used Python 3.11 on Windows.

```bash
git clone <repository-url> MACE
cd MACE
python -m venv .venv
# Windows: .venv\Scripts\activate
source .venv/bin/activate
pip install -e ".[test]"
```

Verify the installation without a model:

```bash
mace smoke --fixture sort_channel.json
pytest
```

`mace smoke` runs the bundled fixture through the verifier and prints
`SMOKE: PASS`. The test suite covers terms, contracts, the verifier, guard
composition, the sandbox runner, the graph baselines and the dataset
protocol.

## Dataset

MACE-Bench v2.1 is in `benchmark_v4_dataset/source_derived_v2_1/`:

| Split | Tasks | Projects | Mechanisms |
|---|---|---|---|
| DEV | 25 | 10 | M1–M9 |
| HELDOUT | 25 | 17 | M1–M9 plus 5 M10 negative controls |

Every task is a `SOURCE_DERIVED_CONTROLLED` construction from a real upstream
sdist: a researcher patch inserts operations `U`, the target `A` is replaced by
`pass  # P-: target A deleted`, and line numbers are preserved. Each task
directory contains `task.json`, `reference.json`, `patch.diff`,
`provenance.json` and `acceptance.json`; the task's declared inputs, probes and
enumeration evidence live alongside.

Full field descriptions, the MSMS/MMBS definitions, the DEV/HELDOUT split
policy and the known project/template overlap are documented in
[DATASET.md](DATASET.md). The dataset license and upstream redistribution
conditions are in [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md).

## Quick Start

```bash
# 1. Model-free sanity check
mace smoke --fixture sort_channel.json

# 2. Full test suite
pytest

# 3. Audit every frozen artifact in this repository
python reproduction/verify_frozen.py
```

The audit checks the five frozen result files, the four frozen HELDOUT
prediction files, the twelve frozen code/protocol files and the structural
integrity of all 50 tasks. Four code files were edited for path portability
only and are reported as `[EDIT]`; `--strict` fails on them instead. See
`reproduction/portability_patch.json` for the old and new hashes.

## Reproducing Experiments

The complete procedure, including prerequisite virtual environments and the
commands for each method, is in [REPRODUCIBILITY.md](REPRODUCIBILITY.md). In
short:

```bash
# 0. Upstream sources (pinned by URL + SHA-256; not redistributed here)
python reproduction/fetch_sdists.py

# 1. One virtual environment per project slug
python benchmark_v4_dataset/tools/stage23_run.py env attrs-23.2.0

# 2. Graph/AST-only baseline and Full MACE over DEV
MACE_RUN_DIR=runs/local_dev MACE_DEV_OUT=results/local_dev.json \
  python scripts/run_candidate_discovery_v2_1.py --tasks sd_attrs_asdict_loop_m7

# 3. Direct LLM baselines
MACE_RUN_DIR=runs/local_qwen \
  python scripts/run_direct_qwen_v2_1.py
MACE_RUN_DIR=runs/local_glm \
  python scripts/run_direct_glm_v2_1.py

# 4. Score HELDOUT predictions without touching the frozen files
MACE_SCORE_OUT=runs/local_scores python scripts/score_heldout_v2_1.py
```

Environment variables:

| Variable | Meaning | Default |
|---|---|---|
| `MACE_WORK` | scratch root for probe workspaces | `<temp>/mace` |
| `MACE_VENVS` | per-project virtual environments | `<MACE_WORK>/venvs` |
| `MACE_PYTHON` | interpreter used to create a missing venv | current interpreter |
| `MACE_RUN_DIR` | output directory for a run | the historical `runs/<name>` |
| `MACE_DEV_OUT` | DEV result JSON written by the Full MACE runner | historical path |
| `MACE_SCORE_OUT` | where the HELDOUT scorer writes | `results/` |

## LLM Backends

Model identity is an implementation detail and appears only in
`configs/llm_backends.json` and the experiment scripts. The reported runs used:

| Backend | Role | Decoding |
|---|---|---|
| `qwen2.5-coder:32b` (Q4_K_M, digest `b92d6a0b…`) | Full MACE candidate discovery; Direct Qwen baseline | temperature 0, seed 42, `num_ctx` 16384 (discovery) / 8192 (direct), `num_predict` 4096 |
| `glm-4.7-flash:q4_K_M` | Direct GLM baseline | temperature 0, seed 42, `num_ctx` 8192 |
| `qwen2.5-coder:7b` (Q4_K_M, 7.6B) | Historical fixture-level study only | temperature 0, seed 42, `num_ctx` 8192, JSON mode |

All reported backends were served by Ollama over an SSH tunnel to a single
RTX 4090 D. `mace/qwen.py` also carries a DashScope transport, but the reported
runs used the Ollama chat API only.

**Qwen 7B status.** The 7B experiments were completed on the historical
six-fixture set and are reported in `results/summary_7b.md` (guard accuracy was
0/6 in every mode). No per-call raw trace for that batch survives in the
repository, and no v2.1 strict-MSMS run was performed with 7B. The 7B numbers
are therefore reported as aggregate only and are not used in the main table.
Concretely: the 7B study is an early M1-pilot guard check on six hand-written
fixtures (`dedup_channel`, `sort_channel`, `swap_channels`, `alt_masking`,
`modulo_absorb`, `overwrite_channel`) in four modes. It is **not** a MACE-Bench
v2.1 Full MACE run, it has no strict-MSMS score, and it must not be quoted as
the 7B counterpart of the 32B result. The v2.1 comparison is C0, Full MACE with
32B, Direct Qwen 32B and Direct GLM only.

## Evaluation Metrics

- **Strict exact (MSMS).** The predicted family of minimal sufficient sets must
  equal the reference family exactly, after block projection. This is the main
  metric.
- **Present / coverage.** The prediction is non-empty.
- **False relations.** Predicted sets that are not in the reference family.
- **Unmatched sets.** Predicted sets that cannot be projected to the block
  vocabulary.
- **Stray operations.** Operations outside the task's declared candidate
  universe.
- **Micro precision / recall.** Computed over predicted relations.
- **MMBS.** Reported only for separable inputs; no reported method emits MMBS
  predictions, so it is `N/A` rather than zero.
- **Paired tests.** Exact McNemar on per-input strict exact outcomes.

`UNKNOWN` is never counted as `FALSE`. An incomplete search is reported as
`SEARCH_INCOMPLETE` and excluded from the accuracy denominator.

## Reproduction Status

Not every reported number is reproducible in the same way. This table is the
authoritative statement of what is shipped and what can be checked.

| Result | Shipped in the public artifact | What can be done with it |
|---|---|---|
| DEV dataset (25 tasks) | yes: tasks, patches, probes, reference relations, acceptance reports | audit `verify_frozen.py`; rebuild with `fetch_sdists.py`; re-run C0/Full MACE end to end (GPU + Ollama + per-project venvs) |
| DEV frozen run (C0, Full MACE, Direct Qwen, Direct GLM) | yes: DEV predictions, per-task tables, raw traces in `runs/` | recompute every DEV number from the CSVs; re-run the methods, accepting sampling and timing differences |
| HELDOUT dataset (25 tasks, 20 masking inputs) | **no**: withheld from the public export | release only after the split is public (`--keep-heldout`); until then the HELDOUT numbers in the paper can only be audited in the full private artifact |
| HELDOUT scores (four methods, McNemar tests) | **no**: HELDOUT-derived tables are withheld, because per-input rows carry the hidden input roles | same as above |
| Qwen 7B study | yes, aggregate only: `results/summary_7b.md`, `docs/M1_report.md` | read the reported aggregate; not re-runnable and not part of the v2.1 comparison |
| Historical benchmark generations | yes, for provenance | not used by any paper number |

Consequently, `reproduction/verify_frozen.py` checks the five DEV result files
and the twelve frozen code/protocol files in every export, and checks the four
HELDOUT prediction files plus the HELDOUT split only when they are present. In
a public export it prints `[SKIP]` for those instead of failing.

## Reproducing Paper Results

The numbers below are copied from the frozen files named in the last column.
The complete cell-by-cell mapping, including which values are derived rather
than read directly, is `results/paper/MACE_paper_numbers_provenance.csv`.

**DEV, primary cohort (21 tasks, 25 masking inputs after the v2.1 role fix):**

| Method | Strict exact | False rel. | Unmatched | Source |
|---|---|---|---|---|
| C0 (Graph/AST only) | 13/25 | 9 | — | `results/dev/MACE_v2_1_dev_final.json` |
| Full MACE + Qwen 32B | 18/25 | 5 | 2 | `results/dev/MACE_v2_1_dev_final.json` |
| Direct GLM | 5/25 | 51 | 11 | `results/MACE_direct_GLM_v2_1_config.json` |
| Direct Qwen 32B | 2/25 | 110 | 55 | `results/MACE_direct_Qwen_v2_1_DEV_completed.json` |

Full MACE executed 276 probes in 747.53 s and used 145,939 prompt /
11,288 completion tokens on this cohort. Paired task outcomes versus C0 are
6 better, 14 equal, 1 worse.

The as-run record has 27 masking inputs under the legacy role definition
(C0 14, Full 19). That block is preserved in
`results/MACE_v2_1_frozen_config.json` and must not be quoted as the paper
denominator.

**HELDOUT (20 masking inputs, 20 tasks).** These values are read from
`results/MACE_HELDOUT_v2_1_official_scores.json` and `results/heldout/`, which
are **withheld from the public export** until the split is released. The table
is reproduced here so the paper's claims are readable; it is not auditable from
the public package alone.

| Method | Strict exact | False rel. | Unmatched | Stray |
|---|---|---|---|---|
| C0 | 7/20 (35.0%) | 8 | 3 | 3 |
| Full MACE | 12/20 (60.0%) | 5 | 2 | 4 |
| Direct Qwen 32B | 4/20 (20.0%) | 74 | 40 | 63 |
| Direct GLM | 1/20 (5.0%) | 29 | 17 | 21 |

Exact McNemar: Full vs C0 p = 0.0625 (not significant); Full vs Direct Qwen
p = 0.0078; Full vs Direct GLM p = 0.0010. Project-disjoint subset: Full
10/17; template-disjoint: Full 8/16; both-disjoint: Full 7/14. These subsets
are descriptive, not powered tests.

To reproduce the scoring rather than trust it:

```bash
MACE_SCORE_OUT=runs/local_scores python scripts/score_heldout_v2_1.py
```

The recomputed `methods`, `pairwise` and `per_input` blocks are identical to
the frozen ones; only the recorded absolute dataset path differs.

## Limitations

- **Finite declared domains.** A relation is verified over the inputs the task
  declares, not over all program inputs. `BOUNDED` does not mean universally
  true.
- **Small candidate universes.** v2.1 tasks have 1–3 candidates per input by
  construction, so the benchmark measures grounding and verification more than
  large-scale candidate ranking.
- **Single model, single seed.** The main table uses one 32B model, one
  quantization, temperature 0 and seed 42. No variance across seeds or models
  is reported.
- **HELDOUT overlap.** 6 of 25 HELDOUT tasks share a project with DEV and 9
  share a construction template; no task is novel in both mechanism and
  template. Generalization claims must use the disclosed subsets.
- **MMBS is unscored.** No reported method emits MMBS predictions, so the
  breaking-set side of the relation is defined but not evaluated.
- **No multimodal or cross-view component.** Depth and semantic masks, where
  present in the wider project, are derived from the same RGB input and are not
  part of MACE.
- **LLM role is narrow.** The model proposes candidate operations; it does not
  write the final relation, and its rationales are not evaluated.

## Citation

```bibtex
@software{mace2026,
  title  = {MACE: Masking-Aware Counterfactual Exploration with Executable Verification},
  author = {{MACE Authors}},
  year   = {2026},
  note   = {MACE-Bench v2.1; ICPC 2027 submission},
  url    = {https://github.com/<owner>/MACE}
}
```

`CITATION.cff` carries the same metadata in Citation File Format. The author
field is intentionally anonymous until the review process ends.

## License

The MACE code, benchmark definitions, patches, probes and documentation are
released under the MIT License (see [LICENSE](LICENSE) and [NOTICE](NOTICE)).
Upstream projects that MACE-Bench tasks are derived from remain under their own
licenses. The public package **redistributes no upstream source code**: the
single-file `original/` and `patched/` copies kept in the private repository are
excluded by default, and upstream sources are downloaded from their pinned
sdists instead. [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md) lists every
project, its license and the conditions that apply if those files are ever
included with `--with-evidence`.
