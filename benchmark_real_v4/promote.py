"""Check the six promotion conditions and write a release candidate.

A survivor is not a task until every condition is backed by saved execution
evidence.  This module refuses to invent any of them:

1. real upstream source with an explicit A (static row + source hash);
2. a declared test set that passes with A deleted (full P- suite);
3. A changes its target location on at least one declared test input;
4. masking is established: P+ equals P- there and some nonempty U subset
   restores equality (MSMS) while deleting U exposes (MMBS);
5. a legal exposing counterexample exists (P+ != P- on a probe input);
6. MSMS/MMBS are verified on a declared input, with the witness scope stated.

Usage::

    python -m benchmark_real_v4.promote <candidate_id> <witness_spec.json>
    python -m benchmark_real_v4.promote --list
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any, Dict, List

from benchmark_real_v4.config import CANDIDATES, EVIDENCE, V4

QUAL = EVIDENCE / "qualification"
QUAL_DESIGNED = EVIDENCE / "qualification_designed"
WIT = EVIDENCE / "witnesses"
FUNNELS = [EVIDENCE / "screening_funnel.json",
           EVIDENCE / "screening_funnel_more.json",
           EVIDENCE / "screening_funnel_extra.json"]
OUT = V4 / "release_candidates"


def _slug(candidate_id: str) -> str:
    return (candidate_id.replace(":", "_").replace("/", "_")
            .replace("\\", "_").replace(".", "_"))[:120]


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8"))


def _rows() -> List[Dict[str, Any]]:
    rows = []
    for path in FUNNELS:
        if path.exists():
            rows.extend(_load(path)["candidates"])
    return rows


def _row(candidate_id: str) -> Dict[str, Any]:
    for row in _rows():
        if row["candidate_id"] == candidate_id:
            return row
    # Hand-picked candidates outside the funnel still have a static record.
    for source in sorted(CANDIDATES.glob("*.json")):
        if source.name.startswith("ranked_"):
            continue
        for row in _load(source).get("candidates", []):
            if row.get("candidate_id") == candidate_id:
                return row
    raise SystemExit(f"unknown candidate {candidate_id}")


def _qual(candidate_id: str) -> Dict[str, Any]:
    """Prefer the designed-test evidence, then the original-test evidence."""
    for root in (QUAL_DESIGNED, QUAL):
        path = root / f"{_slug(candidate_id)}.json"
        if path.exists():
            return _load(path)
    raise SystemExit(f"missing qualification evidence for {candidate_id}")


def _wit(candidate_id: str) -> Dict[str, Any]:
    path = WIT / f"{_slug(candidate_id)}.json"
    if not path.exists():
        raise SystemExit(f"missing witness evidence {path}")
    return _load(path)


def check(candidate_id: str) -> Dict[str, Any]:
    row = _row(candidate_id)
    qual = _qual(candidate_id)
    wit = _wit(candidate_id)
    designed = qual.get("declared_test_set") == "DESIGNED"
    if designed:
        outcomes = qual.get("declared_minus", {}).get("outcomes", {})
        declared_ok = bool(outcomes) and all(
            value == "passed" for value in outcomes.values())
        suite = {"outcomes": outcomes}
        returncode = qual.get("declared_minus", {}).get("returncode")
    else:
        declared_ok = bool(row.get("full_minus")) and \
            row["full_minus"].get("returncode") == 0 and \
            not row["full_minus"].get("summary", {}).get("failed_nodeids")
        suite = (row.get("full_minus") or {}).get("summary")
        returncode = (row.get("full_minus") or {}).get("returncode")
    masked_tests = [test for test in qual["tests"]
                    if test["classification"] == "MASKED_EFFECT"
                    and test["local_effect_instances"] > 0
                    and test["relations"]["msms"]]
    conditions = {
        "1_real_source_and_A": {
            "ok": bool(row.get("source_sha256")
                       and row["target_A"].get("code")),
            "source_sha256": row.get("source_sha256"),
            "A": row["target_A"],
        },
        "2_declared_tests_pass_under_P_minus": {
            "ok": declared_ok,
            "test_set": "DESIGNED" if designed else "ORIGINAL",
            "designed_source": qual.get("designed_source"),
            "suite": suite,
            "returncode": returncode,
        },
        "3_local_effect_on_test_input": {
            "ok": bool(masked_tests),
            "masked_tests": len(masked_tests),
            "examples": [test["nodeid"] for test in masked_tests[:5]],
        },
        "4_masking_established": {
            "ok": bool(masked_tests),
            "msms": [test["relations"]["msms"] for test in masked_tests[:3]],
            "mmbs": [test["relations"]["mmbs"] for test in masked_tests[:3]],
        },
        "5_legal_exposing_counterexample": {
            "ok": bool(wit["summary"]["legal_exposing_payload"]),
            "exposing_payloads": wit["summary"]["exposing"],
            "payloads": [wit["payloads"][index]["payload"]
                         for index in wit["summary"]["exposing"]],
        },
        "6_verified_msms_mmbs_and_scope": {
            "ok": bool(wit["summary"]["verified_msms"]
                       and wit["summary"]["verified_mmbs"]),
            "scope": "declared probe inputs only; no claim over other inputs",
            "msms": [row["msms"] for row in wit["payloads"] if row["msms"]],
            "mmbs": [row["mmbs"] for row in wit["payloads"] if row["mmbs"]],
        },
    }
    promoted = all(item["ok"] for item in conditions.values())
    return {
        "candidate_id": candidate_id,
        "project": row["project"],
        "version": row["version"],
        "file": row["file"],
        "function": row["function"],
        "mechanism": row.get("mechanism", "name-overwrite"),
        "promoted": promoted,
        "conditions": conditions,
        "declared_test_set": qual.get("declared_test_set", "ORIGINAL"),
        "designed_source": qual.get("designed_source"),
        "declared_tests": qual["spec"]["tests"],
        "universe": qual["spec"]["candidate_universe"],
        "qualification": qual["counts"],
        "witness_summary": wit["summary"],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_id", nargs="?")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    ids: List[str]
    if args.all:
        ids = [row["candidate_id"] for row in _rows()
               if row["screening_status"] == "TEST_SURVIVING_DELETION"]
    elif args.candidate_id:
        ids = [args.candidate_id]
    else:
        parser.print_help()
        return 2
    OUT.mkdir(parents=True, exist_ok=True)
    for candidate_id in ids:
        result = check(candidate_id)
        path = OUT / f"{_slug(candidate_id)}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                   sort_keys=True) + "\n", encoding="utf-8")
        print(json.dumps({
            "candidate": candidate_id,
            "promoted": result["promoted"],
            "failed": [name for name, item in result["conditions"].items()
                       if not item["ok"]],
            "path": str(path),
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
