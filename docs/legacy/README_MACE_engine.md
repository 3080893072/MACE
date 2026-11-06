# MACE — Masking-Aware Contract Engine (research prototype)

Given a program `P`, one marked assignment `A`, and a declared finite input
domain, MACE asks a local Qwen model to synthesize **typed, source-grounded
semantic contracts** about `A`, verifies every relation with a bounded checker,
feeds concrete counterexamples back, and derives the conditions under which
deleting `A` is unobservable.

The scientific claim under test (not assumed):

> Synthesizing *observation-relevant* relations on demand, relative to the
> actual state difference induced by `A`, explains conditional and joint masking
> more accurately than generic function summaries or direct LLM reasoning.

**Current status: the claim is not supported at 32B, and M6 recommends STOP on
Full MACE as the main algorithmic contribution.** A post-M6 feasibility audit on
ten real open-source functions is in
[`docs/next_research_decision.md`](docs/next_research_decision.md) (primary
verdict: NO-GO for a general negative-result paper on the current data; Direct
and Full MACE were not run there). See
[`docs/M6_decision.md`](docs/M6_decision.md) for the decision, the symbolic
comparison, and the frozen held-out induction run;
[`docs/M5_diagnosis.md`](docs/M5_diagnosis.md) for the stage-by-stage failure
analysis, the 2×2 diagnostic, and the held-out results. Earlier milestone
reports: [`docs/M1_report.md`](docs/M1_report.md) (hardware, model, pilot) and
[`docs/M2_M4_report.md`](docs/M2_M4_report.md) (engine, propagation, unseen
fixtures, baselines, and the counterexample-feedback ablation).

## Evaluation status of the eleven fixtures

The 11 fixtures in [`fixtures/`](fixtures/) and [`experiments/`](experiments/)
are **development and exploratory research cases**, not a fresh independent
evaluation set. They were designed, debugged, and in several cases repaired
while developing the engine from M2 through M6 (the two held-out batches were
used for M5 and then replayed in M6). Results on them are bounded, exploratory
evidence; no claim here treats them as an untouched benchmark. The ten
real-project cases in [`realcases/`](realcases/) are a pilot collected for the
research-feasibility review, not an independent benchmark either.

## Measured results (M5, `qwen2.5-coder:32b`, seed 42)

Exact = bounded-domain equality with the true mask. All verdicts are `BOUNDED`;
`PROVEN` is never emitted.

| method | dev 6 | all 9 | held-out batch 1 (3) | held-out batch 2 (2) | tokens (9) | model s (9) |
|---|---|---|---|---|---|---|
| MACE A (Qwen contract + Qwen guard) | 1/6 | 3/9 | 2/3 | 0/2 | 99,802 | 542 |
| MACE B (Qwen contract + composer) | 1/6 | 3/9 | 2/3 | 0/2 | 99,802 | 542 |
| direct guard prompt, 3 rounds | 3/6 | 5/9 | 2/3 | 0/2 | 17,566 | 81 |
| fixed guard template, 3 rounds | 2/6 | 4/9 | 2/3 | 0/2 | 20,245 | 85 |
| generic masking prompt, 3 rounds | 1/6 | 3/9 | 2/3 | 0/2 | 24,697 | 186 |
| direct guard prompt, 12 rounds | 3/6 | 5/9 | — | — | 137,009 | 323 |

Held-out batch 1 (`dead_flag`, `dict_slot`, `parity_snap`) was used while
diagnosing a parser bug, so it is only *semi*-held-out. Batch 2
(`clamp_absorb`, `toggle_pair`) was never used before its evaluation; **every
method scores 0/2 there**, and MACE costs about 6× the direct prompt.

## M6 results (frozen code, no new model calls)

All 11 fixtures, same bounded checker (`BOUNDED`, never `PROVEN`). Full detail
in [`docs/M6_decision.md`](docs/M6_decision.md); logs in `m6/`.

| method | exact | tokens | wall |
|---|---|---|---|
| Direct Qwen (stored M5 runs) | 5/11 | 23,626 | 102 s |
| Full MACE A (stored M5 runs) | 3/11 | 141,081 | 705 s |
| Pure Symbolic (no helper summaries) | 7/11 (4 UNKNOWN) | 0 | 0.01 s |
| Symbolic + helper summaries | **11/11** | 0 | 0.02 s |
| Bounded condition induction, sufficient direction | **10/11** | 0 | 25 s |
| Bounded condition induction, necessary direction | 0/11 | 0 | 25 s |

* **Guard retention (phase 2):** replaying 77 stored runs, last-write-wins
  scores 35/77 exact and online retention 37/77. Only two runs regress
  (`parity_snap`, reproduced twice); the fix reaches the best-ever ceiling of
  37/77 but cannot recover upstream failures.
* **Held-out induction (phase 4):** frozen at tag `m6-induct-freeze`
  (`7599e20`), run once on held1+held2: 4/5 exact vs Direct Qwen 2/5 and Full
  MACE 2/5. It fails on `dead_flag` (sound but incomplete: all witnesses are
  positive, so the learner cannot generalize to `True`). The necessary
  direction overfits on every set.
* **Attribution:** the symbolic/induction gains are program analysis plus a
  hand-written predicate-template library (dev ablation: full pool 6/6,
  generic pool 2/6), not LLM semantic discovery. They must not be reported as
  an LLM+MACE contribution.
* **No independent "Step 5" symbolic patch exists in this repository**; the M6
  symbolic engine is a new implementation on the `m6` branch.

The 2×2 diagnostic (cells C/D use human-reviewed contracts and are **never**
system scores):

| cell | contract | guard | dev 6 exact | all 9 exact |
|---|---|---|---|---|
| A | Qwen | Qwen | 1/6 | 3/9 |
| B | Qwen | deterministic composer | 1/6 | 3/9 |
| C | reviewed | Qwen | 3/6 | 5/9 |
| D | reviewed | deterministic composer | 6/6 | 9/9 |

The composer is exact whenever the contract is correct (D) and never emits an
unsound guard on a Qwen contract (B). The accuracy bottleneck is relation and
condition induction; the secondary defect is a non-monotone repair loop that
throws away a correct intermediate guard (5/9 A3 runs end worse than their best
round; `parity_snap` goes exact → unsound).

Historical M1–M4 table over the original six fixtures
(`results/summary_{7b,14b,32b}.md`, 4 rounds in that run, so not directly
comparable to M5's 3-round numbers):

| model | direct | generic | fixed relations | full MACE |
|---|---|---|---|---|
| qwen2.5-coder:7b | 0/6 | 0/6 | 0/6 | 0/6 |
| qwen2.5-coder:14b | 1/6 | 1/6 | 2/6 | 1/6 |
| qwen2.5-coder:32b | 2/6 | 1/6 | 2/6 | 2/6 |

## What exists today

| Milestone | State |
|---|---|
| M1 real Qwen pilot | done on an RTX 4090 D with `qwen2.5-coder:7b` / `:14b`; `docs/M1_report.md` |
| M2 semantic contract engine | typed language, contract schema, bounded verifier, counterexample repair |
| M3 composition and attribution | fixed-point + per-channel invariance composition, proof DAG, trace differencing, contrast attribution, guard blame |
| M4 end-to-end unseen cases | `sort_channel`, `dedup_channel`, `swap_channels`, plus a name-neutral control |
| M5 diagnosis | stage decomposition, 2×2 (`cells`), independent held-out batches, token-matched baseline; `docs/M5_diagnosis.md` |

## Architecture

```
mace/terms.py      typed expression language (parse -> infer -> interpret, no eval)
mace/program.py    # TARGET_A -> P+/P-, subset whitelist, instrumented execution
mace/domain.py     exhaustive / sampled finite domains
mace/contracts.py  JSON contract schema (target_effects, upstream, observers, mask_guard)
mace/verify.py     per-field scopes, two-sided observer faithfulness, guard, composition
mace/compose.py    deterministic guard from verified fixed points + observer conditions
mace/cells.py      2x2 diagnostic (re-verifies stored bundles; no model calls)
mace/diagnose.py   first failing stage, INVALID-vs-semantic split, best-round view
mace/sandbox.py    parent driver: isolated child process, scrubbed env, timeout
mace/runner.py     child entry point (the only place program code is compiled)
mace/qwen.py       Ollama / DashScope client with full call logging
mace/prompts.py    contract, repair, baseline, and oracle-guard prompts
mace/loop.py       counterexample-guided loop, patch application, run artifacts
mace/cli.py        smoke / analyze / run / report / summarize / diagnose / cells / trace
```

### Verification obligations

1. **Observer soundness** — two states with the same observation must not be
   distinguished by the real downstream program (domain grouped by observation,
   collisions checked).
2. **Observer faithfulness, two-sided** — each observer expression must equal the
   real channel value on the states after `A` in **both** P+ and P−. Checking only
   P+ let a model restate the outcome instead of describing the computation.
3. **Target invariance per channel** — under the stated condition, the observed
   channel value is unchanged by `A`.
4. **Guard** — the Boolean condition must match the real paired executions
   (soundness = no false accept, completeness = no false reject).
5. **Upstream fixed point** — a `role=fixed_point` condition must imply
   `snap_plus == snap_minus`, i.e. `A` really is a no-op there; otherwise it is
   demoted and excluded from composition.

### Per-field variable scopes

| field | in scope |
|---|---|
| `target_effects` | entry arguments, plain locals before `A`, `<name>_post` after `A` |
| `upstream` | entry arguments only |
| `observers` | entry arguments, post-`A` snapshot under **plain** names |
| `mask_guard` | entry arguments only |

Out-of-scope names produce a specific INVALID reason (`_post` only in
target_effects; entry arguments only), and the model is told which vocabulary the
field has. The real final output is never an input to a guard or an observer
condition.

Every relation gets an evidence state: `BOUNDED` (exhaustive finite domain),
`TESTED` (sampled domain), `REFUTED` (counterexample found), `UNKNOWN` /
`INVALID` (outside the supported language). `PROVEN` is never emitted: there is
no proof procedure over infinite domains in this prototype.

### Attribution: three separate levels

1. **Participates in the contract** — `attribution.proof_dag`: the guard is an
   OR over verified fixed-point conditions and an AND over per-channel observer
   conditions, with each relation's `source_lines`. Masking is never found by
   enumerating subsets of source operations.
2. **Actually stopped the difference, on this input** — `mace.cli trace` diffs
   the P+/P− execution traces line by line and reports `absorbed`.
3. **Causally necessary under a contrast** — `attribution.contrast` groups the
   domain by all-but-one argument and counts real execution pairs where the
   masked/unmasked verdict flips.

Level 3 also feeds repair: `guard.contrasts` carries minimal pairs per argument,
and `guard.blame` charges each wrong verdict to the top-level subterm responsible.

**Caveat:** the cross-run `attribution` column in the 2×2 counts whether a
relation's cited lines intersect the reviewed contract's lines. That is source
overlap, not logical support.

### Safety model

Untrusted program code runs only in a child process started with `-I`, a fresh
empty working directory, a scrubbed environment (no API keys), a wall-clock
timeout, an AST whitelist (no imports, no dunder, whitelisted methods and
builtins) and a restricted `__builtins__`. Model output is parsed by the typed
term language; no model-provided text is ever `eval`'d. This is process
isolation, not an OS sandbox: use a container for real repositories.

## Setup (Linux GPU host)

```bash
curl -fsSL https://ollama.com/install.sh | sh      # needs zstd installed
export OLLAMA_MODELS=/root/autodl-tmp/ollama_models
OLLAMA_HOST=127.0.0.1 nohup ollama serve > /root/ollama.log 2>&1 &   # localhost only
ollama pull qwen2.5-coder:32b
ollama ps          # must show 100% GPU
python -m pytest -q
```

## Commands

```bash
# CPU self-check: verifies the hidden reference bundle through the sandbox
python -m mace.cli smoke

# Verify any contract file offline
python -m mace.cli analyze --fixture sort_channel.json --bundle my_bundle.json

# Real Qwen experiment: direct, generic, fixed-relations, full MACE
python -m mace.cli run --fixture sort_channel.json \
    --provider ollama --model qwen2.5-coder:32b --mode all --rounds 3 --seed 42

# B: same contract, deterministic guard instead of the model's guard
python -m mace.cli run --fixture sort_channel.json --mode mace \
    --guard-source derived --rounds 3 --out runs/sort_B

# C/D diagnostic ceiling (reviewed contract; NOT a system score)
python -m mace.cli run --fixture sort_channel.json --mode oracle \
    --contract experiments/hidden/sort_channel_reference.json --rounds 3

# Diff the two versions' execution traces on one input
python -m mace.cli trace --fixture sort_channel.json \
    --args '{"xs": [0, -1], "pre": false, "use_left": true, "use_right": true}'

# Trace the exposed witnesses of a bundle instead of a chosen input
python -m mace.cli trace --fixture sort_channel.json --limit 2

# Summarize a run directory
python -m mace.cli report --dir runs/<run>

# Cross-run table: guard soundness/completeness, round 1 -> final, token cost
python -m mace.cli summarize --runs runs/<run-a> runs/<run-b> --json summary.json

# Stage decomposition: where did each run first fail?
python -m mace.cli diagnose --runs runs/<run-a> --json diag.json --stages

# 2x2 table from stored runs (no model calls)
python -m mace.cli cells --runs runs/<run-a> --json cells.json
```

M5 reproducers:

```bash
python scripts/m5_report.py m5/A3 m5/H2 m5/base m5/T   # final vs best round
python scripts/m5_tables.py m5/tables.md               # aggregate tables
bash scripts/run_m5_rerun.sh                           # A3, H2, H3 (AutoDL)
bash scripts/run_m5_baselines_dev.sh                   # baselines on 9 fixtures
```

Run artifacts (`runs/<fixture>_<model>_<stamp>/`):

* `config.json` — fixture config, model identity, `ollama ps`, seed, rounds;
  `diagnostic_only: true` for oracle runs
* `events.jsonl` — every model call and every verification, with timings
* `<mode>_seed<seed>.json` — full exchanges (raw responses, parsed bundles,
  per-relation verdicts, counterexamples), token counts, witnesses
* `summary.json` — one row per mode

## Hidden references

`experiments/hidden/*_reference.json` contains human-written contracts used
**only** for CPU self-checks, scoring, and the C/D diagnostic ceiling. They are
never placed in an automated prompt; the contract prompt reads only
`experiments/*.json`, `fixtures/`, and the declared domain/signatures. The
oracle mode that does consume them sets `diagnostic_only` in the run config.

## Fixtures

| fixture | masking mechanism | reference guard |
|---|---|---|
| `alt_masking` | two absorbing branches | `mode == 0 or mode == 1` |
| `dead_flag` | unconditionally overwritten flag (held-out) | `True` |
| `dedup_channel` | appended duplicate absorbed by dedup | `count(xs, xs[0] + 1) > 0` |
| `dict_slot` | later branch overwrites one slot (held-out) | `mode` |
| `modulo_absorb` | rounding to ten absorbs `+1` | `cap and fn_0(xs) % 10 != 9` |
| `overwrite_channel` | branch recomputes the value | `keep or fn_0(xs) == 0` |
| `parity_snap` | even rounding absorbs `+1` (held-out) | `even and sum(xs) % 2 == 0` |
| `sort_channel` | upstream sort + downstream extremum fold | `pre or ((use_left or xs[0]==min(xs)) and (use_right or xs[-1]==max(xs)))` |
| `sort_channel_neutral` | same, flags renamed `flag_*` (name-priming control) | same as `sort_channel` |
| `swap_channels` | cross-field compensation + gated gap | `not show_gap or n == k` |
| `clamp_absorb` | clamp to 10 absorbs `+1` (held-out batch 2) | `cap and sum(xs) >= 10` |
| `toggle_pair` | branch restores the value (held-out batch 2) | `flag or n == 0` |

## Known limitations

* Bounded checking only: the domain is finite and explicitly declared; no
  `PROVEN` over infinite domains.
* One target per file; `A` must be a simple assignment, not inside a loop.
* Term language covers bool/int/list[int]/dict[int,int]; other sorts are rejected
  as `UNKNOWN`. `min`/`max` accept a list or two integers.
* Attribution is line-level overlap, not semantic support.
* M5 evidence comes from a single model, single seed, 6+3+2 fixtures, and
  temperature 0; treat rankings as indicative. Held-out batch 1 was used while
  diagnosing the parser bug and is not clean; batch 2 is the only fully
  independent set.
* Cells C/D inject the reviewed contract into the prompt and are diagnostic
  ceilings only — never report them as system accuracy.
* The M5 repair loop is non-monotone: it can replace a correct guard with a
  worse later one. `mace/loop.py` keeps last-write-wins; the M6 replay in
  `scripts/m6_repair.py` implements `OnlineRetention`, which keeps a fit-exact
  incumbent until a counterexample revokes it. It recovers 2/77 stored runs,
  so it is a correctness fix, not an accuracy contribution.
