# MACE-Bench v2.1 — HELDOUT Official Scoring Report

Generated: 2026-11-05T15:02Z  
Split: `benchmark_v4_dataset/source_derived_v2_1/heldout` (formal v2.1)  
Scorer: `scripts/score_heldout_v2_1.py` **v1.1**  
Status: **scored once, unsealed, no model called, no prediction modified.**
Scoring stopped immediately after the deliverables were written.

## 1. Frozen-file gate and unsealing

All four prediction files matched their frozen SHA-256 before a single score was
computed. The scorer aborts with no output on any mismatch; none occurred.

| Method | File | Expected SHA-256 | Actual | Match |
|---|---|---|---|---|
| C0 | `results/MACE_HELDOUT_v2_1_C0_predictions.json` | `ecc55c7ac10bc5e302d69ae31b7b5439f0847c983eb1dbe39d1fe72bae40d28d` | same | yes |
| Full MACE | `results/MACE_HELDOUT_v2_1_Full_predictions.json` | `056e6565f0eed7f3e8057ddd0a5550299e42ccb14e0ba7065a25dbd5756ee478` | same | yes |
| Direct Qwen 32B | `results/MACE_HELDOUT_v2_1_Direct_Qwen_predictions.json` | `0d216443dc35ca404c5f508e312d1a501dc4b124eedec82f578eeac40dd2476e` | same | yes |
| Direct GLM 4.7-flash | `results/MACE_direct_GLM_v2_1_heldout_predictions.json` | `b18154766089fd849515f485bbdb279dd47b336c48fd3d1d4f70f2f1a052597f` | same | yes |

Truth source for every method is the same set of 25 formal files
`heldout/tasks/<cid>/reference.json` (SHA-256 of all 25 recorded in
`results/MACE_HELDOUT_v2_1_official_scores.json → audit.reference_hashes`).
No legacy `source_derived/heldout` path appears in any prediction record
(`audit.prediction_hashes[*].path` all point to `source_derived_v2_1`).
Reference, enumeration and prediction bytes were never modified.

Scorer self-checks (fail-closed) passed: the four methods are scored on the
*identical* set of 20 eligible inputs, and for C0/Full the number of non-empty
masking-input predictions matches the prediction files exactly
(12 and 14 respectively).

**Scorer version history (disclosed).** v1.0 contained a method-alias defect:
the per-input branch tested `name == "Full"` while the frozen key is
`"Full MACE"`, so Full was read through the Direct branch and scored as empty.
That defective output was detected before any number was reported and
overwritten; v1.1 fixes it and adds the self-check that would have caught it.
The v1.0 anomaly (Full 0/20) is not used anywhere.

## 2. Scoring definition (frozen v2.1, unchanged)

- **Eligibility (fixed before scoring, applied identically to all four
  methods):** an input is scored iff its reference `role == "masking"`.
- **Denominator:** 20 inputs across 20 tasks, identical for all four methods
  (`audit.self_checks.eligible_key_sets_identical = true`). No method-specific
  denominator, no removal of failures, no zero-filling.
- **Functions:** `score_sets` from the frozen DEV scorer, with
  `project_containment` / `block_spans` from
  `benchmark_v4_dataset/tools/sd_algorithm_pilot.py`. An operation counts for
  a hidden block only if its whole line span lies inside exactly one block;
  otherwise it is stray. `msms_exact = (got == want) and (no stray)`.
- **Empty prediction:** scored by the same rule, i.e. not exact. It stays in
  the denominator. UNKNOWN is not FALSE and is not a correct answer.
- **Required metrics:** Strict MSMS Exact Match, False Relations
  (`|got − want| + |stray|`), Unmatched Operations (predicted sets that map to
  no block), Cooperative Masking Accuracy (M2+M3 inputs), Alternative Path
  Accuracy (M4 inputs), MMBS Accuracy (not applicable — see §7).

### 2.1 Anomalous task disclosure: `sd_multidict_version_m6`

The task has three inputs. Under the frozen role rule only one is eligible:

| Input | Role | In denominator |
|---|---|---|
| `mask_one_impl` | masking | **yes** |
| `expose_two_impls` | exposing | no |
| `control_non_multidict` | control | no |

Per-method outcome on the eligible input: C0 and Full MACE
`EXECUTION_ERROR` (the A-deletion side probe exits non-zero, gate
`probe_error`), Direct Qwen produced 9 sets none of which maps to a block
(0 exact, counted as false relations), Direct GLM `INVALID_OUTPUT`. The other
two inputs are outside every method's denominator by the same rule; they were
not scored for anyone. This is the only task touched by this anomaly.

## 3. Per-method HELDOUT results (denominator = 20 masking inputs)

| Method | Strict exact | Exact % | Non-empty coverage | Accuracy given non-empty | Present-superset | False relations | Unmatched sets | Stray ops |
|---|---|---|---|---|---|---|---|---|
| C0 (Graph/AST) | 7/20 | 35.0 | 12/20 (60.0%) | 7/12 (58.3%) | 7 | 8 | 3 | 3 |
| **Full MACE + Qwen** | **12/20** | **60.0** | **14/20 (70.0%)** | **12/14 (85.7%)** | **13** | **5** | **2** | 4 |
| Direct Qwen 32B | 4/20 | 20.0 | 12/20 (60.0%) | 4/12 (33.3%) | 6 | 74 | 40 | 63 |
| Direct GLM 4.7-flash | 1/20 | 5.0 | 9/20 (45.0%) | 1/9 (11.1%) | 4 | 29 | 17 | 21 |

Relation-level precision/recall (micro over all predicted/scored structures;
macro = mean over the 20 inputs with an empty prediction counted as 0):

| Method | micro P | micro R | macro P | macro R |
|---|---|---|---|---|
| C0 | 0.5833 | 0.2188 | 0.3500 | 0.3500 |
| Full MACE | 0.9375 | 0.4688 | 0.6500 | 0.6500 |
| Direct Qwen | 0.3889 | 0.2188 | 0.2500 | 0.3000 |
| Direct GLM | 0.3846 | 0.1562 | 0.1250 | 0.2000 |

Note that recall is bounded by the gate: 5 of the 20 masking inputs are
`A_NOT_EXECUTED` for C0/Full (the plus/minus comparison cannot be executed),
plus 1 `probe_error`, so their maximum attainable recall is structurally
below 1.

### 3.1 Failure states over the 20 eligible inputs

| Method | SCORED | ABSTAIN_EMPTY | NO_CANDIDATE | EXECUTION_ERROR | INVALID_OUTPUT |
|---|---|---|---|---|---|
| C0 | 12 | 7 | 0 | 1 | 0 |
| Full MACE | 14 | 5 | 0 | 1 | 0 |
| Direct Qwen | 12 | 0 | 0 | 0 | 8 |
| Direct GLM | 9 | 0 | 0 | 0 | 11 |

C0/Full gate breakdown: `PUBLIC_MASKING_CANDIDATE` 14, `A_NOT_EXECUTED` 5,
`probe_error` 1. C0 emitted a set on 12 of its 14 public candidates; Full
emitted on all 14. The 5 `A_NOT_EXECUTED` inputs are honest empty predictions,
not errors of the scorer.

`INVALID_OUTPUT` is task-level for the Direct methods: 10 of 25 HELDOUT tasks
for Qwen (8 of them contain an eligible input) and 14 of 25 for GLM (11
eligible inputs). Every input of an invalid task is scored as empty.

### 3.2 Cooperative and alternative-path accuracy

| Method | Cooperative (M2+M3): exact/inputs | % | Alternative path (M4): exact/inputs | % |
|---|---|---|---|---|
| C0 | 0/6 | 0.0 | 0/3 | 0.0 |
| Full MACE | 3/6 | 50.0 | 1/3 | 33.3 |
| Direct Qwen | 0/6 | 0.0 | 0/3 | 0.0 |
| Direct GLM | 0/6 | 0.0 | 1/3 | 33.3 |

## 4. Paired comparison on identical inputs

Every pair is computed on the same 20 inputs. b = A-only exact, c = B-only
exact; McNemar exact two-sided binomial test. Effect size = risk difference
(b − c)/20, with the discordant counts shown so the effect is not reduced to a
p-value.

| A vs B | b (A only) | c (B only) | both | neither | Discordant | Risk diff (A−B) | Exact p | Significant at 0.05 |
|---|---|---|---|---|---|---|---|---|
| C0 vs Full MACE | 0 | 5 | 7 | 8 | 5 | −25.0 pp | 0.0625 | no |
| C0 vs Direct Qwen | 3 | 0 | 4 | 13 | 3 | +15.0 pp | 0.2500 | no |
| C0 vs Direct GLM | 7 | 1 | 0 | 12 | 8 | +30.0 pp | 0.0703 | no |
| Full MACE vs Direct Qwen | 8 | 0 | 4 | 8 | 8 | +40.0 pp | **0.0078** | **yes** |
| Full MACE vs Direct GLM | 11 | 0 | 1 | 8 | 11 | +55.0 pp | **0.0010** | **yes** |
| Direct Qwen vs Direct GLM | 4 | 1 | 0 | 15 | 5 | +15.0 pp | 0.3750 | no |

The full per-input matrix (20 rows × 4 methods × outcome state) is
`results/MACE_HELDOUT_v2_1_paired_matrix.csv`.

Power note: with 20 paired inputs and 5 discordant pairs, the smallest
attainable two-sided p for a 5–0 split is 0.0625; a 6–0 split would give
0.0313. The Full-vs-C0 comparison is therefore underpowered by construction,
not a null result in the ordinary sense. No test was run on the subsets (§5)
because n ≤ 17 and multiplicity would dominate.

## 5. Generalization subsets (official seal flags, fixed before truth)

Units: masking inputs; task counts in parentheses.

| Subset | Tasks | Inputs | C0 | Full MACE | Direct Qwen | Direct GLM |
|---|---|---|---|---|---|---|
| All HELDOUT | 25 | 20 | 7 (35.00%) | **12 (60.00%)** | 4 (20.00%) | 1 (5.00%) |
| Project-disjoint | 19 | 17 | 6 (35.29%) | **10 (58.82%)** | 3 (17.65%) | 0 (0.00%) |
| Template-disjoint | 16 | 16 | 4 (25.00%) | **8 (50.00%)** | 2 (12.50%) | 1 (6.25%) |
| Project- and template-disjoint | 14 | 14 | 4 (28.57%) | **7 (50.00%)** | 2 (14.29%) | 0 (0.00%) |

Two cautions, both required:

- These are **descriptive** counts. No subset test is reported; the orderings
  are consistent with the full-set ordering but cannot carry a significance
  claim at n = 14–17.
- The 14 "both-disjoint" tasks are disjoint in **project and template**, but
  the earlier audit established that the number of tasks that are genuinely
  new in **both mechanism and template** is **0**. No claim of double-novel
  generalization may be made from this row.

## 6. DEV → HELDOUT change

DEV numbers are the published closure results. HELDOUT numbers are this run.
The DEV denominator (27 for C0/Full) includes 2 control-role inputs that the
strict `role == "masking"` rule excludes; the strict-role DEV figures (25
inputs) are shown separately so the comparison can be made on a matched rule.

| Method | DEV (published) | DEV strict rule | HELDOUT | Δ (strict − HELDOUT) |
|---|---|---|---|---|
| C0 | 14/27 = 51.85% | 13/25 = 52.00% | 7/20 = 35.00% | **−17.0 pp** |
| Full MACE | 19/27 = 70.37% | 18/25 = 72.00% | 12/20 = 60.00% | **−12.0 pp** |
| Direct Qwen | — | 2/25 = 8.00% | 4/20 = 20.00% | +12.0 pp |
| Direct GLM | — | 5/25 = 20.00% | 1/20 = 5.00% | −15.0 pp |

- The DEV strict-rule figures are obtained by removing the two control-role
  rows from the published DEV counts. Both tasks are unambiguous (one is
  all-exact, the other all-wrong for both C0 and Full), so no per-input guess
  is involved; `results/MACE_v2_1_DEV_vs_HELDOUT.csv` records the derivation.
- Full MACE and C0 both drop; the drop is 5–7 pp smaller for Full, so the
  C0→Full gap is wider on HELDOUT (25 pp) than on DEV (20 pp strict).
- Direct Qwen *rises* on HELDOUT (2/25 → 4/20). This is not evidence of
  transfer: its DEV and HELDOUT runs have different invalid-output profiles
  (5 vs 10 invalid tasks) and different task samples. Do not read it as a gain.
- All four DELTAS are descriptive. The DEV and HELDOUT task sets are disjoint
  and there is no paired test across splits.

## 7. Failures, efficiency and comparability

**Preserved and disclosed failures.** Direct Qwen's 10 `INVALID_OUTPUT` tasks
(8 of them inside the scored 20 inputs) are retained in every denominator and
scored as empty. GLM's 14 invalid tasks (11 eligible inputs) likewise. Nothing
was rerun, repaired, re-prompted or imputed in this round.

**Context truncation (prediction-stage artefact, not re-run here).** 12/25
Direct Qwen prompts and 10/25 Direct GLM prompts were served at exactly 4098
prompt tokens, i.e. above the serving cap despite the declared `num_ctx=8192`.
Full MACE prompts ranged 2,344–10,725 tokens against `num_ctx=16384`, all
`done_reason=stop`, no truncation. This asymmetry is a property of the
comparison and is not corrected by scoring.

| Method | Probe executions | Prompt tokens | Completion tokens | Runtime (sum, s) | Prediction unit |
|---|---|---|---|---|---|
| C0 | 152 | — | — | 39.3 | per input |
| Full MACE | 234 | 134,205 | 11,334 | 1,437.9 | per input |
| Direct Qwen | — | 96,272 | 16,442 | 954.0 | per task |
| Direct GLM | — | 102,377 | 14,025 | 325.1 | per task |

**Coverage is not accuracy.** Non-empty coverage is 60/70/60/45% for
C0/Full/Qwen/GLM, but exactness given non-empty is 58.3/85.7/33.3/11.1%.
Full MACE emits on every one of its 14 public candidates and is exact on 12;
Direct Qwen emits on 12 inputs but is exact on 4, with 74 false relations.

**Metrics that cannot be compared, and why.**

- **MMBS accuracy:** N/A for all methods. No frozen method emits MMBS
  predictions, so there is no numerator and no method is penalised for it.
  The reference's MMBS was not used.
- **Cost:** C0/Full are per-input search procedures with probes; Direct
  methods are one call per task with no probes. Wall-clock and probe counts
  measure different things and must not be tabulated as a like-for-like
  efficiency comparison.
- **Direct method granularity:** task-level sets applied to every input, as in
  the frozen DEV protocol. Per-input differences within a Direct task are not
  an output the model produced.
- **Per-task accuracy:** not reported for Direct methods; a task with several
  masking inputs has one shared answer, so task-level counts would inflate or
  deflate relative to input-level counts. Input-level is the only common unit.

## 8. Answers to the six required questions

1. **Is Full MACE better than C0 on HELDOUT?** Yes descriptively: 12/20
   (60.0%) vs 7/20 (35.0%), +25 pp; all 5 discordant pairs favour Full and none
   favour C0. Statistically: **not significant at 0.05** with exact McNemar
   (p = 0.0625, two-sided; 0.0313 one-sided), which is the floor for a 5–0
   split at n = 20. Claim it as a consistent, sizeable descriptive gain, not a
   significant one.
2. **Is Full MACE better than both Direct LLMs?** Yes, and significantly:
   12/20 vs 4/20 (p = 0.0078) and vs 1/20 (p = 0.0010); risk differences
   +40 pp and +55 pp, with 8 and 11 discordant pairs, none favouring the
   Direct method.
3. **How much does performance drop from DEV to HELDOUT?** Full MACE
   72.0% → 60.0% on the matched strict rule (−12.0 pp); C0 52.0% → 35.0%
   (−17.0 pp); Direct GLM 20.0% → 5.0% (−15.0 pp); Direct Qwen rises
   8.0% → 20.0% (+12.0 pp, not a transfer gain — see §6). On the published
   DEV denominators the drops are −10.4 pp (Full) and −16.9 pp (C0). These are
   descriptive cross-split differences.
4. **Project and template isolation?** Full MACE is the best method in every
   subset: 58.82% project-disjoint, 50.00% template-disjoint, 50.00%
   both-disjoint, against C0's 35.29/25.00/28.57 and the Direct methods'
   0–14.29%. The ordering is stable; the subset numbers are descriptive and
   underpowered, and the "both-disjoint" set contains **0** tasks that are new
   in both mechanism and template.
5. **Which conclusions are statistically supported?** Supported at 0.05:
   Full MACE > Direct Qwen, Full MACE > Direct GLM. Not supported at 0.05:
   Full MACE > C0 (p = 0.0625), C0 > either Direct model, Qwen vs GLM.
   Everything about subsets, DEV→HELDOUT deltas, coverage and cost is
   descriptive.
6. **What can the paper claim from these results?**
   - That on a project- and template-disjoint HELDOUT set, a masking-aware
     contract engine reaches 60% strict MSMS exactness, significantly above
     both direct LLM baselines (20% and 5%).
   - That it is directionally and consistently above the graph/AST-only C0
     baseline (+25 pp, 5–0 discordant), stated as a descriptive gain with an
     explicit power caveat.
   - That direct LLM outputs are dominated by false relations and unmatched
     operations (74/40 and 29/17), which is the qualitative failure mode the
     method is designed to remove.
   - **Not** supported: any MMBS claim; any "double-novel mechanism + template"
     claim (count is 0); any efficiency advantage (Full costs ~36× C0 wall
     clock); any significance claim for the C0 comparison or the subsets.

## 9. Artefacts, hashes and audit

Scoring computation: `2026-11-05T15:01:55Z` (scorer start/finish stamps in the
JSON audit). No model call, no prediction write, no reference write.

| Artefact | Bytes | SHA-256 |
|---|---|---|
| `results/MACE_HELDOUT_v2_1_official_scores.json` | 127,184 | `6060a707dc28fc8d2b8d9d8f64cc57ca45f26cbdd0c8506c9c1144059d6fcfa2` |
| `results/MACE_HELDOUT_v2_1_per_input_scores.csv` | 33,843 | `556fcdf84d88f79ca4087e40211f7966abba0ec3fdcd072d98fee39addc3b70b` |
| `results/MACE_HELDOUT_v2_1_method_comparison.csv` | 435 | `dba0eaafff7ce561005fe803528ea23279eb00cfdf4042cc12242949f1d63582` |
| `results/MACE_HELDOUT_v2_1_generalization.csv` | 637 | `c6c20bcbb49c690eb540809a729c217bfca69ac41321c5172be3dae8ed9f73f2` |
| `results/MACE_HELDOUT_v2_1_paired_matrix.csv` | 2,068 | `de11a758bdd00f7c10a1205c0ca6dffac63d925cffd831618d28a686460a4f91` |
| `results/MACE_v2_1_DEV_vs_HELDOUT.csv` | 670 | `096af3a9a45241cf7f74aa3dc68caf2d0734f61e500f9998100b1dc0754e8cb5` |
| scorer `scripts/score_heldout_v2_1.py` (v1.1) | — | `1ac1b4a0b6eceee36896fa734729790e51a97fcdf7028097e6bedfba254fc0b4` |
| extras `scripts/build_heldout_v2_1_scoring_extras.py` | — | `6607f2320367c97d8d47d969aa175f6540870745b9595452416482a3cfa1ba46` |

The JSON audit also records: all 25 reference/enumeration SHA-256 values, all
four prediction hashes with match flags, scorer version and version note, the
self-check block, and the anomaly disclosure.

Scoring is complete. No algorithm change, no new experiment, no re-run was
started after this point.
