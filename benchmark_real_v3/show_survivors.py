"""Print source context for every test-surviving candidate (review aid)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

from benchmark_real_v3.config import EVIDENCE, PROJECTS

FUNNEL = EVIDENCE / "screening_funnel.json"


def main() -> int:
    payload = json.loads(FUNNEL.read_text(encoding="utf-8"))
    wanted = set(sys.argv[1:])
    for row in payload["candidates"]:
        if row["screening_status"] != "TEST_SURVIVING_DELETION":
            continue
        if wanted and row["candidate_id"] not in wanted:
            continue
        cfg = PROJECTS[row["project_id"]]
        path = cfg["root"] / row["file"]
        lines = path.read_text(encoding="utf-8").splitlines()
        line = row["target_A"]["line"]
        print("\n" + "=" * 100)
        print(row["candidate_id"])
        print("function:", row["function"], "variable:", row["variable"],
              "hits:", row["p_plus_hit_test_count"],
              "shape:", json.dumps(row["static_shape"]))
        print("A:", row["target_A"]["code"])
        for later in row["later_assignments"]:
            print(f"  later {later['line']}: {later['code'][:100]}"
                  f" (reads_A={later['reads_A']})")
        start = max(1, line - 12)
        end = min(len(lines), line + 18)
        for index in range(start, end + 1):
            mark = ">>" if index == line else "  "
            print(f"{mark}{index:5} {lines[index - 1]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
