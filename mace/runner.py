"""Sandbox child entry point.

Runs one analysis request in a separate, isolated Python process:

    python -I runner.py payload.json output.json

The untrusted program is compiled and executed *only here*.  The parent
process never imports or execs program code; it only reads the JSON report
this script writes.
"""
from __future__ import annotations

import json
import os
import sys
import traceback


def _import_mace():
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    if root not in sys.path:
        sys.path.insert(0, root)


def main() -> int:
    if len(sys.argv) != 3:
        print("usage: runner.py <payload.json> <output.json>", file=sys.stderr)
        return 2
    payload_path, output_path = sys.argv[1], sys.argv[2]
    with open(payload_path, "r", encoding="utf-8") as handle:
        payload = json.load(handle)
    result = {"status": "ERROR"}
    try:
        _import_mace()
        from mace.contracts import parse_bundle
        from mace.program import build_pair, build_callables, run_pair
        from mace.terms import signature_table
        from mace.verify import verify_bundle

        pair = build_pair(payload["source"], payload.get("entry", "program"))
        if not pair.supported:
            result = {"status": "UNKNOWN", "problems": pair.problems,
                      "target_line": pair.target_line,
                      "reason": "program outside the supported deterministic subset"}
        elif payload.get("trace"):
            from mace.trace import diff_traces
            from mace.program import run_traced
            out = []
            for case in payload["cases"]:
                traced = run_traced(pair, case)
                diff = diff_traces(traced["traces"]["plus"], traced["traces"]["minus"],
                                   outputs_equal=traced["out_plus"] == traced["out_minus"])
                out.append({"args": traced["args"],
                            "out_plus": traced["out_plus"], "out_minus": traced["out_minus"],
                            "diff": diff,
                            "traces": traced["traces"]})
            result = {"status": "OK", "traces": out, "target_line": pair.target_line}
        elif payload.get("labels"):
            # Per-case label only: did the paired runs agree?  The snapshots at
            # A are the pre-state (P-) and post-state (P+) of the target.
            rows = run_pair(pair, payload["cases"])
            result = {"status": "OK", "target_line": pair.target_line,
                      "cases": [{"args": row["args"],
                                 "outputs_equal": row["outputs_equal"],
                                 "err_plus": row["err_plus"],
                                 "err_minus": row["err_minus"],
                                 "snap_minus": row.get("snap_minus") or {},
                                 "snap_plus": row.get("snap_plus") or {},
                                 "a_has_local_effect": row["a_has_local_effect"]}
                                for row in rows]}
        elif payload.get("probe"):
            # Report the variable vocabulary visible at A (names + sorts only).
            from mace.terms import sort_of
            rows = run_pair(pair, payload["cases"][:1])
            row = rows[0] if rows else {}
            vocabulary = {name: sort_of(value)
                          for name, value in (row.get("snap_minus") or {}).items()}
            vocabulary = {k: v for k, v in vocabulary.items() if v}
            result = {"status": "OK", "vocabulary": vocabulary,
                      "channels": len(row.get("out_plus") or []),
                      "target_line": pair.target_line}
        else:
            rows = run_pair(pair, payload["cases"])
            callables = build_callables(pair)
            bundle = parse_bundle(payload["bundle"], allow_guard_only=True)
            report = verify_bundle(
                rows, bundle,
                input_sorts=payload["arg_sorts"],
                functions=signature_table(payload.get("functions")),
                callables=callables,
                level=payload.get("level", "BOUNDED"),
                channels=int(payload.get("channels", 1)),
                core_logic=payload.get("core_logic", False),
            )
            report.update({"status": "OK", "target_line": pair.target_line,
                           "source_sha256": payload.get("source_sha256")})
            result = report
    except Exception as exc:  # noqa: BLE001 - always emit a structured report
        result = {"status": "ERROR", "error": f"{type(exc).__name__}: {exc}",
                  "traceback": traceback.format_exc(limit=8)}
    with open(output_path, "w", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
