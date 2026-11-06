# MACE Benchmark v3 — Public Development/Pilot Package

**Label: DEVELOPMENT/PILOT.**  These five tasks are for development and
pilot scoring.  They are not a future held-out test set, and future MACE or
Qwen scores must not be used to modify their hidden answers.

The benchmark asks for operation-level masking/breaking relations in real
open-source Python programs.  Each task publishes:

* the target source file and exact location of operation A;
* the frozen original-test list `T_task`;
* the legal input contract and the shape of the observation;
* the submission format.

Each task hides the reference candidate-operation locations, witnesses,
enable/disable matrices and expected relations.  The scorer re-executes every
submitted witness against fresh P+/P− variants; it does not trust a submitted
expected result.

## Tasks

| task_id | project | target source |
|---|---|---|
| `jinja2_bytecode_cache_read` | Jinja2 3.1.3 | `src/jinja2/loaders.py` |
| `werkzeug_bind_server_name_lower` | Werkzeug 2.2.3 | `src/werkzeug/routing/map.py` |
| `werkzeug_filestorage_stream_name` | Werkzeug 2.2.3 | `src/werkzeug/datastructures.py` |
| `werkzeug_get_host_default_empty` | Werkzeug 2.2.3 | `src/werkzeug/sansio/utils.py` |
| `werkzeug_secure_filename_ascii_filter` | Werkzeug 2.2.3 | `src/werkzeug/utils.py` |

## Files

* `tasks/<task_id>/task.json` — public metadata and input contract.
* `tasks/<task_id>/source/...` — the original target source file.
* `tasks/index.json` — task index.
* `input_contracts.json` — all public input contracts.
* `submission_format.md` — claim schema and status vocabulary.

## Scope

The hidden candidate universe U is not disclosed.  The scorer evaluates only
operations at submitted source locations that match U; other locations are
reported `UNVERIFIED`.  Minimality is exact over U and the submitted finite
inputs, not over the whole legal input domain.  No claim is made that the
five tasks exhaust all possible operation-level relations.
