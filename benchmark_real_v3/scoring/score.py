"""CLI: score one MACE benchmark v3 submission.

Usage::

    python -m benchmark_real_v3.scoring.score submission.json
    python -m benchmark_real_v3.scoring.score submission.json --out result.json
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from benchmark_real_v3.scoring.engine import score_submission


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("submission", type=Path)
    parser.add_argument("--hidden-root", type=Path, default=None)
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args()
    try:
        submission = json.loads(args.submission.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        print(f"cannot read submission: {exc}", file=sys.stderr)
        return 2
    result = score_submission(submission, hidden_root=args.hidden_root)
    text = json.dumps(result, ensure_ascii=False, indent=2) + "\n"
    if args.out:
        args.out.parent.mkdir(parents=True, exist_ok=True)
        args.out.write_text(text, encoding="utf-8")
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
