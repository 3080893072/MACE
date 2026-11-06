"""Run the deterministic operation-level baseline on ctrl_02 and ctrl_03.

The private labels from ``attribution.json`` are used *after* discovery, only
by the independent benchmark Verifier.  They are never passed to
``discover()`` or to candidate extraction.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
if str(ROOT / "scripts") not in sys.path:
    sys.path.insert(0, str(ROOT / "scripts"))

from check_open_interface import Verifier  # noqa: E402
from open_ops import discover, to_submission  # noqa: E402

TASKS = ROOT / "benchmark_pilot" / "tasks.json"
ATTR = ROOT / "benchmark_pilot" / "attribution.json"


def main() -> int:
    tasks = {t["task_id"]: t for t in
             json.loads(TASKS.read_text(encoding="utf-8"))["tasks"]}
    attribution = json.loads(ATTR.read_text(encoding="utf-8"))["controlled"]
    report = {}
    for task_id in ("ctrl_02", "ctrl_03"):
        result = discover(tasks[task_id])
        verifier = Verifier(tasks[task_id], attribution[task_id])
        verified = [verifier.verify_relation(rel)
                    for rel in to_submission(result)["relations"]]
        report[task_id] = {
            "discovery": result.to_dict(),
            "independent_verifier": verified,
        }
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
