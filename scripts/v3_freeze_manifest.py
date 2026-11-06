"""Freeze manifest for the deterministic Baseline C.

Records the exact commit, config, rules, budget and SHA-256 of every file that
produced the v3 pilot results.  This is a bookkeeping tool: it runs no model,
touches no benchmark task, and never reads HIDDEN data.

Usage::

    python scripts/v3_freeze_manifest.py --run runs/v3_baseline_pilot \
        --out runs/v3_baseline_freeze
    python scripts/v3_freeze_manifest.py --verify runs/v3_baseline_freeze
"""
from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any, Dict, List

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from benchmark_v3_baselines.config import (  # noqa: E402
    BUDGET, MODEL, TASK_IDS, TASK_STORY, config_sha256)
from benchmark_v3_baselines.public_io import load_task  # noqa: E402

FREEZE_SCHEMA = "mace-v3-baseline-freeze-1.0"

CODE_FILES = [
    "benchmark_v3_baselines/__init__.py",
    "benchmark_v3_baselines/ast_discovery.py",
    "benchmark_v3_baselines/baseline_c.py",
    "benchmark_v3_baselines/claims.py",
    "benchmark_v3_baselines/config.py",
    "benchmark_v3_baselines/direct_qwen.py",
    "benchmark_v3_baselines/execution.py",
    "benchmark_v3_baselines/inputs.py",
    "benchmark_v3_baselines/public_io.py",
    "benchmark_v3_baselines/run_pilot.py",
    "benchmark_v3_baselines/trace_runner.py",
    "benchmark_v3_baselines/verifier.py",
    "tests/test_v3_baselines.py",
    "scripts/v3_reference_match.py",
    "scripts/v3_no_model_checks.py",
]


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=KIT, check=True,
                          capture_output=True, text=True).stdout.strip()


def _committed_in(path: Path) -> str:
    try:
        rel = path.resolve().relative_to(KIT)
    except ValueError:
        return ""
    return git("log", "-1", "--format=%H", "--", rel.as_posix())


def _relation_keys(score: Dict[str, Any]) -> List[str]:
    keys = sorted({
        claim["relation_key"] for claim in score.get("claims", [])
        if claim.get("credit") == 1 and claim.get("relation_key")})
    return keys


def build(run_dir: Path) -> Dict[str, Any]:
    config = json.loads((run_dir / "config.json").read_text(encoding="utf-8"))
    recorded_sha = (run_dir / "config.sha256").read_text(encoding="utf-8").strip()
    recomputed_sha = config_sha256(config)
    if recorded_sha != recomputed_sha:
        raise SystemExit("config.sha256 does not match config.json")

    code_hashes = {}
    for rel in CODE_FILES:
        path = KIT / rel
        if not path.exists():
            raise SystemExit(f"missing frozen file: {rel}")
        code_hashes[rel] = sha256_file(path)
    fixtures = sorted((KIT / "benchmark_v3_baselines" / "fixtures").rglob("*.json"))
    for path in fixtures:
        rel = path.relative_to(KIT).as_posix()
        code_hashes[rel] = sha256_file(path)

    tasks: Dict[str, Any] = {}
    for task_id in TASK_IDS:
        loaded = load_task(task_id)  # verifies source_sha256 internally
        task_dir = run_dir / "tasks" / task_id
        score = json.loads((task_dir / "scores" / "C.json")
                           .read_text(encoding="utf-8"))
        baseline = json.loads((task_dir / "baseline_c" / "baseline_c.json")
                              .read_text(encoding="utf-8"))
        submission_path = task_dir / "baseline_c" / "submission.json"
        keys = _relation_keys(score)
        tasks[task_id] = {
            "status": "DEV_TUNED",
            "source_sha256": loaded["task"]["source_sha256"],
            "story": TASK_STORY[task_id],
            "baseline_version": baseline["baseline_version"],
            "discovery_rule": baseline["discovery"]["discovery_rule"],
            "universe_ids": [op["id"] for op in baseline["universe"]],
            "inputs": baseline["inputs"],
            "unknowns": baseline["unknowns"],
            "probe_executions": baseline["probe_executions"],
            "variant_builds": baseline["variant_builds"],
            "claims_submitted": len(baseline["submission"]["claims"]),
            "credited_relation_keys": keys,
            "credited_relation_keys_sha256": sha256_text(
                json.dumps(keys, ensure_ascii=False, sort_keys=True)),
            "files": {
                "submission": {
                    "path": f"tasks/{task_id}/baseline_c/submission.json",
                    "sha256": sha256_file(submission_path)},
                "baseline_c": {
                    "path": f"tasks/{task_id}/baseline_c/baseline_c.json",
                    "sha256": sha256_file(
                        task_dir / "baseline_c" / "baseline_c.json")},
                "score": {
                    "path": f"tasks/{task_id}/scores/C.json",
                    "sha256": sha256_file(task_dir / "scores" / "C.json")},
            },
        }

    report_files = {}
    for rel in ("reference_match.json", "no_model_checks.json",
                "availability.json", "summary.json"):
        path = run_dir / rel
        if path.exists():
            report_files[rel] = sha256_file(path)

    return {
        "schema": FREEZE_SCHEMA,
        "release_version": config["release_version"],
        "branch": config["git_branch"],
        "code_commit": config["git_commit"],
        "code_commit_subject": git("log", "-1", "--format=%s",
                                   config["git_commit"]),
        "results_commit": _committed_in(run_dir),
        "package_tree_sha": git("rev-parse",
                                f"{config['git_commit']}:benchmark_v3_baselines"),
        "config_sha256": recomputed_sha,
        "config_file_sha256": sha256_file(run_dir / "config.json"),
        "experiment_config": config,
        "baseline_version": "C-ast-intervention-1.0",
        "model_config": MODEL,
        "budget": BUDGET,
        "task_status": {task_id: "DEV_TUNED" for task_id in TASK_IDS},
        "generalization_claim_permitted": False,
        "dev_tuned_statement": (
            "All five tasks were used while designing and debugging the AST "
            "discovery rule. Results on them are development-set results and "
            "must never be reported as held-out generalization accuracy."),
        "hidden_isolation": {
            "baseline_package_reads_hidden": False,
            "scorer_invoked_as_subprocess": True,
            "reference_match_is_evaluation_side_only": True,
        },
        "code_files": code_hashes,
        "run_artifacts": report_files,
        "tasks": tasks,
        "totals": {
            "tasks": len(tasks),
            "claims_submitted": sum(t["claims_submitted"] for t in tasks.values()),
            "credited_relation_keys": sum(
                len(t["credited_relation_keys"]) for t in tasks.values()),
            "probe_executions": sum(t["probe_executions"] for t in tasks.values()),
            "variant_builds": sum(t["variant_builds"] for t in tasks.values()),
        },
    }


def verify(freeze_dir: Path) -> int:
    manifest = json.loads((freeze_dir / "manifest.json").read_text(encoding="utf-8"))
    run_dir = freeze_dir.parent / "v3_baseline_pilot"
    current = build(run_dir)
    problems = []
    for key in ("code_commit", "config_sha256", "package_tree_sha"):
        if manifest.get(key) != current.get(key):
            problems.append(f"{key}: {manifest.get(key)!r} != {current.get(key)!r}")
    for section in ("code_files", "tasks", "totals"):
        if manifest.get(section) != current.get(section):
            problems.append(f"section changed: {section}")
    if problems:
        print("FREEZE VERIFY FAILED")
        for item in problems:
            print(" -", item)
        return 1
    print("FREEZE VERIFY OK")
    print(json.dumps(current["totals"], ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, help="pilot run directory")
    parser.add_argument("--out", type=Path, help="freeze output directory")
    parser.add_argument("--verify", type=Path, help="verify an existing freeze dir")
    args = parser.parse_args(argv)
    if args.verify:
        return verify(args.verify)
    if not args.run or not args.out:
        parser.error("either --verify or both --run and --out are required")
    manifest = build(args.run)
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / "manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2),
                    encoding="utf-8")
    print(f"wrote {path}")
    print(json.dumps(manifest["totals"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
