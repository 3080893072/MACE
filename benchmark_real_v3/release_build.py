"""Build the public task package, hidden evidence package and SHA-256 manifest.

The public package contains only what a solver may see: the original source
file, A's exact location, the frozen T_task list, the legal-input contract and
the submission format.  Hidden reference positions, witnesses, matrices and
acceptance logs live under ``release/HIDDEN``.

Run after acceptance and scoring tests pass::

    python -m benchmark_real_v3.release_build
    python -m benchmark_real_v3.release_build --check-only
"""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

from benchmark_real_v3.config import EVIDENCE, PROJECTS, V3
from benchmark_real_v3.scoring.contracts import CONTRACTS

RELEASE = V3 / "release"
PUBLIC = RELEASE / "PUBLIC"
HIDDEN = RELEASE / "HIDDEN"
TASKS = V3 / "tasks"
QUALIFIED = TASKS / "qualified_tasks.json"
ACCEPTANCE = EVIDENCE / "acceptance" / "acceptance_report.json"
LEAK_REPORT = EVIDENCE / "acceptance" / "leak_report.json"
T_TASK_TRACE = EVIDENCE / "acceptance" / "t_task_execution.json"
CORRECTIONS = EVIDENCE / "acceptance" / "corrections.json"
SCORING_TESTS = V3 / "scoring" / "tests" / "test_scoring.py"
ACCEPT_ROOT = Path("<local-path>")
VERSION = "v3.0-dev-pilot-2026-11-02"
LABEL = "DEVELOPMENT/PILOT"


def _sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def _copy(source: Path, destination: Path) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, destination)


def _operations(spec: Dict[str, Any]) -> List[Dict[str, Any]]:
    result = []
    for op in spec["candidate_universe"]:
        if op.get("kind") == "block":
            first = int(op["first_line"])
            last = int(op["last_line"])
            line = first
        else:
            first = last = int(op["line"])
            line = first
        result.append({
            "id": op["id"],
            "file": op["file"],
            "line": line,
            "first_line": first,
            "last_line": last,
            "kind": op.get("kind", "statement"),
            "code": op["code"],
            "role": op.get("role", ""),
        })
    return result


def _op_location(op: Dict[str, Any], *, end_line: bool = False) -> Dict[str, Any]:
    if op.get("kind") == "block":
        return {
            "file": op["file"],
            "line": int(op["first_line"]),
            "end_line": int(op["last_line"]),
            "code": op["code"],
        }
    return {"file": op["file"], "line": int(op["line"]), "code": op["code"]}


def _reference_claims(spec: Dict[str, Any], matrix: Dict[str, Any]) -> List[Dict[str, Any]]:
    claims: List[Dict[str, Any]] = []
    for iid, data in matrix["inputs"].items():
        if data["role"] == "exposing":
            claims.append({
                "type": "EXPOSING_COUNTEREXAMPLE",
                "input": data["payload"],
                "expected_status": "WITNESS_VERIFIED",
                "witness_id": iid,
            })
        if data["role"] == "masking":
            for relation in data["msms"]:
                ops = [op for op in spec["candidate_universe"] if op["id"] in relation]
                claims.append({
                    "type": "MSMS",
                    "input": data["payload"],
                    "operations": [_op_location(op) for op in ops],
                    "expected_status": "WITNESS_VERIFIED",
                    "witness_id": iid,
                })
            for relation in data["mmbs"]:
                ops = [op for op in spec["candidate_universe"] if op["id"] in relation]
                claims.append({
                    "type": "MMBS",
                    "input": data["payload"],
                    "operations": [_op_location(op) for op in ops],
                    "expected_status": "WITNESS_VERIFIED",
                    "witness_id": iid,
                })
    if spec["task_id"] == "werkzeug_bind_server_name_lower":
        op = spec["candidate_universe"][0]
        claims.append({
            "type": "PREREQUISITE_BREAKING",
            "input": matrix["inputs"]["mask_subdomain_supplied"]["payload"],
            "control_input": matrix["inputs"]["expose_subdomain_path"]["payload"],
            "operations": [_op_location(op)],
            "prerequisite": "subdomain is not None",
            "expected_status": "WITNESS_VERIFIED",
        })
    return claims


def _public_task(
    spec: Dict[str, Any],
    qualified: Dict[str, Any],
    source_sha: str,
    project_sha: str,
) -> Dict[str, Any]:
    target = spec["target_operation"]
    return {
        "schema": "mace_benchmark_v3_public_task",
        "label": LABEL,
        "task_id": spec["task_id"],
        "project": spec["source_version"],
        "project_id": spec["project_id"],
        "difficulty": spec.get("difficulty"),
        "source_file": target["file"],
        "source_sha256": source_sha,
        "project_source_tree_sha256": project_sha,
        "target_operation": {
            "file": target["file"],
            "line": int(target["line"]),
            "code": target["code"],
            "function": target.get("function"),
        },
        "analysis_scope": (
            "The public package contains the target source file only.  The "
            "hidden candidate universe is not disclosed.  Operations outside "
            "it cannot be attributed by the scorer and are reported "
            "UNVERIFIED."
        ),
        "test_scope": spec["test_scope"],
        "frozen_t_task": qualified["t_task"],
        "frozen_t_task_count": len(qualified["t_task"]),
        "legal_input_contract": CONTRACTS[spec["task_id"]],
        "observation_contract": CONTRACTS[spec["task_id"]]["observation"],
        "submission_format": "submission_format.md",
        "source_path": f"source/{target['file']}",
        "not_claimed": spec.get("scope", {}).get("not_claimed", []),
    }


def _hidden_reference(
    spec: Dict[str, Any],
    qualified: Dict[str, Any],
    matrix: Dict[str, Any],
    acceptance_task: Dict[str, Any] | None,
    project_sha: str,
) -> Dict[str, Any]:
    suite = {}
    t_task = {}
    if acceptance_task:
        suite = acceptance_task.get("checks", {}).get("p_minus_full_suite", {})
        t_task = acceptance_task.get("checks", {}).get("t_task_on_p_plus", {})
    return {
        "schema": "mace_benchmark_v3_hidden_reference",
        "label": LABEL,
        "release_version": VERSION,
        "task_id": spec["task_id"],
        "project_id": spec["project_id"],
        "project": PROJECTS[spec["project_id"]]["project"],
        "version": PROJECTS[spec["project_id"]]["version"],
        "source_version": spec["source_version"],
        "project_source_tree_sha256": project_sha,
        "target_operation": spec["target_operation"],
        "deletion_method": spec["deletion_method"],
        "probe": spec["probe"],
        "test_scope": spec["test_scope"],
        "frozen_t_task": qualified["t_task"],
        "candidate_universe": _operations(spec),
        "universe_notes": spec.get("universe_notes", []),
        "witnesses": {
            iid: {
                "role": data["role"],
                "payload": data["payload"],
            }
            for iid, data in matrix["inputs"].items()
        },
        "reference_relations": {
            iid: {
                "role": data["role"],
                "msms": data["msms"],
                "mmbs": data["mmbs"],
                "masked_strict_EMPTY": data["masked_strict"].get("EMPTY"),
                "exposed_EMPTY": data["exposed"].get("EMPTY"),
                "exposed_with_universe_disabled": data["exposed"],
            }
            for iid, data in matrix["inputs"].items()
        },
        "reference_claims": _reference_claims(spec, matrix),
        "partial_truth": {
            "exposing_witnesses": [
                iid for iid, data in matrix["inputs"].items()
                if data["role"] == "exposing"],
            "masking_witnesses": [
                iid for iid, data in matrix["inputs"].items()
                if data["role"] == "masking"],
            "confirmed_level": (
                "FINITE_DOMAIN_EXACT over the frozen witnesses and all "
                "subsets of the declared U; never PROVEN over the legal "
                "input domain."),
            "attribution_scope": (
                f"Exact only for the {len(spec['candidate_universe'])} "
                "declared candidate operation(s) and executed inputs.  No "
                "claim that all possible B/C/D/E operations were found."),
        },
        "scope": spec.get("scope", {}),
        "acceptance": {
            "verdict": (acceptance_task or {}).get("verdict", "NOT_RUN"),
            "errors": (acceptance_task or {}).get("errors", []),
            "p_minus_suite_summary": suite.get("summary"),
            "p_minus_suite_success": suite.get("success"),
            "p_minus_suite_log": (
                f"evidence/{spec['task_id']}_p_minus_full.log"),
            "t_task_summary": t_task.get("summary"),
            "t_task_success": t_task.get("success"),
        },
        "evidence": {
            "matrix": f"evidence/{spec['task_id']}_matrix.json",
            "independent_matrix": (
                f"evidence/{spec['task_id']}_independent_matrix.json"),
            "p_minus_log": f"evidence/{spec['task_id']}_p_minus_full.log",
            "p_minus_junit": (
                f"evidence/{spec['task_id']}_p_minus_full.junit.xml"),
            "t_task_log": f"evidence/{spec['task_id']}_t_task.log",
        },
    }


def _submission_format() -> str:
    return """# MACE Benchmark v3 — Submission Format

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
`Only(S) = Masked_strict(U \\ S)` and no nonempty proper subset does.  With
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
"""


def build() -> Dict[str, Any]:
    qualified_payload = json.loads(QUALIFIED.read_text(encoding="utf-8"))
    qualified = {
        task["task_id"]: task for task in qualified_payload.get("tasks", [])
    }
    acceptance_payload = (
        json.loads(ACCEPTANCE.read_text(encoding="utf-8"))
        if ACCEPTANCE.exists() else {"tasks": []}
    )
    acceptance = {
        task["task_id"]: task for task in acceptance_payload.get("tasks", [])
    }
    if RELEASE.exists():
        shutil.rmtree(RELEASE)
    PUBLIC.mkdir(parents=True)
    HIDDEN.mkdir(parents=True)
    public_index = []

    for task_dir in sorted(p for p in TASKS.iterdir() if p.is_dir()):
        spec_path = task_dir / "spec.json"
        if not spec_path.exists():
            continue
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        task_id = spec["task_id"]
        if task_id not in qualified:
            continue
        q = qualified[task_id]
        matrix_path = EVIDENCE / f"{task_id}_matrix.json"
        matrix = json.loads(matrix_path.read_text(encoding="utf-8"))
        cfg = PROJECTS[spec["project_id"]]
        source = cfg["root"] / spec["target_operation"]["file"]
        source_sha = _sha256_file(source)
        project_sha = json.loads(
            (EVIDENCE / "project_source_hashes.json").read_text(
                encoding="utf-8"))[spec["project_id"]]

        public_dir = PUBLIC / "tasks" / task_id
        _copy(source, public_dir / "source" / spec["target_operation"]["file"])
        _write_json(
            public_dir / "task.json",
            _public_task(spec, q, source_sha, project_sha))
        public_index.append({
            "task_id": task_id,
            "project": spec["source_version"],
            "difficulty": spec.get("difficulty"),
            "source_file": spec["target_operation"]["file"],
            "target_operation": public_dir.relative_to(PUBLIC).as_posix()
            + "/task.json",
        })

        hidden_dir = HIDDEN / "tasks" / task_id
        hidden = _hidden_reference(
            spec, q, matrix, acceptance.get(task_id), project_sha)
        _write_json(hidden_dir / "reference.json", hidden)
        evidence_dir = HIDDEN / "evidence"
        _copy(matrix_path, evidence_dir / f"{task_id}_matrix.json")
        independent = ACCEPT_ROOT / task_id / "independent_matrix.json"
        if independent.exists():
            _copy(
                independent,
                evidence_dir / f"{task_id}_independent_matrix.json")
        for suffix in ("p_minus_full.log", "p_minus_full.junit.xml",
                       "t_task.log"):
            candidate = ACCEPT_ROOT / task_id / f"{task_id}_{suffix}"
            if candidate.exists():
                _copy(candidate, evidence_dir / f"{task_id}_{suffix}")

    _write_json(
        PUBLIC / "tasks" / "index.json",
        {
            "schema": "mace_benchmark_v3_public_index",
            "label": LABEL,
            "release_version": VERSION,
            "task_count": len(public_index),
            "tasks": public_index,
        })
    _write_json(
        PUBLIC / "input_contracts.json",
        {
            "schema": "mace_benchmark_v3_input_contracts",
            "label": LABEL,
            "contracts": CONTRACTS,
        })
    (PUBLIC / "submission_format.md").write_text(
        _submission_format(), encoding="utf-8")
    (PUBLIC / "README.md").write_text(
        _public_readme(public_index), encoding="utf-8")

    _copy(QUALIFIED, HIDDEN / "evidence" / "qualified_tasks.json")
    for name in (
        "qualification_registry.json", "funnel_summary.json",
        "project_source_hashes.json",
    ):
        source = EVIDENCE / name
        if source.exists():
            _copy(source, HIDDEN / "evidence" / name)
    if ACCEPTANCE.exists():
        _copy(ACCEPTANCE, HIDDEN / "evidence" / "acceptance_report.json")
    if LEAK_REPORT.exists():
        _copy(LEAK_REPORT, HIDDEN / "evidence" / "leak_report.json")
    if T_TASK_TRACE.exists():
        _copy(T_TASK_TRACE, HIDDEN / "evidence" / "t_task_execution.json")
    if CORRECTIONS.exists():
        _copy(CORRECTIONS, HIDDEN / "evidence" / "corrections.json")
    rejected_spec = EVIDENCE / "rejected_tasks" / (
        "werkzeug_parse_options_header_continuation_state_spec.json")
    if rejected_spec.exists():
        _copy(rejected_spec, HIDDEN / "evidence" / rejected_spec.name)
    rejected_matrix = EVIDENCE / (
        "werkzeug_parse_options_header_continuation_state_matrix.json")
    if rejected_matrix.exists():
        _copy(rejected_matrix, HIDDEN / "evidence" / rejected_matrix.name)

    _write_json(
        HIDDEN / "README.json",
        {
            "schema": "mace_benchmark_v3_hidden_package",
            "label": LABEL,
            "release_version": VERSION,
            "warning": (
                "Hidden reference positions, witnesses, matrices and "
                "acceptance logs.  Never copy these into the public package."),
            "task_count": len(public_index),
            "task_ids": [item["task_id"] for item in public_index],
        })
    return {
        "task_count": len(public_index),
        "task_ids": [item["task_id"] for item in public_index],
    }


def _public_readme(index: List[Dict[str, Any]]) -> str:
    rows = "\n".join(
        f"| `{item['task_id']}` | {item['project']} | `{item['source_file']}` |"
        for item in index)
    return f"""# MACE Benchmark v3 — Public Development/Pilot Package

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
{rows}

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
"""


def _manifest() -> Dict[str, Any]:
    files: Dict[str, str] = {}
    for path in sorted(RELEASE.rglob("*")):
        if not path.is_file() or path.name in ("manifest.json", "SHA256SUMS"):
            continue
        files[path.relative_to(RELEASE).as_posix()] = _sha256_file(path)
    bundle = hashlib.sha256()
    for rel, digest in sorted(files.items()):
        bundle.update(rel.encode("utf-8"))
        bundle.update(b"\0")
        bundle.update(digest.encode("ascii"))
        bundle.update(b"\0")
    public_files = {
        rel: digest for rel, digest in files.items()
        if rel.startswith("PUBLIC/")
    }
    hidden_files = {
        rel: digest for rel, digest in files.items()
        if rel.startswith("HIDDEN/")
    }
    return {
        "schema": "mace_benchmark_v3_release_manifest",
        "release_version": VERSION,
        "label": LABEL,
        "frozen_utc": datetime.now(timezone.utc).isoformat(),
        "public_file_count": len(public_files),
        "hidden_file_count": len(hidden_files),
        "bundle_sha256": bundle.hexdigest(),
        "public_files": public_files,
        "hidden_files": hidden_files,
        "code_files": {
            "benchmark_real_v3/scoring/engine.py": _sha256_file(
                V3 / "scoring" / "engine.py"),
            "benchmark_real_v3/scoring/contracts.py": _sha256_file(
                V3 / "scoring" / "contracts.py"),
            "benchmark_real_v3/scoring/score.py": (
                _sha256_file(V3 / "scoring" / "score.py")
                if (V3 / "scoring" / "score.py").exists() else None),
            "benchmark_real_v3/scoring/demo.py": _sha256_file(
                V3 / "scoring" / "demo.py"),
            "benchmark_real_v3/leak_check.py": _sha256_file(
                V3 / "leak_check.py"),
            "benchmark_real_v3/release_build.py": _sha256_file(
                V3 / "release_build.py"),
            "benchmark_real_v3/acceptance_v3.py": _sha256_file(
                V3 / "acceptance_v3.py"),
            "benchmark_real_v3/acceptance_t_task_trace.py": _sha256_file(
                V3 / "acceptance_t_task_trace.py"),
            "benchmark_real_v3/acceptance_trace_plugin.py": _sha256_file(
                V3 / "acceptance_trace_plugin.py"),
            "benchmark_real_v3/scoring/tests/test_scoring.py": (
                _sha256_file(SCORING_TESTS)
                if SCORING_TESTS.exists() else None),
        },
        "freeze_note": (
            "The public and hidden packages are frozen together.  Hidden "
            "answers must not be changed in response to future MACE/Qwen "
            "scores; any correction requires a separate versioned record."),
    }


def write_manifest() -> Dict[str, Any]:
    manifest = _manifest()
    _write_json(RELEASE / "manifest.json", manifest)
    lines = [
        f"{digest}  {rel}"
        for rel, digest in sorted(
            {**manifest["public_files"], **manifest["hidden_files"]}.items())
    ]
    (RELEASE / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check-only", action="store_true")
    args = parser.parse_args()
    if not args.check_only:
        summary = build()
        print(json.dumps(summary, ensure_ascii=False, indent=2))
    manifest = write_manifest()
    print(json.dumps({
        "release_version": manifest["release_version"],
        "label": manifest["label"],
        "bundle_sha256": manifest["bundle_sha256"],
        "public_files": manifest["public_file_count"],
        "hidden_files": manifest["hidden_file_count"],
        "manifest": str(RELEASE / "manifest.json"),
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
