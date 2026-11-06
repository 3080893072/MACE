# MACE v2.1 — HELDOUT qualitative examples: candidate excerpts (draft)

Purpose: decide whether any model output belongs in the paper, and if so which
excerpts. Three cases are proposed under a fixed selection rule: one Full MACE
success where C0 failed, one Full MACE failure, one Direct Qwen invalid output.
All text below is **verbatim** from the stored raw response; nothing was edited
or regenerated.

| # | Task | Method | HELDOUT outcome | Source file | prompt sha256 (16) |
|---|---|---|---|---|---|
| 1 | `sd_jedi_param_hyphen_m2` | Full MACE | exact (C0: not exact) | `runs/heldout_v2_1_blind/raw/sd_jedi_param_hyphen_m2.json` | `25e3fbcb040cb915` |
| 2 | `sd_simplejson_htmlamp_m4` | Full MACE | not exact (2 sets, no block match) | `runs/heldout_v2_1_blind/raw/sd_simplejson_htmlamp_m4.json` | `5812a83c977841e9` |
| 3 | `sd_passlib_hashname_m2` | Direct Qwen 32B | INVALID_OUTPUT (12/12 rejected) | `runs/direct_qwen_v2_1/heldout/sd_passlib_hashname_m2.json` | `3a7d38c7118a0e55` |

## 1. Full MACE, verified cooperative set (verbatim `candidate_sets`)

```json
[
 {
  "kept_operations": [
   "jedi/inference/compiled/value.py:570-570",
   "jedi/inference/compiled/value.py:573-573"
  ],
  "relation_type": "cooperative_leg",
  "masking_condition": "true",
  "rationale": "Operations 570 and 573 together ensure that hyphens are replaced, making the deletion of operation 568 unobservable."
 }
]
```

Scoring: hidden MSMS = `[["U1","U2"]]`; predicted set projects to `{U1,U2}`;
strict exact. C0 returned only `{U1}` on the same input.

## 2. Full MACE, verified under its own universe but not the hidden relation (verbatim)

```json
[
 {
  "kept_operations": [
   "simplejson/encoder.py:419-419",
   "simplejson/encoder.py:420-420"
  ],
  "relation_type": "cooperative_leg",
  "masking_condition": "chunk contains '<' or '>'",
  "rationale": "Keeping both '<' and '>' replacements masks the effect of '&' replacement."
 }
]
```

Scoring: hidden MSMS = `[["U1"],["U2"]]`; both predicted operations fall
outside every hidden block, so the set projects to no block and is not exact.

## 3. Direct Qwen, rejected proposal (verbatim, first relation)

```json
{
 "file": "passlib/crypto/digest.py",
 "line": 196,
 "text": "if hashlib_name in _hashlib_backends:"
}
```
```json
"rationale": "Deleting these lines makes the deletion of A unobservable because the function will not reach the point where hashlib_name is used."
```

Runtime rejection record (verbatim, first rejected entry): `reason` =
`text_mismatch`. All 12 relations in this task were rejected; the task is
`INVALID_OUTPUT` and is scored as empty in every denominator.

A second, shorter example of the same failure mode is
`sd_pycodestyle_paths_nc` (line 1794, proposed text `"if path:"`,
`text_mismatch`, 12/12 rejected).

## How these should be used (if at all)

- Main text: none of the raw JSON. At most a 3-line case row (input role,
  hidden set, predicted set, exact / not exact).
- Appendix: excerpt 1 for the mechanism, excerpt 2 to show the method is not
  cherry-picked, excerpt 3 for the Direct-LLM failure mode.
- The `rationale` strings are **model output, not evidence**. In excerpt 1 the
  prose names the deleted operation (568) correctly, but that was not checked
  for every task and is not what the score depends on: the claim rests on
  probe verification and block projection, not on the prose. Quote the prose
  only as "what the model produced", never as the explanation of why the
  relation holds.
- Always cite task id + prompt hash prefix + raw file path so the excerpt can
  be re-derived byte-for-byte.

No model was re-run to produce this file; it is extracted from frozen raw
records only.
