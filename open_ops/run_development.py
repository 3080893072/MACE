"""Minimal operation-discovery experiment on the existing development cases.

Arms
----
A. expanded AST/dependency candidates + independent verifier
B. the same candidates plus MACE semantic-contract line proposals, with the
   same candidate count and therefore the same subset-execution budget.

No model is called.  No private B/C/D/E label is passed to candidate
extraction.  The private attribution file is not read here at all.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark_pilot.verifier_v2 import (  # noqa: E402
    run_matrix,
    validate_cases,
    verify_relation,
)
from benchmark_real_pilot.run import load_source  # noqa: E402
from benchmark_real_pilot.specs import TASKS as REAL_SPECS  # noqa: E402
from benchmark_pilot.engine import replace_target_with_pass  # noqa: E402
from open_ops.contracts import contract_meta, load_default_contract  # noqa: E402
from open_ops.discover import (  # noqa: E402
    MAX_CANDIDATES,
    DiscoveryResult,
    discover_expanded,
)

TASKS_PATH = ROOT / "benchmark_pilot" / "tasks.json"
OUT_DIR = ROOT / "open_ops" / "out"


CONTROL_STATE_SOURCE = '''def program(x, c):
    v = x
    v = v + 1  # TARGET_A
    flag = c == 0
    if flag:
        v = x
    return v
'''

CONTROL_STATE_MINUS = '''def program(x, c):
    v = x
    pass  # P-: A deleted
    flag = c == 0
    if flag:
        v = x
    return v
'''


def _control_state_task() -> Dict[str, Any]:
    return {
        "task_id": "control_state_C_changes_state_B_controlled",
        "entry": "program",
        "program": {"source": CONTROL_STATE_SOURCE,
                    "target_A": {"line": 3}},
        "deletion": {"p_minus_source": CONTROL_STATE_MINUS},
        "input_domain": {
            "args": [{"name": "x"}, {"name": "c"}],
            "cases": [{"x": x, "c": c} for x in (0, 1, 2) for c in (0, 1)],
        },
    }


def _load_controlled() -> Dict[str, Dict[str, Any]]:
    data = json.loads(TASKS_PATH.read_text(encoding="utf-8"))
    return {t["task_id"]: t for t in data["tasks"]
            if t["task_id"] in ("ctrl_01", "ctrl_02", "ctrl_03")}


def _join(results: Sequence[DiscoveryResult]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    seen = set()
    for result in results:
        for rel in result.relations:
            key = (rel.kind, tuple(op.line for op in rel.operations))
            if key in seen:
                continue
            seen.add(key)
            out.append(rel.to_dict())
    return out


def _independent_verifier(task: Dict[str, Any],
                          result: DiscoveryResult) -> Dict[str, Any]:
    """Re-execute every relation through benchmark verifier v2."""
    if not result.relations:
        return {"matrix": None, "relations": [], "program_executions": 0}
    lines: List[int] = []
    for rel in result.relations:
        for op in rel.operations:
            if op.line not in lines:
                lines.append(op.line)
    names = {f"op_{i}": line for i, line in enumerate(lines)}
    line_to_name = {line: name for name, line in names.items()}
    arg_names = [a["name"] for a in task["input_domain"]["args"]]
    cases = [(f"case_{i:04d}", {k: v for k, v in c.items() if k != "id"})
             for i, c in enumerate(task["input_domain"]["cases"])]
    validated = validate_cases(cases, arg_names)
    matrix = run_matrix(
        task["program"]["source"], task["deletion"]["p_minus_source"],
        names, validated, entry=task["entry"],
        target_line=int(task["program"]["target_A"]["line"]),
        max_ops=MAX_CANDIDATES,
    )
    verified = []
    for rel in result.relations:
        ops = [line_to_name[op.line] for op in rel.operations]
        check = verify_relation(matrix, rel.kind, ops, rel.witness_case)
        verified.append(check)
    executions = 2 * len(matrix.rows) * len(validated)
    return {
        "matrix": {
            "ops": list(matrix.ops),
            "cases": len(matrix.cases),
            "subsets": len(matrix.rows),
            "errors": {",".join(sorted(k)): v for k, v in matrix.errors.items()},
        },
        "relations": verified,
        "program_executions": executions,
        "all_verified": all(v.get("valid") for v in verified),
    }


def _run_arm(task: Dict[str, Any], contract_lines: Optional[Sequence[int]],
             meta: Dict[str, Any]) -> Dict[str, Any]:
    started = time.perf_counter()
    result = discover_expanded(task, contract_lines=contract_lines,
                               contract_meta=meta)
    wall = round(time.perf_counter() - started, 4)
    verifier = _independent_verifier(task, result)
    return {
        "discovery": result.to_dict(),
        "independent_verifier": verifier,
        "wall_seconds": wall,
        "program_executions": (
            result.stats.get("case_executions", 0) +
            verifier.get("program_executions", 0)
        ),
    }


def _relation_key(rel: Dict[str, Any]) -> Tuple[str, Tuple[int, ...]]:
    return (rel["kind"], tuple(op["line"] for op in rel["operations"]))


def run_task(task: Dict[str, Any], contract_path: Optional[str]) -> Dict[str, Any]:
    contract = ({"available": False, "reason": "no contract path", "lines": []}
                if contract_path is None else
                contract_meta(load_default_contract(task["task_id"], ROOT)))
    lines = contract.get("cited_lines") if contract.get("available") else None
    if contract.get("available") and not lines:
        lines = None
    arm_a = _run_arm(task, None, {})
    arm_b = _run_arm(task, lines, contract if lines else {})
    a_verified = {_relation_key(r) for r in arm_a["discovery"]["relations"]
                  if r["status"] == "VERIFIED"}
    b_verified = {_relation_key(r) for r in arm_b["discovery"]["relations"]
                  if r["status"] == "VERIFIED"}
    added = sorted(b_verified - a_verified, key=lambda x: (x[0], x[1]))
    contract_only_keys = set((arm_b["discovery"].get("contract") or {}).get(
        "added_keys") or [])
    by_key = {op["key"]: op for op in arm_b["discovery"]["candidates"]}
    contract_only_lines = {by_key[k]["line"] for k in contract_only_keys if k in by_key}
    used_for_verified = []
    for rel in arm_b["discovery"]["relations"]:
        if rel["status"] != "VERIFIED":
            continue
        if any(op["line"] in contract_only_lines for op in rel["operations"]):
            used_for_verified.append(_relation_key(rel))
    return {
        "contract": contract,
        "arm_A_no_contract": arm_a,
        "arm_B_contract_assisted": arm_b,
        "comparison": {
            "same_candidate_count": (
                len(arm_a["discovery"]["candidates"]) ==
                len(arm_b["discovery"]["candidates"])
            ),
            "same_subset_execution_budget": (
                arm_a["program_executions"] == arm_b["program_executions"]
            ),
            "a_verified_relation_keys": [list(x) for x in sorted(a_verified)],
            "b_verified_relation_keys": [list(x) for x in sorted(b_verified)],
            "new_verified_relations_from_contract": [list(x) for x in added],
            "contract_only_candidates_used_by_verified_relation": [
                list(x) for x in used_for_verified
            ],
            "contract_semantic_gain": bool(added or used_for_verified),
            "note": (
                "A contract line is only a candidate proposal; all relations "
                "are confirmed by benchmark verifier v2."
            ),
        },
    }


def _real_task(task_id: str) -> Dict[str, Any]:
    meta = REAL_SPECS[task_id]
    source = load_source(meta)
    arg_names = {
        "real_werkzeug_url_unparse": ["components"],
        "real_werkzeug_headerset_update": ["headers", "iterable"],
        "real_click_truncate_visible": ["text", "n"],
    }[task_id]
    return {
        "task_id": task_id,
        "entry": meta["entry"],
        "program": {"source": source,
                    "target_A": {"line": meta["local_target_line"]}},
        "deletion": {"p_minus_source": replace_target_with_pass(source)},
        "input_domain": {
            "args": [{"name": name} for name in arg_names],
            "cases": [c["args"] for c in meta["cases"]],
        },
    }


def main() -> int:
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    controlled = _load_controlled()
    tasks = dict(controlled)
    tasks["control_state_C_changes_state_B_controlled"] = _control_state_task()

    report: Dict[str, Any] = {
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "scope": "development fixtures only; not a new benchmark score",
        "candidate_limit": MAX_CANDIDATES,
        "tasks": {},
        "real_source_attempts": {},
    }
    log_lines = []
    for task_id, task in tasks.items():
        contract_path = None
        contract = load_default_contract(task_id, ROOT)
        if contract.available:
            contract_path = contract.path
        row = run_task(task, contract_path)
        report["tasks"][task_id] = row
        a = row["arm_A_no_contract"]["discovery"]
        b = row["arm_B_contract_assisted"]["discovery"]
        log_lines.append(
            f"{task_id}: A={a['status']} cand={len(a['candidates'])} "
            f"rel={len(a['relations'])} | B={b['status']} "
            f"cand={len(b['candidates'])} rel={len(b['relations'])} | "
            f"gain={row['comparison']['contract_semantic_gain']}")

    for task_id in REAL_SPECS:
        task = _real_task(task_id)
        row = run_task(task, None)
        report["real_source_attempts"][task_id] = row
        a = row["arm_A_no_contract"]["discovery"]
        log_lines.append(
            f"{task_id}: real-source attempt A={a['status']} "
            f"cand={len(a['candidates'])} rel={len(a['relations'])} "
            f"reason={a['reason'][:120]}")

    verified_total = sum(
        1 for rows in report["tasks"].values()
        for rel in rows["arm_B_contract_assisted"]["discovery"]["relations"]
        if rel["status"] == "VERIFIED")
    contract_gain = [
        tid for tid, rows in report["tasks"].items()
        if rows["comparison"]["contract_semantic_gain"]
    ]
    real_verified = [
        {"task_id": tid, "kind": rel["kind"], "lines": rel["source_lines"],
         "status": rel["status"], "condition_status": rel["condition_status"]}
        for tid, rows in report["real_source_attempts"].items()
        for rel in rows["arm_A_no_contract"]["discovery"]["relations"]
        if rel["status"] in ("VERIFIED", "WITNESS_ONLY")
    ]
    total_executions = sum(
        rows[arm]["program_executions"]
        for group in ("tasks", "real_source_attempts")
        for rows in report[group].values()
        for arm in ("arm_A_no_contract", "arm_B_contract_assisted"))
    total_wall = round(sum(
        rows[arm]["wall_seconds"]
        for group in ("tasks", "real_source_attempts")
        for rows in report[group].values()
        for arm in ("arm_A_no_contract", "arm_B_contract_assisted")), 4)
    report["summary"] = {
        "development_tasks": len(report["tasks"]),
        "real_source_attempts": len(report["real_source_attempts"]),
        "b_verified_relations": verified_total,
        "real_verified_or_witness_relations": real_verified,
        "contract_gain_tasks": contract_gain,
        "contract_gain_observed": bool(contract_gain),
        "model_calls": 0,
        "model_tokens": 0,
        "program_executions": total_executions,
        "wall_seconds": total_wall,
        "stories": {
            "independent": any(
                rel["kind"] == "independent" and rel["status"] == "VERIFIED"
                for rows in report["tasks"].values()
                for rel in rows["arm_B_contract_assisted"]["discovery"]["relations"]),
            "cooperative": any(
                rel["kind"] == "cooperative" and rel["status"] == "VERIFIED"
                for rows in report["tasks"].values()
                for rel in rows["arm_B_contract_assisted"]["discovery"]["relations"]),
            "coexisting": any(
                rel["kind"] == "coexisting" and rel["status"] == "VERIFIED"
                for rows in report["tasks"].values()
                for rel in rows["arm_B_contract_assisted"]["discovery"]["relations"]),
        },
    }
    out = OUT_DIR / "development.json"
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    (OUT_DIR / "development.log").write_text("\n".join(log_lines) + "\n",
                                             encoding="utf-8")
    print("\n".join(log_lines))
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
