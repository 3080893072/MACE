"""Run an existing qualification pass but write evidence into the dataset tree.

This is a thin wrapper around ``benchmark_real_v4.qualify``.  It does not
change the algorithm, the variant builder, or the classification rules; it
only redirects the output roots so that V4 dataset evidence stays under
``benchmark_v4_dataset/evidence/qualification/``.

Usage::

    MACE_QUALIFY_FUNNEL=benchmark_real_v4/evidence/screening_funnel_more.json \
      python -I benchmark_v4_dataset/tools/run_qualification.py <candidate_id>

    python -I benchmark_v4_dataset/tools/run_qualification.py --all-survivors
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(KIT))

import benchmark_real_v4.qualify as q  # noqa: E402

DS = KIT / "benchmark_v4_dataset"
q.OUT_ROOT = DS / "evidence" / "qualification"
q.RUN_ROOT = q.OUT_ROOT / "runs"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("candidate_id", nargs="?")
    parser.add_argument("--all-survivors", action="store_true")
    parser.add_argument("--limit", type=int, default=10)
    args = parser.parse_args()

    if args.all_survivors:
        rows = [r for r in q.load_rows()
                if r["screening_status"] == "TEST_SURVIVING_DELETION"]
        rows = [r for r in rows if len(r["p_plus_hit_tests"]) <= q.MAX_TESTS * 4]
        for row in rows[:args.limit]:
            payload = q.qualify(row["candidate_id"])
            print(json.dumps({"candidate": row["candidate_id"],
                              "counts": payload["counts"],
                              "u": [op["id"] for op in payload["spec"]["candidate_universe"]]},
                             ensure_ascii=False))
        return 0

    if not args.candidate_id:
        parser.print_help()
        return 2
    payload = q.qualify(args.candidate_id)
    print(json.dumps({"candidate": payload["candidate_id"],
                      "counts": payload["counts"],
                      "u": [op["id"] for op in payload["spec"]["candidate_universe"]],
                      "path": str(q.OUT_ROOT / (payload["candidate_id"] + ".json"))},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
