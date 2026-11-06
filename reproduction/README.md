# Reproduction helpers

| Script | Purpose | Network | GPU |
|---|---|---|---|
| `verify_frozen.py` | Audit frozen results, predictions, code hashes and dataset structure | no | no |
| `fetch_sdists.py` | Download and verify the pinned upstream sdists | yes | no |
| `export_public.py` | Build a filtered public-release tree | no | no |
| `portability_patch.json` | Record of the four path-only code edits and their before/after hashes | — | — |

## Typical sequence

```bash
# CPU only: prove the shipped artifacts are the reported ones
python reproduction/verify_frozen.py

# CPU only: recompute HELDOUT scores without touching the frozen files
MACE_SCORE_OUT=runs/local_scores python scripts/score_heldout_v2_1.py

# Network + CPU: fetch upstream sources for dataset acceptance or a method run
python reproduction/fetch_sdists.py
```

## Public export

```bash
python reproduction/export_public.py --dest /tmp/mace_public --dry-run
python reproduction/export_public.py --dest /tmp/mace_public
```

The default export removes the HELDOUT split and all HELDOUT-derived tables,
the upstream `original/` and `patched/` source copies under every evidence
tree, the bulk legacy evidence trees, downloaded sources and caches. Use
`--with-evidence` only when the per-project LICENSE/NOTICE obligations are met
(see `THIRD_PARTY_LICENSES.md`). It scans every shipped text
file for credential-like strings and fails if it finds one, and rewrites
absolute local home/repository paths in the exported copy (33 files on the
current tree) to `<home>` / `<local-path>`. Use
`--keep-heldout` only when the paper explicitly releases the HELDOUT split.

The export is a plain directory copy, not a git repository. For a
double-anonymous artifact, initialise a fresh repository from it so that the
original commit history and author metadata are not carried over.
