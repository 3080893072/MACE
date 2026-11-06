# Third-Party Licenses and Redistribution Notes

MACE-Bench tasks are derived from 23 released PyPI projects. The repository
does **not** bundle their source trees or sdists. It ships:

- task definitions, researcher patches, probes and reference relations
  (authored here, MIT licensed);
- pinned sdist URLs, sizes and SHA-256 in
  `benchmark_v4_dataset/discovery/manifest/source_registry.json`;
- a download script, `reproduction/fetch_sdists.py`.

The **private working repository** additionally keeps one original and one
patched copy of the single source file each task targets, under
`benchmark_v4_dataset/source_derived_v2_1/evidence/<task>/original|patched/`
(and the same for `benchmark_v4_dataset/evidence/` on the v2 layer). Those
copies are third-party code. The **public export excludes them by default**;
see "Public export policy" below.

The machine-readable audit is
`benchmark_v4_dataset/results/source_derived_v2_1_license_manifest.csv`
(columns include `spdx_license`, `license_files`, `copyright_notice_required`,
`redistribution_conditions` and a per-project recommendation).

## Project licenses

| Project | Version(s) | SPDX | Source redistribution | Required with redistribution |
|---|---|---|---|---|
| attrs | 23.2.0 | MIT | permitted | license + copyright notice |
| coverage | 7.4.0 | Apache-2.0 | permitted | LICENSE, NOTICE |
| docutils | 0.20.1 | compound: public domain + PSF-2.1.1 + BSD-2-Clause + GPL-3.0 | permitted | `COPYING.txt` and `licenses/`, all notices |
| h11 | 0.14.0 | MIT | permitted | license + copyright notice |
| humanize | 4.9.0 | MIT (declared) | permitted | upstream MIT text + notice (sdist ships no LICENSE file) |
| isort | 5.13.2 | MIT | permitted | license + copyright notice |
| jedi | 0.19.1 | MIT | permitted | license + copyright notice |
| jsonschema | 4.20.0 | MIT | permitted | license + copyright notice |
| Markdown | 3.5.1 | BSD-3-Clause | permitted | license + copyright notice |
| msgpack | 1.0.7 | Apache-2.0 | permitted | LICENSE, NOTICE |
| multidict | 6.0.4 | Apache-2.0 | permitted | LICENSE, NOTICE |
| networkx | 3.2.1 | BSD-3-Clause | permitted | `LICENSE.txt` + notice |
| parso | 0.8.3 | MIT | permitted | license + copyright notice |
| passlib | 1.7.4 | BSD-3-Clause | permitted | license + copyright notice |
| pycodestyle | 2.11.1 | MIT | permitted | license + copyright notice |
| Pygments | 2.17.2 | BSD-2-Clause | permitted | license + copyright notice |
| PyYAML | 6.0.1 | MIT | permitted | license + copyright notice |
| requests | 2.31.0 | Apache-2.0 | permitted | `LICENSE` and `NOTICE` |
| simplejson | 3.19.2 | MIT | permitted | license + copyright notice |
| sqlparse | 0.4.4 | BSD-3-Clause | permitted | license + copyright notice |
| tabulate | 0.9.0 | MIT | permitted | license + copyright notice |
| toml | 0.10.2 | MIT | permitted | license + copyright notice |
| urllib3 | 2.1.0 | MIT | permitted | `LICENSE.txt` + notice |

Versions are the exact ones used by the v2.1 tasks; the 70-project discovery
registry contains additional projects that are not part of v2.1.

## Notes

**docutils.** The sdist declares a compound license: public-domain components,
PSF-2.1.1, BSD-2-Clause and GPL-3.0. If you redistribute the sdist or any
substantial part of it, carry `COPYING.txt` and the `licenses/` directory and
preserve every notice. The safer route, used by
`reproduction/fetch_sdists.py`, is to redistribute only the pinned URL and the
patch.

**humanize.** MIT is declared in `PKG-INFO`, but the sdist contains no
`LICENSE` file (the file is named `LICENCE` in some releases). Include the
upstream MIT text and copyright notice explicitly.

**Apache-2.0 projects.** `coverage`, `msgpack`, `multidict` and `requests`
require the `NOTICE` file to travel with any redistribution of their source.

**Single-file evidence.** `evidence/<task>/original/` and `patched/` each hold
one upstream file. They remain under the upstream license; the corresponding
notice is the one listed above.

**Public export policy.** `reproduction/export_public.py` excludes every
`original/` and `patched/` directory under any `evidence/` tree by default, so
the public package redistributes no third-party source at all. The task
definitions, `patch.diff`, `enumeration.json` and acceptance reports stay, and
`reproduction/fetch_sdists.py` plus the recorded patch reconstructs the files
byte-for-byte. `--with-evidence` re-includes them for a private or
license-cleared distribution; do not use it without shipping the LICENSE and
NOTICE text of every affected project.

The excluded set currently covers docutils (compound, includes a GPL-3.0
component) and the four Apache-2.0 projects (`coverage`, `msgpack`,
`multidict`, `requests`), whose NOTICE files are not present in this
repository and must be taken from the sdists before any redistribution.

**No license for the benchmark composition itself is inherited.** The task
definitions, patches, probes, relations and documentation are original work
released under the repository's MIT license.

## What is deliberately absent

- No full upstream source tree (`discovery/sources/` is generated locally and
  git-ignored).
- No sdist archives (`discovery/sdists/` is generated locally).
- No vendored third-party library code in `mace/` or `scripts/`.
