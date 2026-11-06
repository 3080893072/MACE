"""Qualify a candidate against researcher-designed tests.

The expansion rules allow a declared test set that is designed for the task,
provided it is marked DESIGNED and never passed off as an upstream original.
This driver copies one designed test file into every built variant, runs the
same P+/P-/U-subset qualification as :mod:`benchmark_real_v4.qualify`, and
stores the evidence under ``evidence/qualification_designed``.

The designed test node ids are fixed before the runs; the driver does not
select tests after seeing which ones pass.

Usage::

    python -m benchmark_real_v4.designed_qualify <candidate_id> \\
        --file designed_tests/<name>.py --tests <nodeid> [--tests <nodeid>]
"""
from __future__ import annotations

import argparse
import json
import shutil
from pathlib import Path
from typing import Any, Dict, List

import benchmark_real_v4.qualify as qualify
from benchmark_real_v4.config import EVIDENCE, PROJECTS, V4

DESIGNED_DIR = V4 / "designed_tests"
OUT_ROOT = EVIDENCE / "qualification_designed"
DESIGNED_NAME = "test_v4_designed_{slug}.py"


def _slug(candidate_id: str) -> str:
    return qualify._slug(candidate_id)


def _target_tests_dir(root: Path) -> Path:
    tests = root / "tests"
    return tests if tests.is_dir() else root


def inject(root: Path, source: Path, slug: str) -> str:
    target = _target_tests_dir(root) / DESIGNED_NAME.format(slug=slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source, target)
    return target.relative_to(root).as_posix()


def qualify_designed(candidate_id: str, source: Path,
                     extra_tests: List[str]) -> Dict[str, Any]:
    row = qualify.find_row(candidate_id)
    slug = _slug(candidate_id)
    spec = qualify.build_spec(row)
    rel = None
    variants = qualify.build_variants(spec)
    for meta in variants.values():
        rel = inject(Path(meta["variant"]["root"]), source, slug)
    assert rel is not None
    nodeids = [f"{rel}::{name}" for name in extra_tests]
    spec["tests"] = nodeids
    spec["designed"] = True
    spec["designed_source"] = str(source)
    runs = {key: qualify.run_variant(spec, key, meta)
            for key, meta in variants.items()}
    tests = [qualify.classify(spec, runs, nodeid) for nodeid in nodeids]
    counts: Dict[str, int] = {}
    for test in tests:
        counts[test["classification"]] = counts.get(
            test["classification"], 0) + 1
    payload = {
        "candidate_id": candidate_id,
        "project": row["project"],
        "version": row["version"],
        "file": row["file"],
        "function": row["function"],
        "target_A": row["target_A"],
        "later_assignments": row["later_assignments"],
        "declared_test_set": "DESIGNED",
        "designed_source": str(source),
        "spec": spec,
        "counts": counts,
        "tests": tests,
        "declared_minus": {
            "returncode": runs["EMPTY"]["returncode"],
            "timed_out": runs["EMPTY"]["timed_out"],
            "nodeids": nodeids,
            "outcomes": {nodeid: qualify._outcome(runs["EMPTY"], nodeid)
                         for nodeid in nodeids},
            "log": runs["EMPTY"]["log"],
        },
        "declared_plus": {
            "returncode": runs["plus"]["returncode"],
            "outcomes": {nodeid: qualify._outcome(runs["plus"], nodeid)
                         for nodeid in nodeids},
        },
        "variants": {
            key: {"returncode": run["returncode"],
                  "timed_out": run["timed_out"],
                  "log": run["log"], "trace": run["trace"]}
            for key, run in runs.items()
        },
        "exit": {key: run["returncode"] for key, run in runs.items()},
    }
    OUT_ROOT.mkdir(parents=True, exist_ok=True)
    (OUT_ROOT / f"{slug}.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True)
        + "\n", encoding="utf-8")
    return payload


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_id")
    parser.add_argument("--file", required=True)
    parser.add_argument("--tests", action="append", required=True,
                        help="test function name inside the designed file")
    args = parser.parse_args()
    source = Path(args.file)
    if not source.is_absolute():
        source = V4 / args.file
    payload = qualify_designed(args.candidate_id, source, args.tests)
    print(json.dumps({
        "candidate": payload["candidate_id"],
        "counts": payload["counts"],
        "declared_minus": payload["declared_minus"]["outcomes"],
        "tests": [
            {"nodeid": t["nodeid"], "class": t["classification"],
             "local": t["local_effect_instances"],
             "msms": t["relations"]["msms"],
             "mmbs": t["relations"]["mmbs"]}
            for t in payload["tests"]
        ],
    }, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
