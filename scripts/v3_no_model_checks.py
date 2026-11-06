"""No-model checks for the v3 pilot.

Applies the deterministic Baseline-B verifier to Baseline C's submissions.
This is a plumbing/evidence check, not a model result: it answers "does the
verifier agree with the intervention-derived claims?" and records where the
verifier is structurally blind (it only enumerates the operations a proposal
names).

Usage::

    python scripts/v3_no_model_checks.py --run runs/v3_baseline_pilot
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from benchmark_v3_baselines.config import BUDGET, TASK_IDS  # noqa: E402
from benchmark_v3_baselines.verifier import verify_submission  # noqa: E402


def main(argv=None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run", type=Path, required=True)
    args = parser.parse_args(argv)
    out = {}
    for task_id in TASK_IDS:
        submission_path = (args.run / "tasks" / task_id / "baseline_c"
                           / "submission.json")
        if not submission_path.exists():
            out[task_id] = {"status": "MISSING_SUBMISSION"}
            continue
        submission = json.loads(submission_path.read_text(encoding="utf-8"))
        result = verify_submission(
            task_id, submission, max_ops=BUDGET["max_candidate_ops"],
            variant_prefix=f"v_{task_id}")
        path = args.run / "tasks" / task_id / "baseline_b"
        path.mkdir(parents=True, exist_ok=True)
        (path / "verifier_on_C.json").write_text(
            json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        out[task_id] = {
            "run_label": "NO_MODEL_VERIFIER_CHECK",
            "counts": result["counts"],
            "universe_size": len(result["universe"]),
            "universe_problems": result["universe_problems"],
            "probe_executions": result["probe_executions"],
        }
    (args.run / "no_model_checks.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps(out, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
