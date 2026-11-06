"""Run Task-2 mechanism cases with the reliable analyzer (no model calls)."""
from __future__ import annotations

import json
from pathlib import Path

from reliable_ast_v1 import NAME, VERSION
from reliable_ast_v1.analyzer import analyze_spec
from reliable_ast_v1.cases import SPECS

OUT = Path(__file__).resolve().parent / "runs"


def main() -> int:
    OUT.mkdir(parents=True, exist_ok=True)
    cases = [spec for spec in SPECS if spec.case_id not in {
        "jinja2_bytecode_cache_read",
        "werkzeug_bind_server_name_lower",
        "werkzeug_filestorage_stream_name",
        "werkzeug_get_host_default_empty",
        "werkzeug_secure_filename_ascii_filter",
    }]
    summary = {}
    for spec in cases:
        result = analyze_spec(spec)
        path = OUT / f"case_{spec.case_id}.json"
        path.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                                   sort_keys=True) + "\n", encoding="utf-8")
        summary[spec.case_id] = {
            "target": result["target"],
            "status": result["status"],
            "claims": result["claims"],
            "masked_rows": sum(1 for row in result["inputs_evaluated"]
                               if row["base_kind"] == "MASKED"),
            "rows": [{
                "input": row["input"],
                "base_kind": row["base_kind"],
                "a_executes": row["a_executes"],
                "a_event_count": row["a_event_count"],
                "universe": row["universe"],
                "analysis": None if row["analysis"] is None else {
                    "status": row["analysis"]["status"],
                    "msms": row["analysis"]["msms"],
                    "mmbs": row["analysis"]["mmbs"],
                    "evaluations": row["analysis"]["evaluations"],
                },
            } for row in result["inputs_evaluated"]],
            "variant_builds": result["variant_builds"],
            "executions": result["executions"],
            "wall_seconds": result["wall_seconds"],
        }
        print(json.dumps({"case": spec.case_id, "status": result["status"],
                          "claims": len(result["claims"]),
                          "builds": result["variant_builds"],
                          "wall": result["wall_seconds"]},
                         ensure_ascii=False), flush=True)
    (OUT / "cases.json").write_text(
        json.dumps({"analyzer": NAME, "version": VERSION,
                    "protocol": {"model_calls": 0, "gpu": False,
                                 "independent_test_set": False},
                    "cases": summary}, ensure_ascii=False, indent=2,
                   sort_keys=True) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
