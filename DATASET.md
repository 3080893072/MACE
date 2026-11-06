# MACE-Bench v2.1

MACE-Bench v2.1 is a controlled, execution-verified benchmark of **masking
relations** in real Python code. Every task is derived from a released sdist,
inserted into a real function, and verified by re-execution against an
independently enumerated relation space.

- Dataset root: `benchmark_v4_dataset/source_derived_v2_1/`
- Protocol: `benchmark_v4_dataset/PROTOCOL.md`
- Track: `SOURCE_DERIVED_CONTROLLED`
- Size: 50 tasks — 25 DEV, 25 HELDOUT
- Acceptance: 50/50 pass the v2.1 independent checks (`acceptance.json`)
- Version of the relation definition: `v2.1`

## 1. Task format

Each task is a directory under `tasks/<task_id>/` with five files.

### `task.json`

| Field | Meaning |
|---|---|
| `task_id` | Stable identifier, equal to the directory name. DEV ids are `sd_<project>_<slug>_<mechanism>`; HELDOUT ids use the same scheme. |
| `project`, `version` | Upstream PyPI project and exact version. |
| `split` | `DEV` or `HELDOUT`. |
| `track` | Always `SOURCE_DERIVED_CONTROLLED`. |
| `mechanism` | One of `M1_SINGLE_OPERATION` … `M9_EXCEPTION_FALLBACK`, or `M10_NEGATIVE_CONTROL` (HELDOUT only). |
| `target_operation` | `file`, `line`, `function`, `code`, `statement`. `A` is a single executable statement in released source. |
| `related_functions` | The function containing `A` plus every function enclosing a `U` anchor. |
| `deletion_method` | `replace the line with equal-indentation 'pass  # P-: target A deleted'`; line numbers are preserved. |
| `legal_input_contract` | The public API call used by probes and its constraints. |
| `declared_inputs` | `{id, role, description}`. Roles are `masking`, `exposing`, `control`, `negative_control`. |
| `original_tests` | Upstream tests that exercise `A`, when identified. |
| `scope_note` | Repeats that the claim is bounded to the declared inputs and candidate universe. |

### `reference.json`

The ground truth for one task:

- `candidate_universe` — the declared operations `U1…Uk` with file, line, code
  and block membership.
- `inputs` — per input id: `msms` (minimal non-empty sufficient kept sets) and
  `mmbs` (minimal breaking disabled sets, or empty with status
  `NOT_SEPARABLE`).
- `relation_definition_version` — `v2.1`.
- `not_claimed` — explicit scope exclusions.

`reference.json` is **hidden from every method**. Only the scorer reads it.

### `patch.diff`, `provenance.json`, `acceptance.json`

- `patch.diff` — the insert-only researcher patch that adds the `U` blocks
  delimited by `# SD:U:<id>:begin` / `# SD:U:<id>:end`.
- `provenance.json` — sdist URL and SHA-256, original and patched file hashes,
  the probe command, metadata and the license field.
- `acceptance.json` — 15 machine checks, all of which must pass.

### Supporting evidence

| Path | Contents |
|---|---|
| `cases/<task_id>.json` | Executable case spec: probe, patch anchors, input payloads. |
| `probes/<task_id>.py` | Probe program run inside the project environment. |
| `evidence/<task_id>/` | `original/`, `patched/`, `patch.diff`, `enumeration.json` (full subset observation table), `enumeration_v2_legacy.json` (pre-fix record). |
| `test_map.json` | Upstream test coverage map per task. |
| `heldout/seal/` | HELDOUT seal created before inspection, with counts and per-entry flags. |

**Public release note.** The public export keeps `patch.diff`,
`enumeration.json` and the acceptance reports but removes the `original/` and
`patched/` directories, which contain third-party source bytes. Re-run
`reproduction/fetch_sdists.py` to obtain the upstream files, and apply
`patch.diff` to reconstruct the task; the enumeration and acceptance checks
then work as in the private repository. The HELDOUT split is not shipped at
all unless the export is built with `--keep-heldout`.

## 2. Relation definitions

For an input `x`:

- `obs(P+)` — observation of the original patched program.
- `obs(P−)` — observation after deleting `A`.
- `obs(S)` — observation after deleting `A` and every operation outside `S`.

**MSMS** — minimal non-empty sets `S` with `obs(S) == obs(P+)`. A set is
minimal when no proper subset is sufficient. The empty kept set, when
sufficient, suppresses non-empty MSMS and is never itself reported.

**MMBS** — minimal non-empty sets `D` with `obs(U \ D) != obs(P+)`, defined
only when `obs(P−) == obs(P+)`. Otherwise the input is `NOT_SEPARABLE` and
MMBS is not scored.

`UNKNOWN` (search did not finish) is never treated as `FALSE`.

The full acceptance criteria, including AC1–AC12 for source integrity,
insertion-only patches, line preservation and probe determinism, are in
`benchmark_v4_dataset/PROTOCOL.md`.

## 3. Composition

| | DEV | HELDOUT |
|---|---|---|
| Tasks | 25 | 25 |
| Projects | 10 | 17 |
| Declared inputs | 82 | 70 |
| — masking | 30 | 20 |
| — exposing | 25 | 20 |
| — control | 27 | 20 |
| — negative control | 0 | 10 |
| Candidate universes | 1–3 operations (31 tasks have 1) | same |

Mechanism counts (DEV): M1 8, M2 5, M3 3, M4 2, M5 2, M6 1, M7 2, M8 1, M9 1.
Mechanism counts (HELDOUT): M2 3, M3 3, M4 3, M5 3, M6 3, M7 1, M8 2, M9 2,
M10 5.

The scored DEV main table uses the 21-task primary cohort and its 25 masking
inputs. The 4 reused v2 tasks and the HELDOUT M10 controls are reported
separately and are never pooled with the main table.

## 4. Split policy and known overlap

HELDOUT was sealed before inspection and scored once, blind, after four
prediction files were frozen. The seal is at
`source_derived_v2_1/heldout/seal/heldout_v2_1_seal.json`.

Known limitations, disclosed rather than hidden:

- **Project overlap.** 6 of 25 HELDOUT tasks share a project with DEV
  (`attrs`, `isort`, `jsonschema`, `toml`, and two others); two tasks share the
  same file and target line as a DEV task.
- **Template overlap.** 9 of 25 HELDOUT tasks reuse a DEV construction
  template; 1 also shares the mechanism.
- **No double novelty.** No HELDOUT task has both a novel mechanism and a
  novel template.
- **Disjoint subsets.** 19 tasks are project-disjoint, 16 are
  template-disjoint, 14 satisfy both. Generalization claims must use these
  subsets and are descriptive only.

## 5. Reconstruction

The repository does not redistribute upstream source. Reconstruct a task's
`P+` file from pinned bytes:

```bash
# 1. Download and verify all 23 sdists used by v2.1
python reproduction/fetch_sdists.py

# 2. Check one task end to end (needs its virtual environment)
python benchmark_v4_dataset/tools/stage23_run.py env attrs-23.2.0
python benchmark_v4_dataset/tools/sd_acceptance.py \
  --case benchmark_v4_dataset/source_derived_v2_1/cases/sd_attrs_asdict_loop_m7.json \
  --root benchmark_v4_dataset/source_derived_v2_1
```

`sd_acceptance.py` re-extracts the sdist, checks that the original bytes match
`evidence/<task>/original/`, re-applies `patch.diff`, checks that the delivered
`patched/` bytes match the recorded hash, re-runs every probe and re-enumerates
the relation space independently. It does not import the construction code.

The pinned registry with URL, size and SHA-256 for all 70 discovery projects is
`benchmark_v4_dataset/discovery/manifest/source_registry.json`.

## 6. Independent verification

| Artifact | What it proves |
|---|---|
| `acceptance/<task_id>.json` | 15 structural, hash and relation checks per task |
| `results/source_derived_v2_1_acceptance_summary.json` | 50/50 accepted |
| `results/source_derived_v2_1_msms_mmbs.json` | relations recomputed by an independent implementation |
| `results/source_derived_v2_1_hash_manifest.json` | delivered / logical / source hashes per task |
| `results/source_derived_v2_1_diff.json` | v2 → v2.1 change record, no history masked |
| `results/source_derived_v2_1_project_split.json` | project-disjoint subset |
| `results/source_derived_v2_1_template_audit.json` | template-disjoint subset |

The v2.1 fixes relative to v2 were: MMBS no longer copied from MSMS, non-empty
minimal sets, corrected function metadata (3 tasks), concrete API strings for
HELDOUT, LF-normalised delivered bytes, and a v2.1 seal. The original v2
dataset and its acceptance records are retained unchanged under
`benchmark_v4_dataset/source_derived/`.

## 7. License and redistribution

Task definitions, patches, probes and documentation authored here are MIT
licensed. Upstream projects remain under their own licenses. The repository
does not ship upstream source trees; it ships URLs and hashes. Before
redistributing an sdist, read [THIRD_PARTY_LICENSES.md](THIRD_PARTY_LICENSES.md);
`docutils` in particular uses a compound license that requires carrying
`COPYING.txt` and the `licenses/` directory if its source is redistributed.

## 8. What this dataset does not claim

- It is not a sample of naturally occurring defects. Every `U` block is a
  researcher-constructed insertion, and `task.json` says so.
- It does not establish a claim over all legal inputs; every task is exact only
  over its declared finite input set.
- It does not establish a claim over operations outside the declared candidate
  universe.
- The M10 tasks are negative controls for a *specific candidate patch*, not
  evidence that `A` has no masking relation in general.
