# Baseline report index

The full Chinese development-pilot report is:

`reports/MACE_taskB_baseline_2026-11-02.md`

Machine-readable summary:

- `benchmark_baseline/runs/baseline_summary.json`
- `benchmark_baseline/runs/baseline_summary_stdout.txt`

Frozen protocol:

- `benchmark_baseline/freeze.json`

Per-method raw artifacts:

- `benchmark_baseline/runs/direct/`
- `benchmark_baseline/runs/validator/`
- `benchmark_baseline/runs/ast/`

Headline (development/pilot only, not independent generalization):

| method | claims | correct execution status | credited unique relations | wrong/unverified | model calls | tokens | wall seconds |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| direct | 5 | 1 | 1 | 4 | 5 | 24,229 | 148.854 |
| validator | 5 | 1 | 1 | 4 | 11 | 53,655 | 421.786 |
| ast | 36 | 30 | 15 | 6 | 0 | 0 | 1,531.1 |

Full MACE: `UNSUPPORTED_INTERFACE`, score `null`; no 0% is reported.
