"""Run the P+ full suite with per-test line tracing for every project."""
from __future__ import annotations

import json

from benchmark_real_v3.config import PROJECTS
from benchmark_real_v3.run_suite import run_plus


def main() -> int:
    summary = {}
    for project_id in PROJECTS:
        run = run_plus(project_id)
        summary[project_id] = {
            "returncode": run["returncode"],
            "timed_out": run["timed_out"],
            "summary": run["summary"],
            "log": run["log"],
            "trace_json": run["trace_json"],
            "junit_xml": run["junit_xml"],
            "source_tree_sha256": run["source_tree_sha256"],
        }
        print(project_id, run["returncode"],
              run["summary"].get("outcomes"))
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
