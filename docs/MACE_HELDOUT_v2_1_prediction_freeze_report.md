# MACE-Bench v2.1 — HELDOUT Blind Prediction Freeze Report

Generated: 2026-11-05T14:20Z  
Dataset: `benchmark_v4_dataset/source_derived_v2_1/heldout` (formal v2.1)  
Status: **predictions frozen, NOT scored**. No HELDOUT `reference.json`, private
acceptance, or hidden MSMS/MMBS was read by any predictor. No HELDOUT accuracy
was computed.

## 1. Answers to the five required questions

1. **How many tasks did each new method complete?**
   - C0: **25/25** tasks executed, 25/25 status `OK`.
   - Full MACE + Qwen: **25/25** tasks executed, 25/25 status `OK`, 25 Qwen
     candidate-discovery calls (exactly one per task, no retries).
   - Direct Qwen 32B: **25/25** tasks executed (one call each, no retries);
     **15/25** tasks produced at least one mappable relation set, the other 10
     are `INVALID_OUTPUT` (9 model answers whose every operation was rejected by
     the frozen mapper, 1 HTTP 5xx with no retry — see §5).
2. **Was hidden ground truth accessed?** **No.** The prediction runner was bound
   to a whitelisted public-only copy (`runs/heldout_public_only`, 125 files,
   202 non-public entries refused) and carried a runtime audit hook that aborts
   on any open of `heldout/tasks`, `heldout/acceptance`, `heldout/seal`,
   `enumeration*`, `reference.json`, or the legacy `source_derived/heldout`
   tree. Both Window A prediction files record `guard.violations = []`. Static
   AST audit found no `reference_for` / `_prepare_baseline` / `block_spans` /
   `score_sets` call and no hidden-path literal; the guard self-test blocked all
   four deliberate probe reads. Direct Qwen used the frozen DEV runner, whose
   HELDOUT branch reads only `heldout/cases/` and
   `heldout/evidence/<cid>/patched/`.
3. **Did the new runner use only formal v2.1 paths?** **Yes.** Hard assertions
   require `.../source_derived_v2_1/heldout`; every probe is remapped to
   `heldout/probes/<cid>.py`; no fallback to `source_derived` exists. The DEV
   runner source is unchanged: its SHA-256 (`3e73ac49…adddd8`) equals
   `results/MACE_v2_1_frozen_config.json → file_sha256.runner`; the executor,
   AST-discovery and graph-search cores also match their frozen hashes.
4. **Which tasks had parse / execution / context issues?** See §5. Summary:
   - execution: `sd_multidict_version_m6` (3/3 inputs: the A-deletion side probe
     cannot run),
   - parse/mapping: 9 Direct Qwen tasks + 1 transport failure,
   - context: 12/25 Direct Qwen prompts hit the serving cap at 4098 tokens
     (same artefact as DEV); Full MACE prompts never exceeded 10725 tokens
     against `num_ctx=16384`, all `done_reason=stop`.
5. **Overall freeze status:** all four prediction sets are complete and hashed;
   the frozen Direct GLM hash is unchanged; the six preconditions for unified
   blind scoring in §7 are met. Scoring was not started and must not start until
   the unsealing step is authorised.

## 2. Frozen prediction files

| Method | Tasks | Tasks with ≥1 set | Inputs (declared) | Predicted sets | File | SHA-256 | Bytes |
|---|---|---|---|---|---|---|---|
| C0 (Graph/AST baseline) | 25/25 | 12 | 70 | 26 | `results/MACE_HELDOUT_v2_1_C0_predictions.json` | `ecc55c7ac10bc5e302d69ae31b7b5439f0847c983eb1dbe39d1fe72bae40d28d` | 74,302 |
| Full MACE + Qwen | 25/25 | 14 | 70 | 38 | `results/MACE_HELDOUT_v2_1_Full_predictions.json` | `056e6565f0eed7f3e8057ddd0a5550299e42ccb14e0ba7065a25dbd5756ee478` | 1,729,493 |
| Direct Qwen 32B | 25/25 executed, 15 with output | 15 | 70 | 15 (task-level) | `results/MACE_HELDOUT_v2_1_Direct_Qwen_predictions.json` | `0d216443dc35ca404c5f508e312d1a501dc4b124eedec82f578eeac40dd2476e` | 1,074,355 |
| Direct GLM 4.7-flash (frozen, not rerun) | 25/25 | 11 | 70 | 11 (task-level) | `results/MACE_direct_GLM_v2_1_heldout_predictions.json` | `b18154766089fd849515f485bbdb279dd47b336c48fd3d1d4f70f2f1a052597f` | 1,015,397 |

- C0/Full predictions are **per input** (`predictions[<input_key>]`); Direct
  methods are **task-level** relation sets applied to every input, exactly as in
  the DEV protocol.
- C0 stores `predicted_kept_sets`, Full stores `predicted_sets`; both reference
  operation ids of the form `<file>:<first_line>-<last_line>`, with the full op
  dicts retained in `universe` (C0) / `u_union` (Full), so block projection at
  scoring time needs no hidden data.
- Every prediction was produced with the frozen algorithm: same
  `discover` → `rank_and_prune` → role-separated search (`budget=16`) and strict
  minimality verifier; `MAX_OPS=6`; UNKNOWN ≠ FALSE; no behaviour change.

## 3. Windows, runtime and cost

| Window | Start (UTC) | End (UTC) | Elapsed | Hard limit | Result |
|---|---|---|---|---|---|
| A — precheck + C0 + Full | 2026-11-05T13:35:54Z | 2026-11-05T14:00:34Z | 1480 s (24 m 40 s) | 2700 s | 25/25 + 25/25 |
| B — Direct Qwen | 2026-11-05T14:00:43Z | 2026-11-05T14:17:00Z | 977 s (16 m 17 s) | 2700 s | 25/25 executed |

| Method | Wall clock | Probe executions | Prompt tokens | Completion tokens | Model options |
|---|---|---|---|---|---|
| C0 | 39.4 s (sum of per-task algorithm time) | 152 | — | — | deterministic |
| Full MACE | 1437.9 s (sum) / 1440.2 s process | 234 | 134,205 | 11,334 | temp 0, seed 42, num_ctx 16384, num_predict 4096, retries 0 |
| Direct Qwen | 954.0 s (sum of calls) | — | 96,272 | 16,442 | temp 0, seed 42, num_ctx 8192, num_predict 4096, retries 0 |
| Direct GLM (frozen) | 325.1 s | — | 102,377 | 14,025 | temp 0, seed 42, num_ctx 8192, num_predict 4096, retries 0, `think=false` |

Model: `qwen2.5-coder:32b`, Ollama digest
`b92d6a0bd47ee79114298de0177bf920c05a706d12633950b3936778492bef41` (verified
against `/api/tags` immediately before Window A and unchanged for Window B).

Window A was **restarted once** at 13:35:54Z after the two compatibility fixes
in §4.1. The earlier attempt had produced C0 results for 14 tasks and had not
started Full MACE; those 14 records were never frozen, never used, and were
discarded and recomputed by the identical algorithm. Task order (the frozen
25-task list, alphabetical by case id) was preserved, and the 45-minute budget
was applied to the restarted window.

Freeze timing: the C0 file was final at 13:36:33Z and the Full file at
14:00:34Z, both before Window B started at 14:00:43Z. Their SHA-256 values were
computed after Window B launched and re-verified unchanged at the end; Window A
artifacts were therefore immutable throughout Window B.

## 4. Isolation design and integrity

- `scripts/build_heldout_public_only.py` copied an explicit whitelist — `cases/*.json`,
  `evidence/<cid>/patched/*`, `evidence/<cid>/original/*`,
  `evidence/<cid>/patch.diff`, `probes/*.py` — into `runs/heldout_public_only`
  (125 files: 25 cases, 50 evidence sources, 25 patch diffs, 25 probes) and
  refused 202 entries (`tasks/`, `acceptance/`, `seal/`, `enumeration*.json`).
  `public_subset_flags.json` is the only seal-derived artefact: per-case
  disjointness booleans, with no roles, counts or answers.
- `scripts/run_heldout_v2_1_blind.py` binds `HELDOUT`, asserts its parent is
  `source_derived_v2_1`, remaps every probe to the v2.1 probes directory, and
  installs a `sys.addaudithook` that hard-fails on any forbidden path.
- `scripts/check_heldout_blind_static.py`: forbidden calls — none; hidden-path
  literals — none; path-binding assertions — present; guard self-test — 4/4
  blocked (`reference.json`, `acceptance/<cid>.json`, `enumeration.json`,
  legacy probe path). Result: `results/MACE_HELDOUT_v2_1_blind_static_check.json`.
- `scripts/check_heldout_v2_1_integrity.py` (run outside the predictor; computes
  SHA-256 only, exposes no hidden content):
  - 25/25 case files match `seal → sha256.case`;
  - 25/25 `evidence/<cid>/enumeration.json` match `seal → sha256.enumeration_json`;
  - 25/25 `tasks/<cid>/reference.json` match `seal → sha256.reference_json`;
  - 125/125 copied public files are byte-identical to the formal tree;
  - 25/25 `evidence/<cid>/original/*` hashes equal the corresponding
    `discovery/sources/<root>/<file>` upstream source (source unchanged);
  - 25/25 `patch.diff` applied to `original/*` reproduces `patched/*`
    byte-for-byte (`patch -p1`, checked in a temp copy);
  - 25/25 declared legacy probe paths remap to an existing v2.1 probe with
    identical basename; legacy and v2.1 probe bytes differ only by CRLF→LF,
    content identical after newline normalisation.
  Result: `results/MACE_HELDOUT_v2_1_integrity_precheck.json` (`all_ok=true`).

### 4.1 Two HELDOUT path/compatibility fixes (no algorithmic change)

1. **Top-level module projects** (`base.file` has no `/`, only
   `sd_pycodestyle_paths_nc` → `pycodestyle.py`). `SDExecutor` sets
   `top = rel.split("/")[0]`, which is a *file* for such cases, so the variant
   tree could not be linked. The blind runner links the whole project root
   (`top="."`) when `root/top` is not a directory. Scope: **1/25 tasks**;
   recorded as `top_remap` in that task's record. No algorithm, prompt, graph,
   budget or verifier change.
2. **Read-only hardlink replacement** (Windows). The upstream tree contains
   read-only files; replacing the hardlinked variant target raised
   `WinError 5`. `BlindExecutor` chmods only that single target writable before
   unlinking. Scope: any variant build; no file-content or behaviour change,
   and all probe/source hashes in §4 are unchanged.

Both fixes live only in the new HELDOUT runner; `scripts/run_candidate_discovery_v2_1.py`
and the shared harness were not modified (hashes match the frozen config).

## 5. Errors, incomplete work and anomalies

**Incomplete tasks: none.** All 25 tasks ran in every method; nothing was
zero-filled or guessed. Deadline branches were never triggered.

Execution issue (C0 + Full):

- `sd_multidict_version_m6`, all 3 inputs: the **A-deletion side** probe exits
  non-zero (`__probe_error__`), i.e. deleting A prevents execution. The frozen
  gate requires an observable plus/minus comparison, so no prediction is
  emitted for these inputs. They are not recorded as FALSE. (The plus side runs
  normally; this is a genuine property of the task, not a harness fault.)

Parse/mapping or transport issues (Direct Qwen):

| Task | Status | Cause |
|---|---|---|
| `sd_jedi_param_hyphen_m2` | INVALID_OUTPUT | 3 relations parsed, all ops rejected by frozen mapper |
| `sd_passlib_hashname_m2` | INVALID_OUTPUT | 12 parsed, all rejected |
| `sd_pycodestyle_paths_nc` | INVALID_OUTPUT | 12 parsed, all rejected |
| `sd_pyyaml_int_underscore_m3` | INVALID_OUTPUT | 3 parsed, all rejected |
| `sd_requests_contenttype_m7` | INVALID_OUTPUT | 1 parsed, rejected |
| `sd_simplejson_htmlamp_m4` | INVALID_OUTPUT | 12 parsed, all rejected |
| `sd_sqlparse_normalized_m5` | INVALID_OUTPUT | 5 parsed, all rejected |
| `sd_toml_quote_escape_m4` | INVALID_OUTPUT | 3 parsed, all rejected |
| `sd_urllib3_headerdict_m6` | INVALID_OUTPUT | 1 parsed, rejected |
| `sd_toml_quote_nc` | INVALID_OUTPUT | HTTP 5xx; one attempt, no retry, empty response |

Direct GLM (frozen) has the same protocol shape: 11 `OK`, 14 `INVALID_OUTPUT`.

Context:

- Direct Qwen: **12/25** prompts were served with exactly 4098 prompt tokens,
  i.e. above the serving budget and truncated (jedi, jsonschema_pointer_m4,
  jsonschema_pointer_nc, parso, passlib_hashname, passlib_name, pycodestyle,
  pyyaml, requests_contenttype, simplejson_decoder, simplejson_htmlamp,
  sqlparse_normalized). This is the same serving artefact already disclosed for
  DEV; the declared protocol remains `num_ctx=8192`, no prompt was changed.
  The runner's `context_truncated_suspected` flag (`pt ≥ 8184`) is therefore
  false-negative for this cap and should not be used as the truncation record.
- Direct GLM (frozen): 10/25 prompts hit the same 4098 cap.
- Full MACE: prompt tokens ranged 2,344–10,725 (< 16,384); 25/25
  `done_reason=stop`; no truncation.
- C0/Full search completeness: **0** inputs with `SEARCH_INCOMPLETE`; every
  reported set passed the strict minimality verifier.

## 6. Stratification (official subset flags, prediction counts only)

Units are tasks; declared inputs are public (`inputs` length). Masking-input
counts are unknown until unsealing and are deliberately not estimated.

| Subset | Tasks | Declared inputs | C0 tasks | Full tasks | Qwen tasks | GLM tasks |
|---|---|---|---|---|---|---|
| Full | 25 | 70 | 25 | 25 | 25 | 25 |
| Project-disjoint | 19 | 55 | 19 | 19 | 19 | 19 |
| Template-disjoint | 16 | 48 | 16 | 16 | 16 | 16 |
| Both-disjoint | 14 | 42 | 14 | 14 | 14 | 14 |

Subsets were not re-selected after seeing any truth; they come from the official
seal flags.

## 7. Preconditions for unified blind scoring

- [x] C0 25/25, Full MACE 25/25, Direct Qwen 25/25 executed; GLM frozen 25/25.
- [x] Same formal v2.1 HELDOUT task set for all four methods (25 task ids
      identical across files).
- [x] Frozen Direct GLM SHA-256 unchanged:
      `b18154766089fd849515f485bbdb279dd47b336c48fd3d1d4f70f2f1a052597f`.
- [x] All four prediction files hashed and recorded in
      `results/MACE_HELDOUT_v2_1_freeze_manifest.json`.
- [x] No hidden-truth access during prediction (static + runtime + integrity
      audits).
- [x] No scoring executed, no accuracy computed, no unsealing.
- [ ] Unsealing authorisation for the scoring round (out of scope here).

Consequence for the scoring round: Direct Qwen's 10 `INVALID_OUTPUT` tasks have
no predicted set and will be scored by the frozen rule (empty prediction), not
imputed; the `sd_multidict_version_m6` inputs likewise carry no C0/Full
prediction. These are honest zeros, not missing data.

## 8. Artefacts

- `results/MACE_HELDOUT_v2_1_C0_predictions.json`
- `results/MACE_HELDOUT_v2_1_Full_predictions.json`
- `results/MACE_HELDOUT_v2_1_Direct_Qwen_predictions.json`
- `results/MACE_HELDOUT_v2_1_freeze_manifest.json`
- `results/MACE_HELDOUT_v2_1_execution_status.csv`
- `results/MACE_HELDOUT_v2_1_blind_static_check.json`
- `results/MACE_HELDOUT_v2_1_integrity_precheck.json`
- runners: `scripts/build_heldout_public_only.py`,
  `scripts/run_heldout_v2_1_blind.py`,
  `scripts/check_heldout_blind_static.py`,
  `scripts/check_heldout_v2_1_integrity.py`,
  `scripts/build_heldout_v2_1_freeze.py`
- raw: `runs/heldout_v2_1_blind/` (Window A log, 25 Full raw responses with
  prompt SHA-256), `runs/direct_qwen_v2_1/heldout/` (25 Direct Qwen raw
  records), `runs/heldout_public_only/` (whitelisted public workspace).
