# MACE Benchmark v3 — Submission Format

This is a **DEVELOPMENT/PILOT** package.  It is not a future held-out test
set.  Submit one JSON object per task.

## Envelope

```json
{
  "submission_id": "optional-string",
  "task_id": "one-of-the-five-public-task-ids",
  "claims": [ ... ]
}
```

## Operation locations

Name an operation by a project-relative source location, not by an internal
benchmark id:

```json
{"file": "src/example/module.py", "line": 123}
```

Optional fields:

* `end_line` — last line of a multi-line statement or block.  If omitted, the
  location is treated as a single line.
* `code` — the exact source text.  If supplied, the scorer rejects a mismatch
  as `INVALID`.

Operations outside the hidden declared candidate universe are reported
`UNVERIFIED`; they are not silently treated as false.

## Claim types

### 1. Exposing counterexample

```json
{"type": "EXPOSING_COUNTEREXAMPLE", "input": { ... }}
```

The scorer executes P+ and P− on the submitted legal input.  Both must
produce an observation and the observations must differ.  A single such
witness is `WITNESS_VERIFIED`, never a whole-domain claim.

### 2. Minimal sufficient masking set (MSMS)

```json
{
  "type": "MSMS",
  "input": { ... },
  "operations": [{"file": "...", "line": 123}]
}
```

The scorer enumerates every subset of the declared hidden candidate universe
U.  The claim is verified only if the submitted set `S` satisfies
`Only(S) = Masked_strict(U \ S)` and no nonempty proper subset does.  With
`inputs` (a list of 2–12 legal inputs) instead of `input`, every submitted
input must verify; the status is then `FINITE_DOMAIN_EXACT` **over that finite
submitted list**, still not over the legal input domain.

### 3. Minimal breaking set (MMBS)

Same fields as MSMS, with `"type": "MMBS"`.  The submitted set `S` must
satisfy `Break(S) = Exposed(S)` and no proper subset (including the empty
set) may expose.  The input must already be masked at EMPTY.

### 4. Prerequisite-conditioned breaking

```json
{
  "type": "PREREQUISITE_BREAKING",
  "input": { ... },
  "control_input": { ... },
  "operations": [{"file": "...", "line": 123}],
  "prerequisite": "human-readable description"
}
```

The set must be a minimal breaking set on `input`, and must not break on
`control_input`.  The control may be an exposing input: that shows the
prerequisite is absent.  This is a two-witness conditional result; it is not
promoted to a domain-wide implication.

### 5. Conditional correctness

```json
{
  "type": "CONDITIONAL_CORRECTNESS",
  "condition_input": { ... },
  "conclusion_input": { ... },
  "operations": [{"file": "...", "line": 123}]
}
```

The set must break on the condition input and not break on the conclusion /
control input.  Again this is checked at two submitted points only.

### 6. Proven

`{"type": "PROVEN", "statement": "...", "proof": {...}}` is accepted
syntactically but scored `UNVERIFIED`: this package has no formal proof
checker and never assigns `PROVEN` from execution alone.

## Statuses

* `WITNESS_VERIFIED` — execution confirmed the claim on submitted witness(es).
* `FINITE_DOMAIN_EXACT` — every submitted finite input verified, with all
  subsets of U enumerated.  Not the legal input domain.
* `PROVEN` — reserved; not assigned without a formal checker.
* `FALSE` — execution contradicts the claim.
* `INVALID` — malformed claim or illegal input.
* `UNVERIFIED` — operation outside U, or a proof check this scorer cannot run.
* `UNSUPPORTED` — unknown claim type.
* `DUPLICATE` — exact duplicate of an earlier claim; no credit.

## Duplicate and scope rules

Exact duplicate claims are `DUPLICATE` and earn no credit.  A relation already
credited by an earlier claim does not earn credit again when repeated on
another input.  `score.credited_relations` counts unique relation keys, not
the number of allowed attempts.  Minimality is exact only over the declared
U and the submitted finite inputs.  If U is incomplete, attribution is
limited to U and does not claim that every possible operation was found.
