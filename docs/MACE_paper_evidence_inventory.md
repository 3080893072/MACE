# MACE paper evidence inventory

- Date: 2026-11-03
- Repository: `<local-path>`
- Purpose: separate what the repository actually establishes from what a paper
  might be tempted to claim.
- **Task separation is mandatory.** The numbers below belong to three different
  tasks and must never be put in one comparison column:
  - **G1 (Guard task)** — one marked assignment `A`, predict the input condition
    under which deleting `A` leaves all returned channels unchanged.
  - **O1 (operation-level masking)** — given an operation and a function, decide
    whether its deletion is masked or exposed under strict observation semantics
    (the `reliable_ast_v1` 1.0.1 task).
  - **R1 (fixed-proposal replay)** — the replay applies the new evidence gate to stored
    G1 bundles. It is a replay, not a new end-to-end model run.

All G1 verdicts are bounded over a declared finite domain (`BOUNDED` or
`TESTED`). The code never emits `PROVEN`.

## 0. Change boundary for this round

Preserved unchanged:

- all M1–M6 code paths and stored runs (`m1/`–`m6/`, `m5/`, `results/`);
- the frozen real benchmarks (`benchmark_real_v3/`, `benchmark_real_v4/`) and
  their evidence;
- `reliable_ast_v1/` 1.0.1;
- `mace/verify.py`, `mace/compose.py`, `mace/contracts.py`, `mace/prompts.py`,
  `mace/sandbox.py`, `mace/runner.py`.

Added or additively changed:

- `mace/evidence_gate.py` (new, importable independently);
- `mace/loop.py`: new `evidence_gate: bool = False` parameter, default off;
  when off, every branch is byte-for-byte behaviorally identical to before;
- `mace/cli.py`: new `--evidence-gate` flag, default off;
- `tests/test_evidence_gate.py` (10 new tests);
- `scripts/m7_evidence_gate.py` (fixed-proposal replay, no model calls);
- `evidence_gate/replay.json`, `evidence_gate/replay.md` (new results);
- this inventory and `docs/MACE_paper_draft.md`.

No historical result file was edited. The M1–M6 freeze hashes in
`m6/freeze_manifest.json` still describe the frozen pre-replay files; the replay files are
outside that manifest and are identified here explicitly.

---

## 1. Algorithm modules that can be described in the paper

### 1.1 G1 task definition (implemented)

Input:

- a deterministic Python program `P` with one assignment marked `# TARGET_A`;
- an entry function and its argument sorts;
- a declared finite input domain `D` (all 11 paper fixtures are exhaustive);
- the number of returned channels `K`.

Let `P+ = P` and `P- = P` with the marked assignment replaced by `pass`. For
`x in D`, let `O+(x)` and `O-(x)` be the returned tuples. The mask predicate is

```
M(x) = 1  iff  O+(x) = O-(x)
```

The Guard task asks for a Boolean expression `g` over the entry arguments such
that `g(x) = M(x)` for every `x in D`. This is a bounded equality, not a proof
over all inputs.

### 1.2 Typed contract language (implemented, `mace/terms.py`, `mace/contracts.py`)

- Sorts: `bool`, `int`, `list[int]`, `dict[int,int]`.
- Operators: arithmetic, comparisons, Boolean connectives, conditional
  expressions, indexing, and a fixed set of builtins (`len`, `min`, `max`,
  `sum`, `abs`, `sorted`, `vals`, `distinct`, `count`) plus declared program
  functions.
- There is no Python `eval` of model output; expressions are parsed into a
  typed AST and evaluated by the checker.
- Scope separation is enforced:
  - `target_effects`: entry arguments, pre-`A` locals under plain names, and
    post-`A` locals under `<name>_post`;
  - `upstream`: entry arguments only;
  - `observers`: entry arguments and post-`A` locals under plain names;
  - `mask_guard`: entry arguments only.

### 1.3 Contract bundle (implemented, `mace/contracts.py`)

Four groups:

- `target_effects`: what `A` changes in the local state;
- `upstream`: input facts, each with role `fixed_point` (the condition makes `A`
  a no-op) or `supporting` (explains downstream insensitivity);
- `observers`: one expression per output channel plus the condition under which
  that channel cannot change;
- `mask_guard`: the final Boolean guard.

`parse_bundle` rejects malformed bundles, requires all four groups, and requires
at least one target effect unless the bundle is guard-only.

### 1.4 Bounded dual-version verification (implemented, `mace/verify.py`)

For each usable input the checker executes both versions (`run_pair`) and
evaluates, in the appropriate scope:

1. **Target effect**: under its condition, the stated post-state relation holds.
2. **Upstream fact**: under its condition, the stated input fact holds.
3. **Fixed-point implication**: under the fixed-point condition, the pre- and
   post-`A` local snapshots are equal. A failure demotes the relation to
   `REFUTED` even if the input fact itself was true.
4. **Observer two-sided faithfulness**: the observer expression must equal the
   actual channel value in **both** `P+` and `P-` (not only `P+`).
5. **Observer invariance**: under the observer condition, the observed values in
   `P+` and `P-` must agree.
6. **Guard**: predicted accept/reject versus real `M(x)`; counts `unsound`
   (accepts a case where outputs differ) and `incomplete` (rejects a case where
   outputs agree).
7. **Observer soundness**: states with equal observation vectors must have equal
   real outputs (`collision` count).
8. **Composition**: the deterministic composer is evaluated and re-checked.
9. **Behaviour classes**: `local_inactive`, `active_masked`, `active_exposed`.

Status vocabulary: `BOUNDED` (exhaustive declared domain), `TESTED` (sampled),
`REFUTED`, `INVALID`, `UNKNOWN`. `PROVEN` is not produced anywhere.

### 1.5 Deterministic composer (implemented, `mace/compose.py`)

```
guard = (OR over verified fixed-point conditions)
        OR
        (AND over channels of (OR over that channel's verified observer conditions))
```

Only relations whose verifier status is `BOUNDED` or `TESTED` contribute. If a
channel has no verified observer, the composer returns `INCOMPLETE` with
`expr = None` rather than dropping the channel; if nothing contributes it
returns `UNKNOWN`. With human-reviewed contracts the composer reaches 9/9 exact
on the nine-fixture diagnostic (cell D, M5); this is a **diagnostic ceiling**,
not an automated result.

### 1.6 Counterexample repair loop (implemented, `mace/loop.py`)

Three rounds by default. Each round sends the model the previous bundle, the
failed relations, and concrete paired executions; the model may return a full
bundle or a patch (`revise`, `add_observers`, `mask_guard`). Parsing failures and
semantic failures are fed back. The model never sees the reference bundle,
hidden labels, or the real mask.

### 1.7 Evidence-Gated Local Relations (new in this round, `mace/evidence_gate.py`)

An additive, independently switchable layer that reads the per-relation records
already produced by the bounded checker and requires a **non-vacuous witness**:

- `WITNESS_VERIFIED`: parsed, at least one domain input satisfied the
  condition and produced a supporting observation, and no checked input
  falsified the claim. For observers, at least one condition-true row must have
  equal observations. For fixed-point upstream relations, at least one
  condition-true row must have `snap_plus == snap_minus`.
- `REFUTED`: at least one counterexample was observed.
- `UNVERIFIED`: no runnable evidence (parse/type/evaluation failure, no
  condition-true input, or no fixed-point/observer witness).

Only `WITNESS_VERIFIED` relations are admitted to the composer. The gate reuses
the checker's rows and counters, which are the `P+`/`P-` deletion-intervention
outcomes themselves: **0 extra model calls, 0 extra program executions**. It is
off by default (`--evidence-gate` turns it on), so all historical runs reproduce
exactly.

This closes a real but rare defect: `verify.py` could label a relation
`BOUNDED` with `checked == 0`, or an observer `BOUNDED` with
`invariance_checked == 0`. Across the 59 relations in the 11 stored MACE runs,
exactly **1** relation was in this state (`dedup_channel` observer `O0`).

### 1.8 Sandbox isolation (implemented, `mace/sandbox.py`, `mace/runner.py`)

- `python -I` child process, fresh empty temp working directory, scrubbed
  environment (no credentials), wall-clock timeout.
- The parent never imports or executes the untrusted program; it reads only the
  child's JSON report.
- The child uses an AST whitelist and restricted builtins (`mace/program.py`).
- This is process isolation with a whitelist, not an OS container; the code says
  so explicitly.

### 1.9 Corpus (implemented)

11 fixtures, all with exhaustive finite domains:

| fixture | split | channels | domain size | notes |
|---|---|---:|---:|---|
| `alt_masking` | dev6 | 1 | 160 | two downstream absorbers; third mode exposes |
| `dedup_channel` | dev6 | 1 | 240 | duplicate removal; empty-list boundary |
| `modulo_absorb` | dev6 | 1 | 518 | modulo clamp |
| `overwrite_channel` | dev6 | 2 | 80 | later branch overwrites `A` |
| `sort_channel` | dev6 | 2 | 10,912 | insertion sort upstream; two extrema channels |
| `swap_channels` | dev6 | 3 | 32 | channel swap |
| `dead_flag` | held1 | 2 | 40 | flag has no downstream effect |
| `dict_slot` | held1 | 2 | 80 | one dict slot overwritten; one length identity |
| `parity_snap` | held1 | 1 | 170 | parity rounding |
| `clamp_absorb` | held2 | 1 | 170 | clamp absorbs |
| `toggle_pair` | held2 | 2 | 18 | paired toggle |

**These are not a fresh independent benchmark.** They were designed, debugged,
and repaired during M2–M6; held1 was used for a parser fix and held2 was used in
M5. The paper must call them development/exploratory cases.

---

## 2. Experiments that can be reported truthfully

### 2.1 M5: 2x2 capability diagnostic (`qwen2.5-coder:32b`, seed 42, 3 rounds)

Cells A/B use the same Qwen contract; C/D use human-reviewed contracts and are
**diagnostic only**, never system scores.

| cell | contract | guard | dev6 exact | all 9 exact |
|---|---|---|---:|---:|
| A | Qwen | Qwen | 1/6 | 3/9 |
| B | Qwen | composer | 1/6 | 3/9 |
| C | reviewed | Qwen | 3/6 | 5/9 |
| D | reviewed | composer | **6/6** | **9/9** |

Interpretation that the data supports: when the contract is correct, the
composer is exact (D 9/9); the accuracy bottleneck is relation and condition
induction, not deterministic combination. A vs B shows the composer does not
raise total exactness on Qwen contracts, though it never emits an unsound guard
in cell B.

Held-out batches (from M5): held1 is semi-held-out (used during a parser fix),
held2 was genuinely unseen at the time. Every method scored **0/2** on held2;
MACE cost about 6x the direct prompt.

### 2.2 M6: frozen-code comparison on all 11 fixtures (no new model calls)

| method | exact | tokens | wall |
|---|---:|---:|---:|
| Direct Qwen (stored M5) | **5/11** | 23,626 | 102.3 s |
| Full MACE A (stored M5) | 3/11 | 141,081 | 704.5 s |
| Pure Symbolic (no helper summaries) | 7/11 (4 UNKNOWN) | 0 | 0.01 s |
| Symbolic + helper summaries | **11/11** | 0 | 0.02 s |
| Bounded induction, sufficient direction | 10/11 | 0 | 25 s |
| Bounded induction, necessary direction | 0/11 | 0 | 25 s |

Cost ratio: 5.97x tokens and 6.9x wall for Full MACE vs Direct.

Other frozen M6 results:

- Guard retention over 77 stored run slots: final-round 35/77, online
  best-validated 37/77, best-ever diagnostic ceiling 37/77. Only 2 slots
  regress, both `parity_snap`.
- Held-out condition induction (frozen tag `m6-induct-freeze`, commit
  `7599e20`): 4/5 exact vs Direct 2/5 and Full MACE 2/5 on held1+held2. It fails
  on `dead_flag` (sound but incomplete).
- The symbolic/induction gains come from program analysis and a hand-written
  predicate-template library (dev ablation: full pool 6/6, generic pool 2/6),
  **not** from LLM semantic discovery. They must not be presented as an
  LLM+MACE contribution.
- The repository contains no independent "Step 5 symbolic patch"; the M6
  symbolic engine is a new implementation on the M6 branch.

### 2.3 Evidence-gate replay: controlled evaluation (new)

Sources: `evidence_gate/replay.json`, `evidence_gate/replay.md`, produced by
`python scripts/m7_evidence_gate.py`.

Design: hold each stored M5/M6 MACE proposal and its final bounded report fixed;
compare four guard sources:

- `direct` = **A**: stored Direct Qwen guard;
- `mace` = **B**: stored Full MACE guard (Qwen-written);
- `compose` = **C−** (ablation): deterministic composer over every relation the
  original verifier accepted (gate OFF);
- `gated` = **C**: deterministic composer over `WITNESS_VERIFIED` relations only
  (gate ON).

`compose` and `gated` differ only in the gate, so their difference is the
mechanism's independent effect at fixed proposals.

| method | cases | exact | sound | incomplete | invalid | unknown | unsound |
|---|---:|---:|---:|---:|---:|---:|---:|
| Direct Qwen | 11 | **5** | 6 | 1 | 0 | 0 | 5 |
| Full MACE | 11 | 3 | 5 | 2 | 3 | 0 | 3 |
| Composer (gate OFF) | 11 | 3 | 5 | 2 | 0 | 6 | 0 |
| Evidence-gated composer | 11 | 3 | 4 | 1 | 0 | 7 | 0 |

Per-fixture outcomes:

| fixture | Direct | Full MACE | Composer OFF | Gated |
|---|---|---|---|---|
| `alt_masking` | exact | exact | exact | exact |
| `dedup_channel` | exact | invalid | incomplete | unknown |
| `modulo_absorb` | unsound | invalid | unknown | unknown |
| `overwrite_channel` | exact | unsound | unknown | unknown |
| `sort_channel` | unsound | incomplete | incomplete | incomplete |
| `swap_channels` | incomplete | unsound | unknown | unknown |
| `dead_flag` | exact | exact | exact | exact |
| `dict_slot` | exact | exact | unknown | unknown |
| `parity_snap` | unsound | unsound | exact | exact |
| `clamp_absorb` | unsound | invalid | unknown | unknown |
| `toggle_pair` | unsound | incomplete | unknown | unknown |

Gate effect at fixed proposals:

- exact guards gained by the gate: **0**;
- exact guards lost by the gate: **0**;
- relations accepted by the original verifier: 25/59;
- relations rejected by the gate: **1** (`dedup_channel` observer `O0`,
  `invariance_checked = 0`; the gate-off composer had used it). This one is
  unsupported, not refuted: refuted relations were already rejected by the
  original verifier, so the gate's marginal rejection is exactly the vacuous
  case;
- that rejection changes `dedup_channel` from a sound-but-incomplete composed
  guard (`len(xs) == 0`, 100 incomplete) to `UNKNOWN`; it does not produce a
  correct guard.

Cost: the gate adds 0 model calls, 0 tokens, and 0 program executions. The
stored Full MACE runs used 141,081 tokens and 704.5 s; Direct used 23,626 tokens
and 102.3 s. Evaluation re-checks are not part of method inference cost.

**Honest conclusion:** the evidence gate repairs a real vacuity defect but has
no independent effect on exact accuracy on these 11 cases. It must be reported
as a negative/soundness result, not as an accuracy contribution.

### 2.4 Test suite

`python -m pytest -q` passes **230 tests** after adding 10 evidence-gate tests.
Before this round it was 220. The tests are engineering checks, not a benchmark.

### 2.5 Reliable AST 1.0.1 (O1 task, separate)

Frozen result from `docs/MACE_next_stage_decision.md`:

- 5 development tasks, 36 claims, 17 credited relations, 32 builds, 120
  executions, 68.304 s wall.
- 36/36 claims `WITNESS_VERIFIED`; 0 `FALSE`, 0 `UNVERIFIED`, 0 `INVALID`,
  0 `DUPLICATE`.
- `global_relation_completeness: false`. 17/17 means every known relation in the
  five development tasks was credited, not global completeness.
- Three 1.0.1 fixes: dynamic-only event-order eligibility (no source-line
  proxy), vacuous-MSMS guard, `BROKEN_INTERVENTION` -> `UNVERIFIED`.

These numbers belong to O1. They must not be added to G1 or called Full MACE
results.

---

## 3. Not implemented or not proven

1. **No operation-level intervention wired into the Full MACE Guard loop.** The
   AST analyzer executes candidate deletions and verifies masked/exposed
   witnesses, but Full MACE's Guard loop does not call it. The interface gap is:
   Full MACE's verifier consumes one marked `A` and a fixed input domain;
   the AST analyzer consumes a candidate set derived from a function and
   returns per-operation relations. Bridging them would require a candidate
   projection and a new scoring path; this was not done.
2. **No live Qwen run with the gate ON.** The gate experiment is a fixed-proposal replay. The
   effect of feeding `UNVERIFIED` relations back to the repair loop is untested.
3. **No held-out evaluation.** All 11 fixtures were designed/used before this
   paper. Held1 is semi-held-out; held2 was unseen at M5 time but has since been
   inspected. No result here is a fresh independent test.
4. **No `PROVEN` result.** All passes are bounded over the declared finite
   domain. The 11 domains are exhaustive but finite.
5. **No generalization claim.** One model (`qwen2.5-coder:32b`), one seed (42),
   three rounds, 11 small programs. No multi-model, multi-seed, or real-project
   G1 evaluation.
6. **The gate does not improve exact accuracy.** 0 gains, 0 losses; 1 rejected
   vacuous relation; sound coverage 5 -> 4 because one sound-but-incomplete
   guard becomes `UNKNOWN`.
7. **The G1 bottleneck is upstream relation/condition induction.** 8/9 first
   failures in M5 were upstream; 3 Full MACE guards are `INVALID`; the composer
   is exact with reviewed contracts (D 9/9) but not with Qwen contracts.
8. **Non-monotone repair remains.** 5/9 A3 runs end worse than their best round;
   online retention recovers only 2/77 slots.
9. **Symbolic 11/11 is not an LLM+MACE contribution.** It uses source-level
   path enumeration plus hand-written predicate templates; the generic-pool
   ablation drops dev performance from 6/6 to 2/6.
10. **The real-code cases are O1, not G1.** `pyparsing` 3371 and `click` 2482
    were confirmed as C-class operation-level cases; they motivate the problem
    but do not enter G1 accuracy.

---

## 4. Original MACE vs AST 1.0.1

| dimension | Full MACE (G1) | Reliable AST 1.0.1 (O1) |
|---|---|---|
| Question | Under which inputs is deleting the marked `A` unobservable? | Is deleting a given operation masked or exposed, with local witnesses? |
| Unit | one marked assignment, one declared input domain, `K` channels | candidate operations derived from `P+`/`P-` traces; per-candidate relations |
| Output | typed contract bundle + one Boolean guard | per-operation `WITNESS_VERIFIED_LOCAL` / `UNVERIFIED` / statuses |
| Evidence | bounded `P+` vs `P-` execution over the declared domain; two-sided observer faithfulness; guard unsound/incomplete | dynamic event-order eligibility, strict masked/exposed sets, MSMS/MMBS, deletion-intervention execution |
| Failure semantics | `REFUTED` / `INVALID` / `UNKNOWN`; no `PROVEN` | `BROKEN_INTERVENTION` -> `UNVERIFIED`; vacuous MSMS discarded; no `PROVEN` |
| Composition | deterministic OR/AND composer over verified relations | no Boolean guard composition; relation set per operation |
| Current numbers | Direct 5/11; Full MACE 3/11; composer 3/11; gated 3/11 (G1) | 17/17 credited, 36 claims, 0 false/invalid (O1) |
| Can the numbers be compared? | **No** | **No** |

The AST analyzer was built as an independent engineering branch. It did not
modify Full MACE, the historical runs, or the frozen benchmark evidence. Its
17/17 is evidence that the operation-level relation machinery works on its five
development tasks; it is not evidence that Full MACE solves the Guard task.

---

## 5. Real source cases usable in a Motivating Example

These are O1 audit cases, not G1 benchmark items.

### 5.1 `pyparsing-3.0.9`, `pyparsing/core.py:3371`

```python
3368        self.minLen = min
3369
3370        if max > 0:
3371            self.maxLen = max          # A
3372        else:
3373            self.maxLen = _MAX_INT
3374
3375        if exact > 0:
3376            self.maxLen = exact
3377            self.minLen = exact
```

Deleting `A` is unobservable when `exact > 0`: line 3376 overwrites the attribute
before any observation. When `exact == 0` and `max > 0`, the attribute survives
and the deletion is exposed. The masking condition is therefore a property of a
**later branch on a different attribute**, not of the deleted line alone. The v4
qualification witnesses are 3 designed payloads: masked `(max=3, exact=2)` and
`(max=5, exact=3)`, exposed `(max=3, exact=0)`.
Source: `benchmark_real_v4/witnesses/pyparsing3371_white_maxlen.json`; notes in
`reliable_ast_v1/cases.py` (`pyparsing_3371_self_maxlen`).

### 5.2 `click-8.4.1`, `src/click/core.py:2482`

```python
2482            value = self.type_cast_value(ctx, value)      # A
...
2487        if self.callback is not None:
2490            if value is UNSET:
2491                value = None
2495            if not unset_keys:
2497                value = self.callback(ctx, self, value)
...
2512                    value = self.callback(ctx, self, value)
```

Deleting `A` is unobservable when the later callback returns a value that makes
the final observation independent of the cast input. The audit's designed
payloads show masked `(value="42", callback=const)` and `(value="7",
callback=const)`, exposed `(value="42", callback=echo)` and `(value="7",
callback=echo)`. The condition crosses a function boundary and depends on the
callback's behavior, which neither a local diff nor a syntax-only rule can
decide.
Source: `benchmark_real_v4/witnesses/click2482_process_value.json`; notes in
`reliable_ast_v1/cases.py` (`click_2482_callback_return`).

### 5.3 Minimal G1 illustration: `fixtures/alt_masking.py`

```python
def program(xs, mode):
    v = xs[0] if len(xs) > 0 else 0
    v = v + 1                      # TARGET_A
    if mode == 0:
        out = v * 0
    elif mode == 1:
        out = v - v
    else:
        out = v
    return out
```

Here `M(x) = (mode == 0 or mode == 1)`. The example shows why the guard needs
both a fixed-point/upstream view (the two absorbing branches) and a downstream
observer view (the surviving `v` in mode 2). It is one of the 11 exploratory
fixtures, not a held-out case.

---

## 6. Real execution flow usable as Algorithm 1

This is the actual `mace.loop.run_mode(mode="mace", guard_source="qwen")` flow,
with optional `evidence_gate=True` and `guard_source="derived"` for cell C.

```
Input: source P, target line l, finite domain D, channels K, rounds R,
       guard_source s, evidence_gate e
1.  V <- sandbox.probe_vocabulary(P, D[0])          # names + sorts only
2.  prompt <- contract_prompt(P, l, D, signatures, K, V)
3.  messages <- [system, user(prompt)]
4.  previous <- None
5.  for r = 1..R:
6.      raw <- Qwen(messages, temperature=0, seed=42)
7.      if previous != None and raw is a patch:
8.          bundle_dict <- apply_patch(previous, raw)
9.      else:
10.         bundle_dict <- raw
11.     bundle <- parse_bundle(bundle_dict)        # typed; reject malformed
12.     rows <- run_pair(P+, P-, D)                # isolated child process
13.     report <- verify_bundle(rows, bundle)      # BOUNDED/TESTED/REFUTED/INVALID/UNKNOWN
14.     if e:
15.         report <- gate_report(report)          # WITNESS_VERIFIED/REFUTED/UNVERIFIED
16.     if s == "derived":
17.         composed <- compose_guard(bundle, report_if_gate else report, K)
18.         if composed.expr is None and e:
19.             return NO_VERIFIED_COMPOSITION, report
20.         if composed.expr:
21.             bundle_dict <- replace_guard(bundle_dict, composed.expr)
22.             report <- verify_bundle(run_pair(P+, P-, D), parse(bundle_dict))
23.     store exchange(bundle_dict, report)
24.     if report.all_relations_pass and report.guard_ok:
25.         return ALL_VERIFIED, bundle_dict, report
26.     failures <- relations/guard not OK, plus gated-out relations if e
27.     messages <- messages + [assistant(raw),
                               user(repair_prompt(previous, failures,
                                                  counterexamples))]
28.     previous <- bundle_dict
29. return final bundle, final report, usage
```

Two details that matter for reproducibility:

- `run_pair` executes both versions for every case in `D`; a malformed or
  out-of-scope expression never reaches Python `eval`.
- A bounded pass is reported as `BOUNDED`/`TESTED`; the code has no path that
  returns `PROVEN`.

---

## 7. Does the new improvement have an independent effect?

**No, not on exact accuracy in the controlled replay.**

Evidence:

- `compose` (gate OFF) and `gated` (gate ON) both score 3/11 exact on the same
  stored proposals.
- The gate gains 0 exact guards and loses 0 exact guards.
- The gate rejects 1 relation (a vacuous observer) that the original verifier
  had accepted. The gate-off composer had used that relation's condition; with
  the gate, no guard is emitted for that fixture (`UNKNOWN` instead of a
  sound-but-incomplete guard).
- The gate adds no model calls and no program executions.

Scope note: the gate's only consumer is the deterministic composer. In the
original Full MACE the model writes the final guard, so a gate-annotation-only
variant with that guard is output-identical to B (3/11). C is therefore defined
as the gated composer, the minimal configuration in which the mechanism can
affect the output.

What the gate does establish:

- an explicit three-way evidence taxonomy (`WITNESS_VERIFIED`, `REFUTED`,
  `UNVERIFIED`) instead of treating a `BOUNDED` status with zero checked rows as
  support;
- a mechanical rule that an unverified candidate cannot enter the deterministic
  composition;
- a switchable ablation (`--evidence-gate`, default off) with unchanged
  historical behavior.

What it does not establish:

- that evidence gating improves Guard accuracy;
- that it helps the repair loop in a live run (untested);
- that a bounded witness is a proof.

If the paper reports the new mechanism, it must report this as a negative result
and as a soundness/accountability refinement, not as an accuracy gain.

---

## 8. Claims that cannot be made

Do not write any of the following:

1. "Full MACE outperforms Direct Qwen." It does not: 3/11 vs 5/11.
2. "MACE is more token-efficient." It uses 5.97x the tokens (141,081 vs 23,626).
3. "The evidence gate improves accuracy / solves the bottleneck." It gains 0
   exact guards.
4. "Full MACE proves / guarantees masking." Only bounded domain results exist;
   `PROVEN` is never emitted.
5. "The 11 fixtures are a held-out benchmark." They were developed and inspected
   during M2–M6; held2 was only unseen at M5 time.
6. "The AST 1.0.1 17/17 is a Full MACE result." It is a separate operation-level
   task.
7. "The symbolic 11/11 is an LLM+MACE contribution." It is program analysis plus
   hand-written templates; the generic-pool ablation is 2/6 on dev.
8. "MACE generalizes to real projects." The real-code cases (`pyparsing`,
   `click`) are O1 audit cases; G1 was not run on real projects.
9. "The method finds all masked operations / is complete." The AST analyzer
   explicitly records `global_relation_completeness: false`; the G1 domains are
   finite.
10. "Human-reviewed contracts are the system." Cells C/D are diagnostic ceilings,
    not automated results.

---

## 9. Reproduction commands and artifacts

```bash
cd <local-path>

# Full test suite (230 tests)
python -m pytest -q

# M6 frozen comparison table (no model calls)
python scripts/m6_symbolic.py

# evidence-gate controlled replay (no model calls)
python scripts/m7_evidence_gate.py

# AST 1.0.1 regression (O1 task, separate)
python -m reliable_ast_v1.regress
```

Key artifacts:

- `m5/` — stored Qwen runs used by M5/M6 and the replay (not modified).
- `m6/symbolic.json`, `m6/symbolic.md` — M6 symbolic comparison.
- `evidence_gate/replay.json`, `evidence_gate/replay.md` — the replay.
- `reliable_ast_v1/runs/regression.json` — AST 1.0.1 regression.
- `docs/M5_diagnosis.md`, `docs/M6_decision.md`,
  `docs/MACE_next_stage_decision.md` — prior analyses.
- `docs/FREEZE_MANIFEST.md`, `m6/freeze_manifest.json` — M1–M6 freeze hashes
  (the replay additions are outside that freeze).

All reported numbers above come from these stored logs or from the replay run
performed on 2026-11-03. None are estimated.
