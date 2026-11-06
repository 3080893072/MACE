"""Run the three extracted real-source tasks and record P+/P- evidence.

This runner is deliberately small.  It reuses ``benchmark_pilot.engine`` for
source compilation, textual deletion of the marked target, call observation,
and test execution.  It adds one transformation the old controlled engine did
not need: disabling an arbitrary statement line (the real masking operations
are plain assignments, not ``if`` statements).
"""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

ROOT = Path(__file__).resolve().parents[1]
import sys

if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark_pilot.engine import (  # noqa: E402
    compile_source,
    replace_target_with_pass,
    run_tests,
)

from benchmark_real_pilot.specs import TASKS  # noqa: E402


def disable_statement_lines(source: str, lines: Iterable[int]) -> str:
    """Replace any statement whose ``lineno`` is in ``lines`` with ``pass``.

    This is the assignment-line analogue of the controlled engine's
    ``_disable_if_lines``.  It is intentionally syntactic: it does not try to
    prove that the disabled statement is the only writer.
    """
    wanted: Set[int] = set(lines)

    class Disable(ast.NodeTransformer):
        def visit(self, node: ast.AST):  # noqa: ANN001 - ast visitor
            if isinstance(node, ast.stmt) and getattr(node, "lineno", None) in wanted:
                return ast.copy_location(ast.Pass(), node)
            return super().visit(node)

    tree = Disable().visit(ast.parse(source))
    return ast.unparse(ast.fix_missing_locations(tree)) + "\n"


def run_cases(source: str, entry: str, capture_line: int | None,
              cases: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    compiled = compile_source(source, capture_line)
    return {
        case["id"]: compiled.call(entry, case["args"])
        for case in cases
    }


def pair(source_plus: str, source_minus: str, entry: str, capture_line: int,
         cases: Sequence[Dict[str, Any]], disabled: Iterable[int]
         ) -> Dict[str, Any]:
    disabled = list(disabled)
    if disabled:
        # ast.unparse renumbers lines; snapshots are only needed for the
        # no-intervention base matrix, which keeps the original source.
        plus_source = disable_statement_lines(source_plus, disabled)
        minus_source = disable_statement_lines(source_minus, disabled)
        snapshot_line = None
    else:
        plus_source = source_plus
        minus_source = source_minus
        snapshot_line = capture_line
    plus = run_cases(plus_source, entry, snapshot_line, cases)
    minus = run_cases(minus_source, entry, snapshot_line, cases)
    per_case = {}
    for case in cases:
        cid = case["id"]
        a = plus[cid]
        b = minus[cid]
        per_case[cid] = {
            "plus_observation": a["observation"],
            "minus_observation": b["observation"],
            "plus_snapshot": a.get("snap"),
            "minus_snapshot": b.get("snap"),
            "equal": a["observation"] == b["observation"],
            "both_return": (
                a["observation"][0] == "return"
                and b["observation"][0] == "return"
            ),
        }
    return {"disabled_lines": disabled, "cases": per_case}


def load_source(meta: Dict[str, Any]) -> str:
    return (ROOT / meta["local_path"]).read_text(encoding="utf-8")


def run_task(task_id: str, meta: Dict[str, Any]) -> Dict[str, Any]:
    source_plus = load_source(meta)
    source_minus = replace_target_with_pass(source_plus)
    entry = meta["entry"]
    cap = meta["local_target_line"]
    cases = meta["cases"]

    base = pair(source_plus, source_minus, entry, cap, cases, [])
    masked_by_b = pair(
        source_plus, source_minus, entry, cap, cases,
        [meta["local_operation_line"]],
    )

    witness = next(c for c in cases if c["role"] == "mask_witness")
    wid = witness["id"]
    base_w = base["cases"][wid]
    b_w = masked_by_b["cases"][wid]

    mask_ok = bool(base_w["both_return"] and base_w["equal"])
    expose_ok = bool(
        b_w["plus_observation"] != b_w["minus_observation"]
    )
    # A's local write is visible immediately after A in P+ and absent in P-.
    snap_plus = base_w["plus_snapshot"] or {}
    snap_minus = base_w["minus_snapshot"] or {}
    var = meta["target_variable"]
    local_effect = var in snap_plus and var not in snap_minus

    # The only proper non-empty subset of a singleton is empty; it masks.
    minimal = mask_ok and expose_ok
    relation = "independent" if (mask_ok and expose_ok and minimal) else None

    # Existing-test evidence.  These are ports of released test assertions,
    # not executions of the upstream pytest suite.
    tests = meta.get("upstream_tests", [])
    test_plus = run_tests(source_plus, tests, entry, cap) if tests else {}
    test_minus = run_tests(source_minus, tests, entry, cap) if tests else {}
    tests_all_pass = bool(tests) and all(
        test_plus[name]["passed"] and test_minus[name]["passed"]
        for name in test_plus
    )

    # Per-case no-intervention picture, including the A-never-executed cases.
    case_rows = {}
    for case in cases:
        cid = case["id"]
        row = base["cases"][cid]
        case_rows[cid] = {
            "role": case["role"],
            "args": case["args"],
            "plus_observation": row["plus_observation"],
            "minus_observation": row["minus_observation"],
            "equal": row["equal"],
            "a_executed": row["plus_snapshot"] is not None,
            "target_in_plus_snapshot": var in (row["plus_snapshot"] or {}),
            "target_in_minus_snapshot": var in (row["minus_snapshot"] or {}),
        }

    return {
        "task_id": task_id,
        "project": meta["project"],
        "version": meta["version"],
        "license": meta["license"],
        "upstream_path": meta["upstream_path"],
        "upstream_symbol": meta["upstream_symbol"],
        "upstream_lines": meta["upstream_lines"],
        "local_path": meta["local_path"],
        "hypothetical_deletion": meta["hypothetical_deletion"],
        "target": {
            "upstream_line": meta["upstream_target_line"],
            "local_line": meta["local_target_line"],
            "variable": var,
        },
        "operation": {
            "upstream_line": meta["upstream_operation_line"],
            "local_line": meta["local_operation_line"],
            "text": source_plus.splitlines()[meta["local_operation_line"] - 1].strip(),
        },
        "mask_witness": {"case_id": wid, "args": witness["args"]},
        "checks": {
            "mask_ok": mask_ok,
            "disable_operation_exposes": expose_ok,
            "target_has_local_effect": local_effect,
            "proper_nonempty_subset_masks": False,
            "relation_minimal": minimal,
            "relation": relation,
        },
        "case_matrix": case_rows,
        "disabled_operation_matrix": masked_by_b["cases"],
        "upstream_test_status": meta["upstream_test_status"],
        "upstream_test_note": meta["upstream_test_note"],
        "upstream_tests_executed": False,
        "ported_test_results": {
            "plus": test_plus,
            "minus": test_minus,
            "all_pass": tests_all_pass,
        },
        "ground_truth_status": "PARTIAL_GROUND_TRUTH",
        "unknowns": [
            "Only the operation below A that was found by source reading is tested; "
            "no exhaustive search for other independent/cooperative/coexisting "
            "relations was performed.",
            "The extracted file is a standalone excerpt, not the whole upstream "
            "module; imports and unrelated methods are omitted.",
            "Upstream pytest was not executed in this round (see report); test "
            "evidence consists of ported released assertions and the absence of "
            "a direct upstream test where recorded.",
            "Local line numbers are excerpt line numbers; upstream line numbers "
            "are recorded separately.",
        ],
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--out", default=str(ROOT / "benchmark_real_pilot" / "results" / "results.json"))
    args = parser.parse_args()

    tasks = [run_task(tid, meta) for tid, meta in TASKS.items()]
    cand = json.loads((ROOT / "benchmark_real_pilot" / "candidates.json").read_text(encoding="utf-8"))
    relation_counts: Dict[str, int] = {}
    for task in tasks:
        relation = task["checks"]["relation"]
        if relation:
            relation_counts[relation] = relation_counts.get(relation, 0) + 1
    results = {
        "summary": {
            "candidates_reviewed": cand["reviewed"],
            "candidates_accepted": cand["accepted"],
            "candidates_rejected": cand["rejected"],
            "real_tasks_built": len(tasks),
            "tasks_with_verified_masking_relation": sum(
                1 for task in tasks if task["checks"]["relation"]
            ),
            "relation_counts": relation_counts,
            "upstream_suite_executed": False,
        },
        "tasks": tasks,
        "upstream_suite_executed": False,
        "upstream_suite_blocker": (
            "Executing the downloaded PyPI sdists' pytest suite was classified "
            "as running external code before the specific project/version was "
            "named by the user.  This round therefore does not claim that the "
            "whole upstream suite was executed."
        ),
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(results, ensure_ascii=False, indent=2, default=str) + "\n",
                   encoding="utf-8")
    print(f"wrote {out}")
    for task in results["tasks"]:
        checks = task["checks"]
        print(
            f"{task['task_id']}: relation={checks['relation']} "
            f"mask_ok={checks['mask_ok']} exposes={checks['disable_operation_exposes']} "
            f"local_effect={checks['target_has_local_effect']} "
            f"tests_pass={task['ported_test_results']['all_pass']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
