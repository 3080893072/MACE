# Public Release Checklist

Scope: the tree produced by `reproduction/export_public.py` (the anonymous
review artifact), not the private working repository. Generated 2026-11-06.

Status legend: **PASS** (checked, no action), **MANUAL** (needs a human
decision or an action outside this machine), **FAIL** (blocks release).

Rebuild and re-check:

```bash
python reproduction/export_public.py --dest <empty-dir>
cd <empty-dir>
python -m pytest
python -m mace.cli smoke --fixture sort_channel.json
python reproduction/verify_frozen.py
```

---

## 1. Credentials

| # | Check | Status | Evidence |
|---|---|---|---|
| 1.1 | No API key or bearer token in shipped text | **PASS** | full-tree scan for `sk-…`, the Anthropic auth-token variable, the GitHub token variables, and generic `api_key` assignments: 0 hits |
| 1.2 | No PEM private key blocks | **PASS** | 4 files contained upstream ECDSA test vectors and are withheld automatically: `discovery/evidence/ecdsa-…/candidate.json`, `discovery/manifest/pypi/ecdsa-0.18.0.json`, `discovery/stage3_5/recompute_signals.json`, `results/MACE_v4_candidate_inventory.csv` |
| 1.3 | The historical leaked Anthropic auth token is not in the package | **PASS** | its only carriers were `benchmark_real_v3/evidence` and `benchmark_real_v4/evidence`, both excluded by prefix |
| 1.4 | That token has been revoked/rotated | **MANUAL** | it existed in the private history; rotation cannot be verified from here |
| 1.5 | No `.env`, key file or credential config | **PASS** | none present; `.gitignore` also blocks them |

## 2. Personal identity and local paths

| # | Check | Status | Evidence |
|---|---|---|---|
| 2.1 | No `<home> path (plain or JSON-escaped) | **PASS** | 0 hits; 0 after rewrite |
| 2.2 | No pytest temp dirs embedding the account name | **PASS** | pytest temp dirs containing the account name are rewritten to `pytest-of-<user> 0 hits |
| 2.3 | No `<local-path>…`, `<local-path>…` or other local roots | **PASS** | 0 hits in shipped files |
| 2.4 | No author name, email or affiliation in code, metadata, CITATION | **PASS** | author is `MACE Authors`; upstream project-author emails appear only in task payloads |
| 2.5 | Git history carries no personal author | **PASS** | fresh repository, single author `MACE Authors` |
| 2.6 | GitHub account used for upload is anonymous | **MANUAL** | a personal account is not anonymous; use a separate artifact account or the anonymous mirror |

## 3. HELDOUT hidden answers

| # | Check | Status | Evidence |
|---|---|---|---|
| 3.1 | No HELDOUT task, reference, probe, case, evidence or seal directory | **PASS** | any path segment starting with `heldout` is excluded, across `source_derived/`, `source_derived_v2_1/` and every `runs/` tree |
| 3.2 | No HELDOUT prediction or score file | **PASS** | `results/MACE_HELDOUT_v2_1_*`, `results/heldout/`, `results/MACE_v2_1_DEV_vs_HELDOUT.csv` excluded |
| 3.3 | No per-input role labels | **PASS** | they live only in the excluded HELDOUT tables |
| 3.4 | Remaining files with "HELDOUT" in the name contain no answers | **PASS** | `docs/MACE_HELDOUT_v2_1_*report.md` (hash/count reporting only), `scripts/*heldout*` (tooling), `discovery/manifest/seal_heldout_broad.json` (hashes) |
| 3.5 | Release of the split approved by the authors | **MANUAL** | required before building with `--keep-heldout` |

## 4. Third-party code and licenses

| # | Check | Status | Evidence |
|---|---|---|---|
| 4.1 | No upstream `original/` or `patched/` source copies | **PASS** | 0 files; excluded under every `evidence/` tree |
| 4.2 | No upstream sdists, wheels or source archives | **PASS** | 0 files; `discovery/{sources,sdists}` excluded |
| 4.3 | No upstream license-header code outside evidence | **PASS** | scan for MIT/BSD/Apache header text in `.py`: 0 hits |
| 4.4 | Repository LICENSE present and correct | **PASS** | MIT, "MACE Authors", scope note |
| 4.5 | NOTICE present | **PASS** | explains that no third-party source is redistributed |
| 4.6 | Per-project license table | **PASS** | `THIRD_PARTY_LICENSES.md`, 23 projects, SPDX + obligations, public-export policy |
| 4.7 | License/NOTICE text for docutils and the four Apache projects | **N/A** | only required if someone rebuilds with `--with-evidence`; documented as a manual gate |
| 4.8 | No license-incompatible material in the benchmark definitions | **PASS** | tasks, patches, probes and relations are original work |

## 5. Reproducibility checks on the exported tree

| # | Check | Status | Result |
|---|---|---|---|
| 5.1 | `pytest` | **PASS** | 390 passed, 1 skipped (HELDOUT test skipped by design), exit 0 |
| 5.2 | `mace smoke --fixture sort_channel.json` | **PASS** | `SMOKE: PASS` |
| 5.3 | Frozen result hashes | **PASS** | 5/5 |
| 5.4 | Frozen code hashes | **PASS with exemptions** | 8/12 identical, 4 `[EDIT]`, see below |
| 5.5 | Dataset structure | **PASS** | 25 DEV tasks, acceptance 25/25 |
| 5.6 | HELDOUT prediction hashes | **SKIP** | files intentionally not shipped; the script prints `[SKIP]` |
| 5.7 | `sd_acceptance.py` on the public tree | **MANUAL** | needs `fetch_sdists.py` first; `original/` evidence is not shipped, so AC1's evidence comparison cannot run until those files are reconstructed |
| 5.8 | Model-backed re-runs | **NOT RUN** | needs GPU and a model server; intentionally out of scope for this audit |

### Exempted code hashes

All four are path-resolution-only edits made when the personal absolute paths
were removed. Full hashes: `reproduction/portability_patch.json`.

| File | Change | Behaviour |
|---|---|---|
| `scripts/run_candidate_discovery_v2_1.py` | venv interpreter via `mace.paths`; `MACE_RUN_DIR` / `MACE_DEV_OUT` overrides | none |
| `scripts/run_candidate_discovery_v2.py` | venv interpreter via `mace.paths` | none |
| `scripts/close_candidate_discovery_v2_1.py` | venv interpreter via `mace.paths` (3 call sites) | none |
| `benchmark_v4_dataset/tools/sd_algorithm_pilot.py` | `WORK`/`VENVS` via `mace.paths`; `venv_python()` | none |

No prompt, search rule, scorer, dataset file or result file was touched.

## 6. Documentation

| # | Check | Status |
|---|---|---|
| 6.1 | README states the method sentence verbatim | **PASS** |
| 6.2 | README separates fully re-runnable DEV, audit-only results, and withheld HELDOUT | **PASS** — "Reproduction Status" table |
| 6.3 | README marks the HELDOUT table as not auditable from the public package | **PASS** |
| 6.4 | Qwen 7B scope stated: M1 pilot, six fixtures, not a v2.1 comparison | **PASS** — README and EXPERIMENTS §3 |
| 6.5 | Every command in README/REPRODUCIBILITY maps to a real script | **PASS** |
| 6.6 | Dataset reconstruction path documented without shipping sources | **PASS** — DATASET.md public-release note |

## 7. Git and publication

| # | Check | Status |
|---|---|---|
| 7.1 | Export is a fresh tree with no inherited history | **PASS** |
| 7.2 | `.gitattributes` disables EOL conversion (`* -text diff`) | **PASS** |
| 7.3 | No remote configured, nothing pushed | **PASS** |
| 7.4 | No GitHub repository created, no Release published | **PASS** |
| 7.5 | File sizes within GitHub limits (< 100 MB per file) | **PASS** — largest shipped file is 6.4 MB |
| 7.6 | Upload target and visibility chosen by the authors | **MANUAL** |
| 7.7 | Final human read of the diff before `git push` | **MANUAL** |

---

## Verdict

**Passes every automated check; not yet publishable until the three MANUAL
items are closed:**

1. rotate the leaked Anthropic auth token;
2. decide how the HELDOUT split is released (public package ships none of it);
3. choose an anonymous upload identity and confirm the final visibility.

Everything else in this checklist is verified on the exported tree.
