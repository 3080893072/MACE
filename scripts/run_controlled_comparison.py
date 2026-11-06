"""Functional comparison on the three old controlled Pilot tasks.

This script does not modify the Pilot tasks, oracle, attribution, or frozen
blind task.  It builds in-memory fixtures from the public Pilot task JSON and
runs the methods' *existing* interfaces:

* ``pure_symbolic`` -- ``mace.symbolic.derive_guard`` (the M6 "Pure Symbolic"
  method), plus the existing bounded guard checker;
* ``direct_qwen`` -- ``mace.loop.run_mode(mode="direct")``, guard-only baseline;
* ``full_mace``   -- ``mace.loop.run_mode(mode="mace")``, the full contract
  pipeline with the existing bounded verifier.

Capabilities that an interface does not expose are recorded as
``UNSUPPORTED_INTERFACE``, not as a wrong answer.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from mace import sandbox  # noqa: E402
from mace.contracts import ContractError, parse_bundle  # noqa: E402
from mace.domain import Domain, input_sorts  # noqa: E402
from mace.fixture import Fixture  # noqa: E402
from mace.loop import _guard_only_bundle, run_mode  # noqa: E402
from mace.symbolic import derive_guard  # noqa: E402

TASK_IDS = ("ctrl_01", "ctrl_02", "ctrl_03")
OUT = ROOT / "benchmark_blind_v1" / "executability"


class PilotFixture(Fixture):
    """Fixture with an explicit legal-domain description.

    ``Fixture.domain_text`` assumes an uncoupled Cartesian product.  ctrl_03's
    declared domain is a union of five regimes, so the text is supplied here
    instead of being inferred incorrectly.
    """

    def __init__(self, *args, domain_text: str, **kwargs):
        super().__init__(*args, **kwargs)
        self._domain_text = domain_text

    def domain_text(self) -> str:
        return self._domain_text


def load_tasks() -> Dict[str, Dict[str, Any]]:
    data = json.loads((ROOT / "benchmark_pilot" / "tasks.json").read_text(encoding="utf-8"))
    return {t["task_id"]: t for t in data["tasks"] if t["task_id"] in TASK_IDS}


def make_fixture(task: Dict[str, Any]) -> PilotFixture:
    spec = task["input_domain"]
    cases = [{k: v for k, v in case.items() if k != "id"} for case in spec["cases"]]
    sorts = input_sorts(spec)
    domain_spec = {k: v for k, v in spec.items() if k != "cases"}
    domain = Domain(cases, True, domain_spec)
    args = ", ".join(f"{a['name']}: {a['sort']}" for a in spec["args"])
    return PilotFixture(
        config={"id": task["task_id"], "entry": "program",
                "domain": domain_spec, "channels": 1},
        source=task["program"]["source"],
        domain=domain, arg_sorts=sorts, functions={}, channels=1, entry="program",
        domain_text=f"{args}; the declared finite set has {len(cases)} cases "
                    f"({spec.get('note', '')}).")


def check_guard(fixture: Fixture, guard: str | None) -> Dict[str, Any]:
    if not guard:
        return {"status": "ABSENT", "exact": False, "sound": None,
                "complete": None, "unsound": None, "incomplete": None}
    start = time.perf_counter()
    try:
        bundle = parse_bundle(_guard_only_bundle(guard), allow_guard_only=True)
        report = sandbox.analyze(
            fixture.source, list(fixture.domain.cases), bundle.to_dict(),
            arg_sorts=fixture.arg_sorts, functions=fixture.functions,
            channels=fixture.channels, level="BOUNDED", entry=fixture.entry,
            timeout=300.0)
    except (ContractError, sandbox.SandboxError, ValueError) as exc:
        return {"status": "INVALID", "exact": False, "sound": False,
                "complete": False, "unsound": None, "incomplete": None,
                "error": f"{type(exc).__name__}: {exc}",
                "wall_seconds": round(time.perf_counter() - start, 3)}
    g = report.get("guard") or {}
    status = g.get("status")
    typed = status not in ("INVALID", "ERROR", None)
    return {
        "status": status,
        "exact": bool(typed and g.get("unsound") == 0 and g.get("incomplete") == 0),
        "sound": bool(typed and g.get("unsound") == 0),
        "complete": bool(typed and g.get("incomplete") == 0),
        "unsound": g.get("unsound"),
        "incomplete": g.get("incomplete"),
        "counterexamples": g.get("counterexamples") or [],
        "typed": typed,
        "wall_seconds": round(time.perf_counter() - start, 3),
    }


def run_symbolic(task: Dict[str, Any]) -> Dict[str, Any]:
    fixture = make_fixture(task)
    start = time.perf_counter()
    try:
        result = derive_guard(fixture, use_summaries=False)
        error = None
    except Exception as exc:  # noqa: BLE001 - record, do not hide
        result = {"status": "ERROR", "guard": None, "reason": str(exc)}
        error = f"{type(exc).__name__}: {exc}"
    guard = result.get("guard")
    check = check_guard(fixture, guard)
    return {
        "method": "pure_symbolic",
        "task_id": task["task_id"],
        "status": result.get("status", "UNKNOWN"),
        "error": error,
        "guard": guard,
        "guard_check": check,
        "coverage": result.get("coverage"),
        "reason": result.get("reason"),
        "wall_seconds": round(time.perf_counter() - start, 3),
        "tokens": {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0,
                   "llm_calls": 0},
        "capabilities": {
            "guard": ("SUPPORTED" if guard else "UNKNOWN"),
            "masking_operation_sets": "UNSUPPORTED_INTERFACE",
            "valid_counterexample": "UNSUPPORTED_INTERFACE",
            "test_gap": "UNSUPPORTED_INTERFACE",
        },
        "interface_note": ("derive_guard returns a source-level guard and coverage; "
                           "it does not enumerate operation subsets or map tests."),
    }


def run_llm_method(task: Dict[str, Any], method: str,
                   client: Any, rounds: int) -> Dict[str, Any]:
    fixture = make_fixture(task)
    mode = "direct" if method == "direct_qwen" else "mace"
    out_dir = OUT / "runs" / task["task_id"] / method
    start = time.perf_counter()
    try:
        result = run_mode(fixture, client, mode, rounds=rounds, seed=42,
                          out_dir=out_dir, timeout=300.0, guard_source="qwen")
        error = None
    except Exception as exc:  # noqa: BLE001
        result = {"status": "ERROR", "final_guard": None, "final_report": None,
                  "final_bundle": None, "usage": {}, "exchanges": []}
        error = f"{type(exc).__name__}: {exc}"
    report = result.get("final_report") or {}
    bundle = result.get("final_bundle") or {}
    guard = result.get("final_guard")
    relations = report.get("relations") or []
    witnesses = report.get("witnesses") or []
    if method == "direct_qwen":
        capabilities = {
            "guard": "SUPPORTED" if guard else "UNKNOWN",
            "masking_operation_sets": "UNSUPPORTED_INTERFACE",
            "valid_counterexample": ("CHECKER_GENERATED_ONLY" if witnesses
                                     else "NOT_PRODUCED"),
            "test_gap": "UNSUPPORTED_INTERFACE",
        }
        note = ("Direct Qwen is the guard-only M5/M6 baseline; its prompt does not "
                "ask for operation sets, counterexamples, or test gaps.  Any witness "
                "comes from the checker's report, not from the model.")
    else:
        capabilities = {
            "guard": "SUPPORTED" if guard else "UNKNOWN",
            "masking_operation_sets": "UNSUPPORTED_INTERFACE",
            "valid_counterexample": ("CHECKER_GENERATED_ONLY" if witnesses
                                     else "NOT_PRODUCED"),
            "test_gap": "UNSUPPORTED_INTERFACE",
        }
        note = ("Full MACE emits typed relations and their conditions (a semantic "
                "masking explanation), then the checker supplies witnesses.  The "
                "contract schema does not enumerate downstream operation subsets "
                "and does not classify tests.")
    return {
        "method": method,
        "task_id": task["task_id"],
        "status": result.get("status"),
        "error": error,
        "guard": guard,
        "guard_check": check_guard(fixture, guard),
        "relations": [
            {"id": r.get("id"), "kind": r.get("kind"), "status": r.get("status"),
             "expr": r.get("expr"), "condition": r.get("condition"),
             "failures": r.get("failures"), "checked": r.get("checked")}
            for r in relations
        ],
        "relation_count": len(relations),
        "witness_count": len(witnesses),
        "witnesses": witnesses,
        "usage": result.get("usage"),
        "model": result.get("model"),
        "rounds_used": result.get("rounds_used"),
        "capabilities": capabilities,
        "interface_note": note,
        "wall_seconds": round(time.perf_counter() - start, 3),
        "raw_exchanges": result.get("exchanges"),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--methods", default="pure_symbolic",
                        help="comma list: pure_symbolic,direct_qwen,full_mace")
    parser.add_argument("--model-path", default=None)
    parser.add_argument("--rounds", type=int, default=3)
    parser.add_argument("--out", default=str(OUT / "controlled_comparison.json"))
    args = parser.parse_args()
    methods = [m.strip() for m in args.methods.split(",") if m.strip()]
    tasks = load_tasks()

    client = None
    if any(m in ("direct_qwen", "full_mace") for m in methods):
        if not args.model_path:
            raise SystemExit("--model-path is required for Qwen methods")
        from scripts.local_qwen_client import LocalQwenClient  # noqa: PLC0415
        client = LocalQwenClient(args.model_path, max_new_tokens=1024,
                                 temperature=0.0, seed=42)

    rows: List[Dict[str, Any]] = []
    for task_id in TASK_IDS:
        task = tasks[task_id]
        for method in methods:
            print(f"== {task_id} {method}", flush=True)
            if method == "pure_symbolic":
                row = run_symbolic(task)
            elif method in ("direct_qwen", "full_mace"):
                row = run_llm_method(task, method, client, args.rounds)
            else:
                raise SystemExit(f"unknown method {method}")
            rows.append(row)
            print(json.dumps({k: row.get(k) for k in
                              ("task_id", "method", "status", "guard", "guard_check")},
                             ensure_ascii=False)[:1200], flush=True)

    model_info = None
    if client is not None:
        try:
            model_info = client.model_info()
        except Exception as exc:  # noqa: BLE001
            model_info = {"error": f"{type(exc).__name__}: {exc}"}
    payload = {
        "schema_version": "mace-controlled-functional-comparison-v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "pilot_only": True,
        "note": ("ctrl_01/02/03 have been reviewed repeatedly and are Pilot tasks, "
                 "not a new independent test set.  No historical label was changed."),
        "model": model_info,
        "methods": methods,
        "tasks": rows,
    }
    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8", newline="\n")
    print("WROTE", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
