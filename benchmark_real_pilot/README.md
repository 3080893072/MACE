# Real-source feasibility pilot

This directory contains three extracted real-source tasks for testing whether
operation-level semantic masking can be asserted and checked outside synthetic
controlled programs.

## What is here

- `tasks/` — exact function/class excerpts from public releases.  The target
  line carries `# TARGET_A`; the masking operation is a later assignment to
  the same local name.
- `specs.py` — frozen domains, upstream line numbers, provenance, and ports of
  released test assertions.
- `candidates.json` — 18 reviewed candidates (3 accepted, 15 rejected) and the
  screening rules fixed before review.
- `run.py` — runs P+ (target present) and P− (target replaced by `pass`),
  disables the candidate operation in both, and records observations,
  snapshots, and relation checks.
- `results/results.json` — generated evidence.
- `provenance.json` — package/source hashes and the upstream-suite blocker.
- `evidence/upstream_test_search.md` — static coverage evidence.

## Run

From the repository root:

```bash
python -I benchmark_real_pilot/run.py
```

Expected summary:

```text
candidates_reviewed: 18
real_tasks_built: 3
tasks_with_verified_masking_relation: 3
relation_counts: {"independent": 3}
upstream_suite_executed: false
```

The runner executes the extracted task bodies only.  It does not import the
downloaded packages and does not run the upstream pytest suites.

## Important limits

- Deletion is hypothetical; no upstream commit is claimed.
- Each task has one source-read candidate operation B and one confirmed
  `independent` relation.  No exhaustive search for every relation was done.
- `PARTIAL_GROUND_TRUTH`: the relation is execution-confirmed on the extracted
  excerpt, but the whole upstream suite was not executed in this round.
- The local line numbers are excerpt line numbers; upstream line numbers are
  in `specs.py` and `provenance.json`.

## Protocol v2: task tests vs project suite

Test organization is now split into two scopes; see
[`docs/benchmark_test_protocol_v2.md`](../docs/benchmark_test_protocol_v2.md)
for the full protocol, evidence, and limits.

- **`T_task`** is the frozen, source-associated set of original upstream tests.
  Daily Benchmark runs use only this set.  It was selected from P+ trace
  coverage before any P− result and is never re-selected by P− outcomes.
- **`T_project`** is the project's applicable original suite.  It is run once
  for qualification, cached by source/environment/test-scope/variant, and not
  repeated for every model answer.

Frozen counts: click `_truncate_visible` 1 test; Werkzeug `HeaderSet.update`
3 tests; Werkzeug `url_unparse` 18 tests.  All 22 selected tests hit the target
A line under P+.  Protocol v2 does **not** change the earlier qualification
conclusion: only click's project suite survives deletion of A.

```bash
# Freeze T_task (creation time; P+-only input)
python -m benchmark_real_pilot.protocol_v2.run freeze

# Daily Benchmark: only frozen T_task
python -m benchmark_real_pilot.protocol_v2.run task

# Qualification manifest from cached T_project evidence
python -m benchmark_real_pilot.protocol_v2.run manifest
```
