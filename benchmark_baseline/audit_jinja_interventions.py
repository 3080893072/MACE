"""Independent phase-1 audit: execute jinja2 U-out interventions directly.

This script does NOT read hidden reference files.  It builds P+ / P- variants
from the public source and deletes the AST-submitted operation (line 119) and
the reference-universe candidate (line 137) independently, then records the
probe observation and the executed lines on the public probe inputs.

Output: benchmark_baseline/audit/jinja_interventions.json
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List

from benchmark_baseline.ast_method import input_pool
from benchmark_real_v3.config import KIT, PROJECTS
from benchmark_baseline.prompts import public_task
from benchmark_real_v3.variant_lab import build_variant, run_probe

TASK = "jinja2_bytecode_cache_read"
PROJECT = "jinja2-3.1.3"
PROBE = "probe_jinja_bytecode_cache.py"
TRACE = KIT / "benchmark_baseline" / "trace_lines.py"
OUT = KIT / "benchmark_baseline" / "audit" / "jinja_interventions.json"
# Tracing costs ~19 s per run on this machine; only the two sides need it.
TRACE_CONDITIONS = {"P+", "P-"}
TRACE_INPUT_INDEX = 0  # one representative benign input; traces cost ~19 s each

# (label, deleted statement lines, delete A?)
CONDITIONS: List[tuple[str, tuple[int, ...], bool]] = [
    ("P+", (), False),
    ("P-", (), True),
    ("P+_del119", (119,), False),
    ("P+_del137", (137,), False),
    ("P-_del119", (119,), True),
    ("P-_del137", (137,), True),
    ("P+_del119_137", (119, 137), False),
    ("P-_del119_137", (119, 137), True),
]


def trace(project_root: Path, target_file: str, payload: Dict[str, Any]) -> List[int]:
    cfg = PROJECTS[PROJECT]
    out = Path(tempfile.mkstemp(prefix="trace_", suffix=".json")[1])
    request = {
        "probe": str(KIT / "benchmark_real_v3" / "probes" / PROBE),
        "target_file": str((project_root / target_file).resolve()),
        "payload": payload,
        "out": str(out),
    }
    req = out.with_suffix(".req.json")
    req.write_text(json.dumps(request), encoding="utf-8")
    env = os.environ.copy()
    env["PYTHONPATH"] = str((project_root / cfg["source_dir"]).resolve())
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    try:
        subprocess.run([cfg["python"], str(TRACE), str(req)],
                       cwd=str(project_root), env=env, capture_output=True,
                       text=True, encoding="utf-8", errors="replace",
                       timeout=180)
        data = json.loads(out.read_text(encoding="utf-8"))
        return sorted(int(x) for x in data.get("lines", []))
    finally:
        for path in (out, req):
            try:
                path.unlink()
            except OSError:
                pass


def main() -> int:
    task = public_task(TASK)
    target = task["target_operation"]
    file = target["file"]
    name_prefix = "audit_jinja"
    rows: Dict[str, Any] = {
        "task": TASK,
        "target": target,
        "conditions": {},
    }
    for label, deleted, delete_a in CONDITIONS:
        statements = [(file, line) for line in deleted]
        if delete_a:
            statements.append((file, int(target["line"])))
        variant = build_variant(
            PROJECT, f"{name_prefix}_{label}", statement_deletions=statements)
        root = Path(variant["root"])
        cond: Dict[str, Any] = {"deleted": list(deleted), "delete_A": delete_a,
                                "edits": variant["edits"], "inputs": []}
        print(f"[audit] {label} built", flush=True)
        payloads = input_pool(TASK)
        for index, payload in enumerate(payloads):
            result = run_probe(PROJECT, root, PROBE, payload)
            obs = result.get("observation")
            row = {
                "payload": payload,
                "returncode": result["returncode"],
                "observation": obs,
                "ok": bool(result["returncode"] == 0 and isinstance(obs, dict)),
            }
            if label in TRACE_CONDITIONS and index == TRACE_INPUT_INDEX:
                try:
                    row["executed_lines"] = trace(root, file, payload)
                except Exception as exc:  # noqa: BLE001
                    row["trace_error"] = repr(exc)
            cond["inputs"].append(row)
            print(f"[audit] {label} input {index} rc={row['returncode']} "
                  f"obs={json.dumps(obs, ensure_ascii=False)[:120]}",
                  flush=True)
        rows["conditions"][label] = cond
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(rows, ensure_ascii=False, indent=2,
                              sort_keys=True) + "\n", encoding="utf-8")
    # Compact summary to stdout.
    compact = {}
    for label, cond in rows["conditions"].items():
        compact[label] = [
            {
                "input": row["payload"],
                "ok": row["ok"],
                "obs": row["observation"],
                "lines_of_interest": sorted(set(row.get("executed_lines", []))
                                            & {119, 132, 137}),
            }
            for row in cond["inputs"]
        ]
    print(json.dumps(compact, ensure_ascii=False, indent=1))
    print(f"\nwrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
