# Reproducibility Guide

This guide separates three activities that are often conflated:

1. **Auditing the paper numbers** against the frozen artifacts shipped here
   (CPU only, minutes).
2. **Re-running the scoring** from frozen predictions (CPU only, seconds).
3. **Re-running a method** end to end (needs per-project virtual environments,
   downloaded sdists, and a local model server).

Only (1) and (2) are expected to reproduce bit-for-bit. (3) is a re-execution;
LLM sampling, library versions and timing can differ.

## 1. Environment

| Component | Requirement |
|---|---|
| Python | 3.10+ (reported runs: 3.11, Windows) |
| Runtime dependencies | none (standard library only) |
| Test dependency | `pytest>=7.4` |
| Method re-runs | one virtual environment per benchmark project + Ollama |
| GPU | only for method re-runs (reported: RTX 4090 D, 24 GB) |
| Credentials | none; no hosted API key is used |

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -e ".[test]"
```

## 2. Audit frozen artifacts (CPU, ~30 s)

```bash
python reproduction/verify_frozen.py
```

Checks performed:

- 5 frozen result files against `results/MACE_v2_1_frozen_config.json`;
- 4 frozen HELDOUT prediction files against the hashes in the official scores;
- 12 frozen code/protocol files, with the 4 path-portability edits reported as
  `[EDIT]`;
- 50 task directories: id match, declared-input/reference agreement, and every
  `acceptance.json` passing.

Expected result: `RESULT: PASS (portability edits exempted)`. Use
`--strict` to fail on the four edits; the old and new hashes are in
`reproduction/portability_patch.json`.

### Why four code files differ

The reported runs used an absolute repository path and Windows virtual
environments under `<local-path>`. Those strings were replaced with
`mace/paths.py` resolution (environment variables, then repository-relative
defaults, then a temporary directory). No prompt, search rule, scorer or
dataset file changed. All result and prediction hashes are unchanged.

## 3. Re-run the official scoring (CPU, seconds)

```bash
MACE_SCORE_OUT=runs/local_scores python scripts/score_heldout_v2_1.py
```

Reads the four frozen prediction files plus the HELDOUT references and
recomputes every score, the paired McNemar tests and the subset tables.
`MACE_SCORE_OUT` keeps the frozen `results/` files untouched.

Verified outcome on this repository: the recomputed `methods`, `pairwise` and
`per_input` blocks are identical to the frozen file; only the recorded absolute
`dataset_root` string differs.

## 4. Model-free smoke checks

```bash
mace smoke --fixture sort_channel.json     # prints SMOKE: PASS
pytest                                      # 391 tests
```

Verified outcome on this repository:

| Check | Result |
|---|---|
| `import mace, mace.paths` | OK, version 0.2.0 |
| `mace smoke --fixture sort_channel.json` | `SMOKE: PASS` |
| `pytest -q` | 391 passed, exit 0 |
| Import of the five pipeline scripts | OK |
| `python reproduction/verify_frozen.py` | PASS |
| Scoring re-run | identical scientific values |
| Public export (`export_public.py`), then `verify_frozen.py` + `pytest` inside it | PASS; 390 passed, 1 skipped (HELDOUT absent by design) |
| Fresh `git clone` of this repository, then `verify_frozen.py` + `pytest` | PASS; 391 passed (`.gitattributes` disables EOL conversion) |

## 5. Re-running a method

### 5.1 Upstream sources

```bash
python reproduction/fetch_sdists.py            # 23 projects used by v2.1
python reproduction/fetch_sdists.py --all      # all 70 discovery projects
```

Downloads each pinned sdist, verifies size and SHA-256, and extracts it to
`benchmark_v4_dataset/discovery/sources/<slug>/`. If you keep a shared cache,
set `MACE_SDIST_CACHE`; archives are copied into the repository layout
afterwards.

### 5.2 Per-project virtual environments

```bash
python benchmark_v4_dataset/tools/stage23_run.py env attrs-23.2.0
```

Creates `<MACE_VENVS>/<slug>`, installs `pytest==7.4.0` and the project in
editable mode, then records `pip freeze`. The default `MACE_VENVS` is
`<MACE_WORK>/venvs`; set both to control placement:

```bash
export MACE_WORK=/data/mace_scratch
export MACE_VENVS=/data/mace_scratch/venvs
export MACE_PYTHON=$(which python3.11)
```

The probe runner resolves `Scripts/python.exe` on Windows and `bin/python`
elsewhere. No project is imported into the controller process.

### 5.3 C0 and Full MACE

```bash
MACE_RUN_DIR=runs/local_dev \
MACE_DEV_OUT=results/local_dev.json \
python scripts/run_candidate_discovery_v2_1.py --tasks sd_attrs_asdict_loop_m7
```

- Without `--tasks`, the script runs its built-in 21-task DEV list.
- With `MACE_RUN_DIR` unset it would write into the historical run directory;
  always set it when re-running, so the frozen traces are preserved.
- `--dry-run` builds the AST catalogue and performs the pre-trace without
  calling the model. It still needs the per-project virtual environment.

C0 is produced inside the same run; there is no separate C0-only entry point
for v2.1. The frozen C0 predictions are available if you only want to score.

### 5.4 Direct LLM baselines

```bash
MACE_RUN_DIR=runs/local_qwen python scripts/run_direct_qwen_v2_1.py
MACE_RUN_DIR=runs/local_glm  python scripts/run_direct_glm_v2_1.py
```

Both scripts talk to Ollama at `http://127.0.0.1:11434`. To use another host,
edit the `ENDPOINT` constant or tunnel the port; the model names are constants
at the top of each script and in `configs/llm_backends.json`.

### 5.5 Model service

```bash
ollama serve
ollama pull qwen2.5-coder:32b
ollama pull glm-4.7-flash:q4_K_M
```

The reported runs used one model at a time, `OLLAMA_NUM_PARALLEL=1`,
`OLLAMA_MAX_LOADED_MODELS=1`, `KEEP_ALIVE=-1`. A 24 GB GPU is sufficient for
the 32B Q4_K_M model used here.

## 6. Rerun vs audit: what to expect

| Activity | Deterministic? | Needs GPU? | Needs network? |
|---|---|---|---|
| Frozen hash audit | yes | no | no |
| Dataset structural check | yes | no | no |
| HELDOUT scoring from frozen predictions | yes | no | no |
| Task acceptance (`sd_acceptance.py`) | yes | no | yes (sdist download) |
| C0 / Full MACE re-run | no (LLM sampling, timing) | yes | model endpoint |
| Direct LLM re-run | no | yes | model endpoint |

A re-run that produces different numbers does **not** license changing the
frozen results. Report the difference; do not overwrite.

## 7. Known non-determinism and defects

- **Prompt truncation at 4098 tokens.** Both Direct baselines declare
  `num_ctx=8192`, but the serving stack reserved 4096 for output. Affected
  tasks are flagged in the per-task CSVs. This is disclosed, not corrected.
- **Scorer v1.0 alias defect.** An early scorer compared against `"Full"`
  while predictions were labelled `"Full MACE"`, producing 0/20. Only v1.1
  results are used. The defect is recorded in the official scoring report.
- **`__pycache__` staleness.** Probes run with `-I` (which implies `-E`, so
  `PYTHONDONTWRITEBYTECODE` is ignored). The dataset tools delete `__pycache__`
  before each probe; do not remove that step.
- **Line endings.** v2.1 normalises delivered files to LF so that delivered
  and enumerated hashes agree. Editing dataset files with a CRLF editor will
  break acceptance.

## 8. What cannot be reproduced from this repository alone

- The 7B per-call traces (only aggregate tables survive; see
  `EXPERIMENTS.md`).
- The exact GPU timing and memory readings.
- Any result that depended on the original absolute path or the original
  virtual environments.
- HELDOUT scores under a different prediction set; the frozen predictions are
  the only ones scored.
