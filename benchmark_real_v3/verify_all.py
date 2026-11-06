"""Run the declared enable/disable matrix for every task with a spec."""
from __future__ import annotations

import json
from pathlib import Path

from benchmark_real_v3.config import EVIDENCE
from benchmark_real_v3.verify_task import TASKS, evaluate


def main() -> int:
    results = []
    for task_dir in sorted(p for p in TASKS.iterdir() if p.is_dir()):
        spec_path = task_dir / "spec.json"
        if not spec_path.exists():
            continue
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        result = evaluate(spec["project_id"], spec)
        out = EVIDENCE / f"{spec['task_id']}_matrix.json"
        out.write_text(
            json.dumps(result, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        results.append({
            "task_id": spec["task_id"],
            "exposing_inputs": result["scope"]["exposing_inputs"],
            "masking_inputs": result["scope"]["masking_inputs"],
            "msms": {
                iid: data["msms"] for iid, data in result["inputs"].items()
            },
            "mmbs": {
                iid: data["mmbs"] for iid, data in result["inputs"].items()
            },
            "matrix": str(out),
        })
        print(spec["task_id"], result["scope"]["exposing_inputs"],
              result["scope"]["masking_inputs"])
    print(json.dumps(results, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
