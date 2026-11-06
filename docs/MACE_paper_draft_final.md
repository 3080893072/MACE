# MACE: Bounded Verification of Masking Contracts for Conditional Assignment Deletion

*Final evidence-consistency version — 2026-11-03. Every number below is either
taken from a stored log in this repository or explicitly labelled as a local,
non-frozen measurement. This paper reports a negative result for the LLM
relation-proposal path and does not claim an accuracy advantage. The companion
document `docs/MACE_claim_evidence_audit.md` lists, claim by claim, what is
implemented, what is experimentally supported, and what remains unproven.*

---

## Abstract

Deleting an assignment is safe only when every later observation is insensitive
to it. In real code this condition is often an input predicate: a later branch
overwrites the assigned name, a downstream operation absorbs the value, or a
callback replaces it. We present MACE, a contract-based analyzer that asks a
language model for typed semantic relations about the marked assignment, checks
every relation with paired executions of the original and deleted versions over
a declared finite input domain, feeds concrete counterexamples back, and
composes a mask guard deterministically. We add **Evidence-Gated Local
Relations**, which admits a relation to composition only when the bounded
checker has a non-vacuous supporting witness, and which distinguishes
`WITNESS_VERIFIED`, `REFUTED`, and `UNVERIFIED` instead of treating every
`BOUNDED` label as support.

On eleven exploratory programs with exhaustive finite domains and
Qwen2.5-Coder-32B, Direct Qwen produces 5/11 exact guards, Full MACE 3/11, the
deterministic composer 3/11, and the evidence-gated composer 3/11. The gate
rejects one unsupported relation and changes one sound-but-incomplete guard to
`UNKNOWN`; it gains zero exact guards and loses zero. With human-reviewed
contracts the same composer is exact on 9/9 diagnostic cases (the six `dev6`
programs plus the three `held1` programs), which localizes the bottleneck in
upstream relation and condition induction rather than in composition. A
Direct-First policy, evaluated offline with both proposals held fixed, reaches
6/11 by keeping an exact Direct guard and otherwise using the composer over
stored MACE relations; it gains one case, loses none, costs 4.66x the Direct
tokens, and is not an online algorithm result. On the same eleven programs a
purely symbolic engine reaches 7/11 without model calls, and a symbolic engine
with human-written helper summaries reaches 11/11. MACE's value in this study is
not accuracy: it is a bounded, auditable contract interface, a composer that
emitted no unsound guard on these model-written contracts, and an explicit
account of what the model did and did not establish. **The evidence does not
support the claim that a new MACE variant outperforms a strong direct-prompting
baseline.**

---

## 1. Introduction

A compiler's dead-store elimination asks whether a write can ever be observed.
In straight-line code the answer is a liveness question. In real Python
functions it is often a *conditional* question: the write is observed on some
inputs and overwritten, absorbed, or cancelled on others. The condition depends
on values computed far from the deleted line, sometimes across a function
boundary.

Two open-source examples motivate the problem. In `pyparsing`'s `White.__init__`,
the assignment `self.maxLen = max` is overwritten by `self.maxLen = exact`
whenever `exact > 0`, so deleting the first write is unobservable exactly on
that branch condition; when `exact == 0` and `max > 0`, the first write survives
and the deletion is exposed. In `click`'s `Parameter.process_value`, the
assignment `value = self.type_cast_value(ctx, value)` is later replaced by
`value = self.callback(ctx, self, value)`; whether the deletion is observable
depends on what the callback returns. Neither case can be decided by looking at
the deleted line alone, and the second cannot be decided without reasoning about
a callee.

A natural response is to ask a language model for the condition. The model can
read the whole function, recognize the overwrite, and propose a Boolean guard.
But an unverified guard is not an analysis result. It may be unsound (accept an
input where the two versions differ), incomplete (reject an input where they
agree), or simply unparseable. The model can also produce a plausible narrative
that never becomes a checkable claim.

MACE takes the position that the model should propose *relations*, not final
truths. The analyzer gives the model a typed relation language, checks every
proposed relation against real paired executions over a declared finite domain,
returns counterexamples, and composes a guard from the relations that survived.
Nothing is called a proof; a pass is `BOUNDED` over the declared domain or
`TESTED` over a sample.

This paper makes six contributions:

1. **A typed contract language and bounded verifier.** Relations are scoped
   (pre-state, post-state, inputs, observers), type-checked, and evaluated by a
   checker rather than Python `eval`. The verifier separates target effects,
   upstream facts with a fixed-point implication, two-sided observer
   faithfulness, observer invariance, guard soundness, observer soundness, and
   behaviour classes.
2. **A deterministic composer with explicit incompleteness.** The guard is an OR
   of verified fixed-point conditions and an AND over channels of verified
   observer conditions. A missing channel yields `INCOMPLETE` and no guard
   rather than a silently weaker one.
3. **Evidence-Gated Local Relations.** A switchable layer that requires a
   non-vacuous witness before a relation may enter composition, with three
   explicit evidence statuses. It closes a real vacuity defect in the verifier
   and costs zero extra model calls and zero extra program executions.
4. **A controlled empirical study with a negative result.** On eleven
   exploratory programs, the LLM contract path does not beat a direct guard
   prompt, and the evidence gate does not change exact accuracy. We report the
   exact counts, the per-fixture outcomes, and the failure analysis.
5. **An honest treatment of a plausible but unsupported variant.** We evaluate
   a Direct-First policy offline with fixed proposals. It gains exactly one
   exact guard over Direct Qwen at 4.66x the token cost, and the gain comes from
   the deterministic composer, not from Full MACE's final guard. We therefore
   classify it as a diagnostic, not as a new algorithm.
6. **A reproducible evidence inventory.** The repository records which results
   are system results, which are diagnostic ceilings, which belong to a separate
   operation-level task, and which claims are not supported. The companion audit
   document maps each claim to its artifact.

We emphasize what we do **not** claim: MACE does not prove masking, does not
outperform Direct Qwen on this data, does not generalize beyond the eleven
exploratory programs, and its new gate does not improve accuracy. The eleven
fixtures were used across multiple development rounds, so none is an independent
held-out test. Section 8 and Appendix B list the unsupported claims explicitly.

---

## 2. Motivating Example

### 2.1 A downstream overwrite

```python
# pyparsing/core.py, White.__init__ (lines 3368-3377)
self.minLen = min
if max > 0:
    self.maxLen = max          # A
else:
    self.maxLen = _MAX_INT
if exact > 0:
    self.maxLen = exact        # overwrites A
    self.minLen = exact
```

The deletion of `A` is unobservable when `exact > 0`: the attribute is
overwritten before any observation. When `exact == 0` and `max > 0`, the value
written by `A` survives and the deletion changes the object. The mask condition
is therefore a predicate over the *other* arguments, not a property of the
deleted statement. A local diff sees a write and a later write; it does not see
the guard.

### 2.2 A cross-function overwrite

```python
# click/core.py, Parameter.process_value (lines 2482-2512)
value = self.type_cast_value(ctx, value)          # A
...
if self.callback is not None:
    if value is UNSET:
        value = None
    ...
    if not unset_keys:
        value = self.callback(ctx, self, value)   # overwrites A
    else:
        with ctx:
            ctx.params.update(unset_keys)
            value = self.callback(ctx, self, value)
```

Whether `A` is observable depends on what the callback returns. In the audit
payloads, a constant-returning callback masks the deletion, while an
echo-returning callback exposes it. A syntax-only rule cannot distinguish these;
the condition crosses a function boundary and depends on behavior.

### 2.3 A minimal Guard-task example

```python
# fixtures/alt_masking.py
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

Here the correct guard is `mode == 0 or mode == 1`. Two downstream branches
absorb the increment; the third exposes it. The example contains both kinds of
evidence MACE needs: a fixed-point-style upstream view (the absorbing branches)
and a downstream observer view (the surviving `v`). It is one of the eleven
exploratory fixtures, not a held-out case.

The first two examples are operation-level audit cases from a separate
`reliable_ast_v1` study. They motivate the semantics; they are not part of the
Guard evaluation in this paper. The third is a Guard fixture. This distinction
is maintained throughout: the operation-level task asks which candidate
operations are masked or exposed under dynamic event-order semantics; the Guard
task asks for one Boolean input predicate per marked assignment. They have
different outputs, metrics, and logs, and results from one are never reported as
results for the other.

---

## 3. Problem Definition

### 3.1 Programs and deletion

We consider deterministic Python programs `P` in a supported subset: no
imports, no I/O, no randomness, and only operations the sandbox can execute and
observe. One assignment is marked `# TARGET_A`. Let `P+ = P` and let `P-` be `P`
with that assignment replaced by `pass`. For an input `x` from a declared finite
domain `D`, let `O+(x)` and `O-(x)` be the returned tuples (the program may
return `K` channels).

The **mask predicate** is

```
M(x) = 1  iff  O+(x) = O-(x).
```

### 3.2 Guard task (G1)

Given `P`, the marked line, the declared sorts, and `D`, synthesize a Boolean
expression `g` over the entry arguments such that

```
for all x in D:  g(x) = M(x).
```

`g` is a *bounded* guard: it is correct on `D`, not on all inputs. The declared
domains in this paper are exhaustive over their finite ranges (Section 5).

### 3.3 Metrics

A nonempty guard is **typed** if it parses and type-checks in the relation
language. On the declared domain:

- `unsound(g) = |{x : g(x)=1 and M(x)=0}|` (accepts a differing output);
- `incomplete(g) = |{x : g(x)=0 and M(x)=1}|` (rejects an agreeing output).

The reported categories partition the eleven cases:

- **exact**: typed, `unsound = 0`, `incomplete = 0`;
- **incomplete**: typed, `unsound = 0`, `incomplete > 0`;
- **unsound**: typed, `unsound > 0`;
- **invalid**: a nonempty guard fails to parse or type-check;
- **unknown**: no guard is produced.

We also report **sound** as the cumulative count of typed guards with
`unsound = 0` (exact + incomplete).

### 3.4 Relation to operation-level masking

A related but distinct task asks, for each candidate operation in a function,
whether deleting it is masked or exposed under strict observation semantics.
That is the `reliable_ast_v1` 1.0.1 task (O1). It uses dynamic event-order
eligibility, masked/exposed sets, and MSMS/MMBS relations. It does not produce a
Boolean input guard, and its 17/17 credited-relation result is not a Guard-task
result. It was obtained on a different corpus, by a different pipeline, and with
a different unit of analysis. We keep the tasks separate throughout: Section 2
uses O1 cases only as motivation; Sections 4-6 report only G1 experiments;
Appendix B forbids transferring O1 numbers to G1 claims.

---

## 4. Methodology

### 4.1 Overview

MACE has five stages:

1. probe the variable vocabulary at the marked line (names and sorts only);
2. ask the model for a typed contract bundle;
3. execute `P+` and `P-` on every input in `D` and verify each relation;
4. feed counterexamples back for at most three rounds;
5. either return the model's guard or compose one deterministically from the
   relations the checker accepted.

The evidence gate is an optional step between (3) and (5): it reclassifies each
relation by the evidence actually collected and restricts composition to
witness-verified relations.

### 4.2 Relation language and scopes

The language has sorts `bool`, `int`, `list[int]`, and `dict[int,int]`;
arithmetic, comparisons, Boolean connectives, conditional expressions, indexing,
and a fixed builtin set (`len`, `min`, `max`, `sum`, `abs`, `sorted`, `vals`,
`distinct`, `count`) plus declared program functions. Model output is parsed
into a typed AST; there is no Python `eval`.

Scopes are deliberately narrow:

| field | available names |
|---|---|
| `target_effects` | entry arguments; pre-`A` locals under plain names; post-`A` locals under `<name>_post` |
| `upstream` | entry arguments only |
| `observers` | entry arguments; post-`A` locals under plain names |
| `mask_guard` | entry arguments only |

This prevents a common failure in which a relation is accepted only because it
silently reads a local that is not in scope.

### 4.3 Contract bundle

A bundle contains:

- `target_effects` — what `A` changes in the local state;
- `upstream` — input facts with role `fixed_point` (the condition makes `A` a
  no-op) or `supporting` (explains downstream insensitivity);
- `observers` — one expression per channel plus a condition under which that
  channel cannot change;
- `mask_guard` — the final Boolean guard;
- `uncertainty` — what the model could not establish.

`parse_bundle` rejects malformed or incomplete bundles. A guard-only bundle is
allowed for baselines.

### 4.4 Bounded verification obligations

For each usable input, the checker executes both versions and evaluates:

1. **Target effect.** Under its condition, the stated pre/post relation holds.
2. **Upstream fact.** Under its condition, the stated input fact holds.
3. **Fixed-point implication.** Under a `fixed_point` condition, the pre- and
   post-`A` snapshots are equal. A failure demotes the relation to `REFUTED`
   even if the input fact was true; this is the only license for putting the
   condition into the guard's OR.
4. **Observer faithfulness.** The observer expression equals the actual channel
   value in **both** `P+` and `P-`. Checking only `P+` would let a model restate
   the plus-side answer and ignore `A`.
5. **Observer invariance.** Under the observer condition, the observed values
   in `P+` and `P-` agree.
6. **Guard.** Predicted accept/reject versus real `M(x)`; counts `unsound` and
   `incomplete`.
7. **Observer soundness.** Two states with equal observation vectors must have
   equal real outputs; a collision is a failure.
8. **Composition.** The deterministic composer is evaluated and re-checked as a
   candidate guard.
9. **Behaviour classes.** `local_inactive`, `active_masked`, `active_exposed`.

Statuses are `BOUNDED` (exhaustive declared domain), `TESTED` (sampled),
`REFUTED`, `INVALID`, and `UNKNOWN`. The implementation has no path that emits
`PROVEN`.

### 4.5 Deterministic composition

Let `F` be the verified fixed-point relations and `O_k` the verified observers
for channel `k`. The composer emits

```
guard = ( OR_{r in F} r.condition )
        OR
        ( AND_{k=1..K} ( OR_{r in O_k} r.condition ) ).
```

Only relations with verifier status `BOUNDED` or `TESTED` contribute. If a
channel has no verified observer, the result is `INCOMPLETE` with no expression;
the composer never drops a channel.

The composer does not read individual domain rows, real outputs, or the model's
own guard. It consumes the per-relation verdicts (`BOUNDED`, `TESTED`, and the
associated counters) that the bounded checker already computed from those rows.
That distinction matters: the composer is not a second checker and makes no new
semantic decision, but it is downstream of the bounded evidence and is not
independent of `D`. The composed guard is then checked like any other candidate.

### 4.6 Evidence-Gated Local Relations

The original verifier can label a relation `BOUNDED` with `checked = 0` (for a
non-observer relation) or an observer `BOUNDED` with `invariance_checked = 0`.
In both cases the label means "no counterexample was found", not "a witness was
found". The gate makes the distinction explicit:

- **`WITNESS_VERIFIED`**: the expression and condition parsed in scope; at least
  one domain input satisfied the condition and produced a supporting
  observation; no checked input falsified the claim. For an observer, at least
  one condition-true row has equal observations in `P+` and `P-`. For a
  fixed-point relation, at least one condition-true row has equal pre/post
  snapshots.
- **`REFUTED`**: at least one checked input produced a counterexample.
- **`UNVERIFIED`**: no runnable evidence — parse/type/evaluation failure, no
  condition-true input, or no fixed-point/observer witness.

Only `WITNESS_VERIFIED` relations may enter the composer. The gate reads the
per-relation counters and rows already produced by the bounded checker; it does
not execute the program again. Those rows are the deletion-intervention
outcomes themselves (`P+` keeps `A`, `P-` deletes it), so a witness is an
intervention witness, not a static claim. Enabling the gate therefore adds no
model calls and no program executions. It is off by default, and all historical
runs reproduce exactly when it is off.

The gate's evidence is still bounded: a relation that is vacuous on `D` may be
non-vacuous outside `D`. `WITNESS_VERIFIED` is not `PROVEN`, and this paper never
uses the word "proven" for a gate outcome.

### 4.7 Counterexample repair

The loop runs for at most three rounds. Each round sends the previous bundle,
the failed relations, and concrete paired executions. The model may return a
full bundle or a patch (`revise`, `add_observers`, `mask_guard`). Parse errors
and semantic errors are fed back. The model never sees the reference bundle,
hidden labels, or the real mask. With the gate on, relations whose evidence
status is not `WITNESS_VERIFIED` are also reported as failures, so the model is
asked to supply evidence rather than a bare `BOUNDED` claim. This feedback path
is implemented but was **not** exercised in a new model run for the gated
condition; Section 7 records that limitation.

### 4.8 Isolation and reproducibility

The untrusted program runs only in a child process started with `python -I`, a
fresh empty temporary directory, a scrubbed environment (no credentials), a
wall-clock timeout, an AST whitelist, and restricted builtins. The parent reads
only the child's JSON report. This is process isolation with a whitelist, not an
OS container; the code states the limitation.

### 4.9 Algorithm 1

```
Algorithm 1: MACE Guard analysis with optional evidence gating
Input : source P, target line l, finite domain D, channels K, rounds R,
        guard source s in {qwen, derived}, gate flag e
Output: guard g (or UNKNOWN), bounded report

 1  V <- probe_vocabulary(P, D[0])              # names + sorts only
 2  messages <- [system, contract_prompt(P,l,D,signatures,K,V)]
 3  previous <- None
 4  for r = 1..R:
 5      raw <- Qwen(messages; temperature=0, seed=42)
 6      if previous != None and raw is a patch:
 7          bundle_dict <- apply_patch(previous, raw)
 8      else:
 9          bundle_dict <- raw
10      bundle <- parse_bundle(bundle_dict)       # typed; reject malformed
11      report <- verify(fixture, bundle_dict)    # isolated child runs P+ and P- on D
12      qwen_guard <- bundle.mask_guard.expr
13      if e:
14          report <- gate_report(report)         # W/R/U per relation; original
15                                                # statuses are retained
16      if s == "derived":
17          composed <- compose_guard(bundle, report, K)   # gated iff e
18          if composed.expr is None and e:
19              return NO_VERIFIED_COMPOSITION, report
20          if composed.expr:
21              bundle_dict <- replace_guard(bundle_dict, composed.expr)
22              report <- verify(fixture, bundle_dict)      # re-check composed guard
23              report.qwen_guard <- qwen_guard
24      store exchange(bundle_dict, report)
25      if report.status != "OK":
26          return final guard or UNKNOWN, report
27      if report.all_relations_pass:
28          return bundle_dict.mask_guard, report
29      failures <- relations/guard not OK, plus gated-out relations if e
30      if previous != None and same_relations(previous, bundle_dict):
31          failures <- failures + "your patch changed nothing"
32      messages <- messages + [assistant(raw),
33                              user(repair_prompt(previous, failures,
34                                                 counterexamples))]
35      previous <- bundle_dict
36  return final guard or UNKNOWN, final report
```

The implementation differs from a textbook loop in two places, and the
algorithm above reflects the code rather than an idealized version. First,
`verify` both runs the paired programs and evaluates the bundle, so a round
performs one child execution batch; when a derived guard is substituted, the
substituted bundle is verified with a second batch. Second, when `s = derived`
with the gate off and the composer emits no expression, the model's own guard is
retained; only the gate-on path can return `NO_VERIFIED_COMPOSITION`.

---

## 5. Experimental Setup

### 5.1 Programs

We use eleven programs, all with exhaustive finite domains:

| fixture | split | channels | domain size | mechanism |
|---|---|---:|---:|---|
| `alt_masking` | dev6 | 1 | 160 | two absorbing branches; third exposes |
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

The split names are historical. The programs were designed, debugged, and in
some cases repaired during earlier milestones. `held1` was used while
diagnosing a parser bug; `held2` was unseen at the earlier evaluation time but
has since been inspected. **All eleven have been used in multiple rounds of
development and diagnostic analysis (M5 and M6). None is an independent
retained test set in this paper, and no statistical claim about unseen programs
is made.** All results on them are exploratory.

### 5.2 Model and runtime

- `qwen2.5-coder:32b` served by Ollama;
- temperature 0, seed 42, `num_ctx` 8192;
- at most three repair rounds;
- the stored M5 runs were executed on a remote GPU host; the M6 analyses and the
  replay are CPU-only and make no model calls.

### 5.3 Compared methods

- **Direct Qwen (A):** one prompt for the guard; counterexample feedback for at
  most three rounds.
- **Full MACE (B):** the original contract loop; the model writes the final
  guard.
- **Composer, gate OFF (C−):** the same stored contract, but the guard is the
  deterministic composition of every relation the verifier accepted.
- **Evidence-gated composer (C):** the same stored contract, but only
  `WITNESS_VERIFIED` relations may contribute.
- **Direct-First (D, diagnostic only):** keep the Direct guard when the bounded
  checker accepts it as exact; otherwise use the composer over the stored MACE
  relations. This is defined and evaluated in Section 6, RQ6.

C− and C differ only in the gate. This is the ablation. Because C is evaluated
on the stored final contract rather than a fresh model run, it is a
**fixed-proposal replay**: it isolates the gate at fixed proposals but does not
capture how `UNVERIFIED` feedback would change a live repair trajectory.

The gate's only consumer is the deterministic composer. In the original Full
MACE the model writes the final guard directly, so annotating relations cannot
change that output; a gate-annotation-only variant with the Qwen guard is
output-identical to B. We therefore define C as the gated composer, the minimal
configuration in which the mechanism can have any effect at all.

### 5.4 Evaluation

Every candidate guard is re-checked on the full declared domain with the same
bounded checker, at level `BOUNDED`. A pass is bounded equality, never a proof.
The 11 domains are exhaustive over their declared ranges. We report counts, not
estimated percentages; with n=11, one case is 9.1 percentage points.

### 5.5 Cost accounting

Token counts and wall-clock times for A and B come from the stored run logs. The
composer and gate use stored relations: they add no model calls and no program
executions. The frozen replay does **not** record CPU timings. A local
audit-time re-measurement of the same stored proposals gave 0.15 ms for all
eleven ungated compositions and 0.42 ms for all eleven gated compositions on one
CPU in a single run. Those are order-of-magnitude figures from a non-frozen
measurement, not experimental results, and should not be cited as such.
Evaluation re-checks are not part of method inference cost.

---

## 6. Results and Research Questions

### RQ1: How accurate are direct prompting, MACE, and the composer?

| method | cases | exact | sound | incomplete | invalid | unknown | unsound |
|---|---:|---:|---:|---:|---:|---:|---:|
| Direct Qwen | 11 | **5** | 6 | 1 | 0 | 0 | 5 |
| Full MACE | 11 | 3 | 5 | 2 | 3 | 0 | 3 |
| Composer (gate OFF) | 11 | 3 | 5 | 2 | 0 | 6 | 0 |
| Evidence-gated composer | 11 | 3 | 4 | 1 | 0 | 7 | 0 |

*Columns `exact`, `incomplete`, `invalid`, `unknown`, and `unsound` partition the
eleven cases; `sound` is cumulative (`exact + incomplete`). Source:
`evidence_gate/replay.json`.*

Direct Qwen is the strongest method by exact count, 5/11. Full MACE is 3/11 and
costs 5.97x the tokens. The composer is also 3/11. The gate is also 3/11. In the
earlier M5 evaluation, before the `held2` pair had been inspected, every method
scored 0/2 on that pair; the current 11-case table includes those programs as
exploratory cases.

The qualitative difference is soundness: on these eleven cases the composer
emits no unsound guard on the model-written contracts, while Direct Qwen emits
five and Full MACE three. The composer achieves this by refusing to answer when
a channel lacks a verified observer: it returns `UNKNOWN` in six cases. This is
a coverage-for-soundness trade, not an accuracy gain, and it is an empirical
outcome on this data rather than a structural guarantee.

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

Three Full MACE guards are `INVALID` because the model wrote an expression
outside the declared scope or type system (`dedup_channel`, `modulo_absorb`,
`clamp_absorb`). This is a model-interface failure, not a verifier failure: the
checker correctly refused to evaluate them.

### RQ2: Does Evidence-Gated Local Relations improve the result?

No, not in this controlled replay.

- exact guards gained by the gate: **0**;
- exact guards lost by the gate: **0**;
- relations accepted by the original verifier: **25/59**;
- relations rejected by the gate: **1**;
- rejected relations that the gate-off composer had used: **1**.

The one rejection is `dedup_channel` observer `O0`, a `BOUNDED` observer whose
condition never held on the domain (`invariance_checked = 0`). Its condition,
`len(xs) == 0`, was used by the gate-off composer to form a guard that rejected
100 agreeing inputs. With the gate, the channel has no witness-verified
observer, so no guard is emitted. The fixture moves from `incomplete` to
`unknown`; it does not become exact. The rejected relation was **unsupported,
not refuted**: relations with counterexamples are already marked `REFUTED` by
the verifier, so the gate's marginal rejection is exactly the vacuous case.

This is the honest summary of the new mechanism: it removes an unsupported
relation and makes the evidence status explicit, but it does not recover the
fixture. On a live run it would also change the repair feedback (an
`UNVERIFIED` relation would be reported as a failure), but that effect is
untested because no new model calls were made.

The gate's accounting value is real: across 59 relations, one of the 25
accepted relations had no witness. The gate makes that state impossible to
mistake for support. The accuracy value is zero on this data.

### RQ3: Where does MACE fail?

The evidence points to relation and condition induction, not to composition:

- **Upstream first, with a counting caveat.** In the earlier stage-by-stage
  diagnosis, 8 of 9 first failures were in upstream relations. That counter uses
  the first failing field in record order and therefore also counts
  `supporting` upstream slots that the model used as a place to restate a guard
  formula; it is not eight independent failures of fixed-point reasoning. The
  informative pattern is narrower: for the decisive guard-relevant relations,
  the errors are reversed fixed-point conditions, over-strong observer
  conditions, missing observer channels, and observer expressions that read the
  pre-`A` name for the post-`A` snapshot. The composer cannot recover a channel
  whose observer condition was never established.
- **Correct contracts compose.** With human-reviewed contracts, the
  deterministic composer is exact on 9/9 diagnostic cases (cell D of the 2x2
  study; the nine are the six `dev6` plus the three `held1` programs, and
  `held2` was not run in that diagnostic). Cell C, where the same reviewed
  contract is paired with a model-written guard, is 5/9. The contrast localizes
  the remaining loss to guard writing only when the relations are already
  correct. Those cells are diagnostic ceilings, not system results.
- **Non-monotone repair.** Replaying 77 stored run slots, last-write-wins scores
  35/77 exact and online best-validated retention scores 37/77; the best-ever
  diagnostic ceiling is also 37/77. Only two slots regress, both
  `parity_snap` (`A3/qwen` and `H2/qwen`), and both are the same failure mode.
  The repair loop is not the main bottleneck, but it can discard a valid
  intermediate guard.
- **Invalid is not unsound.** Full MACE's three `INVALID` guards are scope/type
  failures. They are counted separately from the three unsound guards. Treating
  all failures as "wrong Boolean formula" would overstate the semantic error
  rate.

### RQ4: What does the mechanism cost?

| method | tokens | model wall | extra model calls | extra program executions | composition CPU |
|---|---:|---:|---:|---:|---:|
| Direct Qwen | 23,626 | 102.3 s | 0 | 0 | 0 |
| Full MACE | 141,081 | 704.5 s | 0 | 0 | 0 |
| Composer (gate OFF) | 0 | 0 s | 0 | 0 | not in frozen log |
| Evidence-gated composer | 0 | 0 s | 0 | 0 | not in frozen log |

Full MACE uses 5.97x the tokens and 6.9x the wall-clock of Direct Qwen. The
composer and gate are free in model terms because they consume the stored
relations; their cost is the CPU time to classify and assemble expressions. The
gate itself adds zero executions because it reuses the checker's paired rows. A
single local audit measurement put both operations below one millisecond for all
eleven fixtures (0.15 ms ungated, 0.42 ms gated); this is indicative only and is
not a frozen result (Section 5.5).

### RQ5: What do program-analysis alternatives show?

A post-hoc frozen comparison on the same eleven fixtures reports:

| method | exact | tokens | wall |
|---|---:|---:|---:|
| Pure Symbolic (no helper summaries) | 7/11 (4 UNKNOWN/ABSENT) | 0 | 0.012 s |
| Symbolic + **human-written** helper summaries | 11/11 | 0 | 0.016 s |
| Bounded induction, sufficient direction | 10/11 | 0 | 25.2 s |
| Bounded induction, necessary direction | 0/11 | 0 | 25.2 s |

The two symbolic rows must not be conflated. **7/11 is the fully automatic
result.** The 11/11 row uses helper summaries that were written by hand for this
study; those summaries are an input to the engine, not something the engine
discovered, and the 11/11 therefore is not an autonomous result. The four
`UNKNOWN`/`ABSENT` cases in the pure row are `dedup_channel`, `modulo_absorb`,
`overwrite_channel`, and `sort_channel`, all of which need a helper fact that
the pure engine cannot derive.

Bounded induction is a separate diagnostic. Its 10/11 is measured on the
held-out `eval` split of each fixture after selection on `fit` (dev 6/6, held
4/5); `dead_flag` is exact on `fit` but not on `eval`. The necessary direction
is 0/11. The full predicate pool reaches 6/6 on dev, while a generic pool
reaches only 2/6; the difference is the hand-written template families. The
induction engine therefore demonstrates that the mask-guard sub-obligation is
amenable to bounded program analysis **given a human-designed predicate
template library**; it does not demonstrate automatic semantic discovery, and
its 10/11 does not transfer to the other MACE obligations or to programs outside
the template vocabulary.

These results are important context but are **not** an LLM+MACE contribution.
The repository also confirms that no independent "Step 5 symbolic patch" exists;
the M6 engine is a new implementation on the M6 branch. We report these numbers
to show where the bottleneck lies, not to claim them as the method of this
paper.

### RQ6: Is a Direct-First variant supported?

This question was added after the main study and is answered with an offline
simulation only. No model was called and no frozen result was changed.

**Design.** We use the stored Direct Qwen guard `G0` and the stored Full MACE
relations as fixed proposals. The policy is:

1. run the same bounded checker on `G0`;
2. if `G0` is exact on `D`, keep it;
3. otherwise use the deterministic composer over the stored MACE relations
   (gate off or gate on).

Selection uses only the bounded check of each candidate; the reference bundles
and reference guards are never loaded. This is a **fixed-proposal offline
simulation**, not an online run: the MACE relations are not regenerated, the 11
fixtures had already been inspected, and no repair feedback was exercised. Its
result is diagnostic.

**Complementarity.** On the 2x2 of final guards:

| | Full MACE exact | Full MACE not exact |
|---|---|---|
| Direct exact | 3 (`alt_masking`, `dead_flag`, `dict_slot`) | 2 (`dedup_channel`, `overwrite_channel`) |
| Direct not exact | 0 | 6 (`modulo_absorb`, `sort_channel`, `swap_channels`, `parity_snap`, `clamp_absorb`, `toggle_pair`) |

No fixture is Full-MACE-only. The oracle union of the two final guards is
therefore 5/11, the same as Direct alone.

**Policy result.** The Direct-First policy reaches **6/11**: it keeps the five
exact Direct guards and gains `parity_snap`, where the composer over the MACE
relations is exact even though the Full MACE final guard is unsound. It loses
none. The gain is attributable to the deterministic composer, not to a better
MACE guard. The gate-on and gate-off variants both reach 6/11.

**Cost.** Direct alone is 23,626 tokens / 102.31 s. Running MACE on the six
Direct-refuted fixtures adds 86,403 tokens / 426.14 s, for a policy total of
110,029 tokens / 528.45 s — 4.66x the Direct tokens and 5.17x the wall time.

**Why it is not a new algorithm result.** The verifier detects the Direct error
in all 6/6 non-exact cases (every one has nonzero `unsound` or `incomplete`).
But relation-level evidence fully repairs only 1/6 (`parity_snap`), partially
repairs 2/6 (`sort_channel`, `toggle_pair`; sound but incomplete), and provides
detection only for 3/6 (`modulo_absorb`, `swap_channels`, `clamp_absorb`;
composer emits no guard). The bottleneck is candidate generation, not two-sided
checking. A +1/11 exact gain at 4.66x token cost, on fixtures already inspected,
with no online run, is not sufficient evidence for a new effective algorithm.
It is also dominated on accuracy and cost by the symbolic induction result
(10/11, zero tokens, 25.2 s). We report it because it is the strongest variant
the existing evidence can support, and even it does not support a superiority
claim.

---

## 7. Threats to Validity

**Construct validity.** Exactness is equality with the real mask on a finite
domain. `BOUNDED` is not `PROVEN`; a guard that is exact on `D` may fail
outside it. The metrics separate unsound, incomplete, invalid, and unknown, but
they do not measure explanation quality or the usefulness of a relation to a
human. The relation language is deliberately small; a correct guard outside the
language would be counted as invalid.

**Internal validity.** The same domain is used to verify relations and to
evaluate the guard. This is standard in bounded verification but it is not a
generalization test. The repair loop also uses counterexamples from `D`. The
replay comparison is a fixed-proposal replay, not a live run with gate-modified
feedback; it isolates the gate but cannot estimate its end-to-end effect. The
Direct-First result is a fixed-proposal offline simulation under the same
limitation. The gate's witness requirement is itself bounded by `D`, so a
relation vacuous on `D` might be non-vacuous elsewhere. The three `INVALID` Full
MACE guards mix scope errors and type errors; we do not separate them further.
Model sampling is controlled by temperature 0 and seed 42, but a single run per
fixture cannot quantify run-to-run variance.

**External validity.** Eleven small programs, one model, one seed, three rounds.
The programs were authored for this research and were inspected during earlier
milestones; they are not a fresh benchmark. The real-code examples are
operation-level audit cases, not Guard-task evaluations. The symbolic and
induction comparisons have their own dependencies (a hand-written predicate
template library; human-written helper summaries), which are stated with their
numbers. No claim is made about real repositories, other model families, or
other languages.

**Conclusion validity.** With n=11, one case is 9.1 percentage points; the
difference between 5/11 and 3/11 is two cases. We report counts rather than
significance tests. The negative result for the gate is robust in the sense that
it gains and loses zero exact cases, but the sample is too small to bound a
small positive effect. The Direct-First +1 is a single case and is not
statistically interpretable.

**Mitigations.** All numbers come from stored logs or are explicitly labelled as
non-frozen local measurements; the fixtures and domains are public in the
repository; the verifier has no `PROVEN` path; the paper reports the negative
result and the diagnostic status of the oracle cells. The companion audit
records the exact artifact for every number and the claims that must not be
made.

---

## 8. Related Work

**Dead code and dead stores.** Classical compiler analyses eliminate
assignments whose values are never observed [Muchnick 1997]. Liveness and
dead-store analyses are usually syntactic or dataflow-based; MACE targets a
different question: the *input condition* under which a single marked
assignment is unobservable, including cases where the value is observed on some
inputs and absorbed on others. The output is a guard, not a transformed program.

**Program slicing and dependence analysis.** Slicing computes the statements
that can affect an observation; MACE asks for a Boolean predicate over inputs
and verifies it by execution. The two are complementary: a slice could propose
candidate relations, while MACE checks and composes them.

**Dynamic invariant detection.** Daikon [Ernst et al. 2007] infers likely
invariants from executions. MACE uses executions as a bounded oracle for
model-proposed relations and keeps refutations explicit; it does not infer
invariants from scratch.

**Bounded verification and symbolic execution.** KLEE [Cadar et al. 2008] and
DART [Godefroid et al. 2005] explore paths with symbolic or directed inputs.
MACE uses concrete paired executions over a declared finite domain and reports
`BOUNDED`, not path-coverage guarantees. The finite domain makes the checker
simple and auditable; it also limits the claim.

**Counterexample-guided synthesis.** CEGIS [Solar-Lezama et al. 2006; Alur et
al. 2013] alternates candidate synthesis with counterexample verification. MACE
is a natural-language variant: the model proposes typed relations, the checker
returns concrete counterexamples, and the model repairs. The difference is that
MACE composes the final guard deterministically from verified relations instead
of trusting the model's final answer.

**LLMs for code.** Codex [Chen et al. 2021], MBPP [Austin et al. 2021], and
AlphaCode [Li et al. 2022] established that LLMs can generate code and solve
programming problems. LLM+verifier loops and LLM-based program repair
[Schäfer et al. 2023] use tests or static checks as feedback. MACE's negative
result is consistent with a broader pattern: the model is useful as a proposal
source, but the verifier, not the model, must define correctness. Our
contribution is the contract interface and the bounded accounting, not a claim
that the LLM has learned the semantics.

**Mutation testing.** A masked mutant survives because no test distinguishes
it; MACE's mask predicate is a semantic analogue for a single assignment
deletion [Jia & Harman 2011; Just et al. 2014; Papadakis et al. 2019]. The
difference is that MACE synthesizes an input predicate rather than measuring a
test suite.

---

## 9. Conclusion

MACE treats conditional assignment deletion as a bounded contract problem. The
model proposes typed relations, the checker verifies them on paired executions,
and a deterministic composer turns the verified relations into a guard. The
evidence gate adds an explicit witness requirement and a three-way evidence
status, closing a real vacuity defect at zero extra execution cost.

On eleven exploratory programs the result is negative for the LLM path: Direct
Qwen is 5/11 exact, Full MACE 3/11, the composer 3/11, and the gated composer
3/11. The gate gains no exact guard. What the framework does provide is
soundness accounting: the composer never emits an unsound guard on
model-written contracts, the verifier never claims a proof, and every accepted
relation has a bounded witness (after the gate). The diagnostic ceiling shows
that correct contracts compose exactly (9/9 on the nine diagnostic fixtures),
which places the bottleneck in upstream relation and condition induction.

We also report the strongest variant the evidence can support. A Direct-First
policy with fixed proposals reaches 6/11, one case above Direct, at 4.66x the
tokens, with zero losses; the gain is a composer substitution on `parity_snap`,
not a Full MACE win, and it does not survive as an algorithm claim because it is
an offline simulation on already-inspected fixtures. Program analysis is the
better direction: pure symbolic execution reaches 7/11 autonomously, and with
human-written helper summaries 11/11, while bounded induction reaches 10/11 on
the mask-guard sub-obligation with a hand-written template pool.

The next step suggested by the evidence is not more prompt engineering. It is to
replace or augment the model's relation proposal with program analysis, and to
connect the operation-level intervention machinery to the Guard loop. Until
that is done and evaluated on an independent set, MACE should be presented as a
verification and accountability framework with a negative accuracy result, not
as a state-of-the-art masking analyzer.

---

## References

- Alur, R., Bodik, R., Juniwal, G., Martin, M., Raghothaman, M., Seshia, S. A.,
  Singh, R., Solar-Lezama, A., Torlak, E., Udupa, A. *Syntax-guided synthesis.*
  FMCAD 2013.
- Austin, J., Odena, A., Nye, N., Bosma, M., Michalewski, H., Dohan, D., Jiang,
  E., Cai, C., Terry, M., Le, Q., Sutton, C. *Program synthesis with large
  language models.* arXiv:2108.07732, 2021.
- Cadar, C., Dunbar, D., Engler, D. *KLEE: Unassisted and automatic generation
  of high-coverage tests for complex systems programs.* OSDI 2008.
- Chen, M., Tworek, J., Jun, H., et al. *Evaluating large language models
  trained on code.* arXiv:2107.03374, 2021.
- Cousot, P., Cousot, R. *Abstract interpretation: A unified lattice model for
  static analysis of programs by construction or approximation of fixpoints.*
  POPL 1977.
- Ernst, M. D., Perkins, J. H., Guo, P. J., McCamant, S., Pacheco, C., Tschantz,
  M. S., Xiao, C. *The Daikon system for dynamic detection of likely
  invariants.* Science of Computer Programming 69(1-3), 2007.
- Godefroid, P., Klarlund, N., Sen, K. *DART: Directed automated random
  testing.* PLDI 2005.
- Jia, Y., Harman, M. *An analysis and survey of the development of mutation
  testing.* IEEE Transactions on Software Engineering 37(5), 2011.
- Just, R., Jalali, D., Inozemtseva, L., Ernst, M. D., Holmes, R., Fraser, G.
  *Are mutants a valid substitute for real faults in software testing?* ISSTA
  2014.
- Li, Y., Choi, D., Chung, J., Kushman, N., et al. *Competition-level code
  generation with AlphaCode.* Science 378(6624), 2022.
- Muchnick, S. S. *Advanced Compiler Design and Implementation.* Morgan
  Kaufmann, 1997.
- Papadakis, M., Kintis, M., Zhang, J., Jia, Y., Traon, Y. L., Harman, M.
  *Mutation testing advances: An analysis and survey.* Advances in Computers
  112, 2019.
- Schäfer, M., Nadi, S., Eghbali, A., Tip, F. *An empirical evaluation of using
  large language models for automated program repair.* ESEC/FSE 2023.
- Solar-Lezama, A., Tancau, L., Bodik, R., Seshia, S. A., Saraswat, V.
  *Combinatorial sketching for finite programs.* ASPLOS 2006.

---

## Appendix A. Reproducibility

```bash
cd <local-path>
python -m pytest -q                       # 230 tests
python scripts/m6_symbolic.py             # frozen M6 symbolic comparison, no model calls
python scripts/evidence_gate_replay.py    # gate replay, no model calls
python scripts/direct_first_feasibility.py  # Direct-First offline simulation, no model calls
```

Stored model runs are under `m5/`; M6 aggregates under `m6/`; the gate replay is
under `evidence_gate/`; the Direct-First simulation writes
`direct_first/feasibility.json`. The M1-M6 freeze is recorded in
`docs/FREEZE_MANIFEST.md` and `m6/freeze_manifest.json`. The replay and the
Direct-First simulation are outside that freeze.

## Appendix B. Unsupported claims

See also `docs/MACE_paper_evidence_inventory.md`, Section 8, and the companion
`docs/MACE_claim_evidence_audit.md`. In particular, do not write that:

- MACE beats Direct Qwen, or that any MACE variant is a new state-of-the-art
  masking analyzer;
- the evidence gate improves accuracy (it gains and loses zero exact guards on
  this data);
- Direct-First 6/11 is an online algorithm result (it is a fixed-proposal
  offline simulation on already-inspected fixtures, with one gain);
- the bounded results are proofs, or that `WITNESS_VERIFIED` is `PROVEN`;
- the eleven fixtures are an independent held-out benchmark;
- the AST 1.0.1 17/17 is a MACE/Guard result;
- Pure Symbolic 7/11 and Symbolic + human-written helper summaries 11/11 are the
  same result, or that 11/11 is autonomous;
- bounded induction 10/11 is automatic semantic discovery (it depends on a
  hand-written predicate template library and covers only the mask-guard
  sub-obligation);
- the human-reviewed contract 9/9 is a system result rather than a diagnostic
  ceiling;
- the model has learned the masking semantics, or that MACE establishes masking
  conditions on all inputs.

## Appendix C. Result-to-artifact map

| Claim | Artifact |
|---|---|
| RQ1 table and per-fixture outcomes | `evidence_gate/replay.json`, `evidence_gate/replay.md` |
| 25/59 accepted, 1 gate rejection, 1 used by gate-off composer | `evidence_gate/replay.json` (`relation_audit`) |
| Gate 0 gains / 0 losses | `evidence_gate/replay.json` (`methods.compose` vs `methods.gated`) |
| Correct contracts compose 9/9; cell C 5/9 | `m5/cells_C.json` |
| 77 slots; 35 final, 37 online, 37 best-ever; 2 `parity_snap` regressions | `m6/repair.json`; `docs/M6_decision.md` §2 |
| Pure 7/11, 0.012 s; symbolic 11/11, 0.016 s | `m6/symbolic.json` |
| Induction sufficient 10/11 (`eval`), necessary 0/11, 25.2 s | `m6/induct_dev.json`, `m6/induct_held.json`; `docs/M6_decision.md` |
| Generic pool 2/6 vs full 6/6 (dev) | `m6/induct_dev.json` |
| Direct-First 2x2, 5/11 union, 6/11 policy, cost | `direct_first/feasibility.json` |
| Token and wall totals (23,626 / 141,081; 102.3 / 704.5 s) | `m6/symbolic.json` (`direct`, `mace` rows) |
| Domain sizes, channels, exhaustive flag | `evidence_gate/replay.json` (`domain_size`, `channels`, `domain_exhaustive`) |
| Model prompt visibility (no reference/hidden labels) | `mace/prompts.py` header and prompt builders |
| Verifier obligations and no `PROVEN` path | `mace/verify.py`; `mace/compose.py`; `mace/evidence_gate.py` |
| Sandbox isolation | `mace/sandbox.py`, `mace/runner.py` |
| 230 tests | `python -m pytest -q` |
