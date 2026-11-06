"""Independently re-run the five upstream tests on P+ and P-.

This is an executability check for the frozen blind task, not a scorer.  It
reads the frozen public task, re-derives the five test cases from the embedded
upstream test block, and executes each case against

* the installed ``requests 2.31.0`` function,
* the frozen P+ source,
* the frozen P- source,

recording the observation, whether the target line executed, the local state
right after A, and the test-gap class.  It then compares its own labels with
the frozen private oracle and fails loudly on any disagreement.

Run:
    python scripts/verify_real_task_story.py
"""
from __future__ import annotations

import ast
import copy
import hashlib
import inspect
import json
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

OUT = ROOT / "benchmark_blind_v1"
PUBLIC = OUT / "public" / "task_01_parse_header_links.json"
PRIVATE = OUT / "private" / "task_01_oracle.json"
FREEZE = OUT / "FREEZE.json"
RUN_DIR = OUT / "executability"


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def dump(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump(value), encoding="utf-8", newline="\n")


def normalize(value: Any) -> Any:
    """Type-aware, order-insensitive JSON form used only for comparison."""
    if isinstance(value, dict):
        return {"dict": sorted((normalize(k), normalize(v)) for k, v in value.items())}
    if isinstance(value, (list, tuple)):
        return ["seq", [normalize(v) for v in value]]
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, int):
        return ["int", value]
    if isinstance(value, str):
        return ["str", value]
    if value is None:
        return ["none"]
    return [type(value).__name__, repr(value)]


def execute(source: str, entry: str, value: str, target_line: int) -> Dict[str, Any]:
    namespace: Dict[str, Any] = {"__name__": "__story_check__"}
    exec(compile(source, "<frozen-task>", "exec"), namespace)  # noqa: S102
    fn = namespace[entry]

    captured: Dict[str, Any] = {"target_executed": False, "snapshot": None}

    def local_trace(frame, event, arg):
        if event == "line":
            if frame.f_lineno == target_line:
                captured["target_executed"] = True
            elif frame.f_lineno == target_line + 1 and captured["snapshot"] is None:
                captured["snapshot"] = {
                    name: copy.deepcopy(frame.f_locals[name])
                    for name in ("value", "replace_chars", "links")
                    if name in frame.f_locals
                }
        return local_trace

    def global_trace(frame, event, arg):
        if event == "call" and frame.f_code.co_name == entry:
            return local_trace
        return None

    observation: Any
    try:
        sys.settrace(global_trace)
        try:
            result = fn(value)
        finally:
            sys.settrace(None)
        observation = ["return", normalize(result)]
        raised = None
    except Exception as exc:  # noqa: BLE001 - exceptions are observations
        sys.settrace(None)
        observation = ["raise", type(exc).__name__, str(exc)]
        raised = f"{type(exc).__name__}: {exc}"
    return {
        "observation": observation,
        "raised": raised,
        "target_executed": captured["target_executed"],
        "snapshot_after_A": (normalize(captured["snapshot"])
                             if captured["snapshot"] is not None else None),
    }


def load_cases(public: Dict[str, Any]) -> List[Tuple[str, Any, Any]]:
    tree = ast.parse(public["existing_tests"]["adapted_source"])
    func = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
    assign = next(n for n in ast.walk(func)
                  if isinstance(n, ast.Assign)
                  and any(isinstance(t, ast.Name) and t.id == "cases" for t in n.targets))
    cases = ast.literal_eval(assign.value)
    return [(f"t{i}", value, expected) for i, (value, expected) in enumerate(cases, 1)]


def main() -> int:
    public = json.loads(PUBLIC.read_text(encoding="utf-8"))
    private = json.loads(PRIVATE.read_text(encoding="utf-8"))
    freeze = json.loads(FREEZE.read_text(encoding="utf-8"))
    if sha256_bytes(PUBLIC.read_bytes()) != freeze["public_sha256"]:
        raise SystemExit("public task hash does not match FREEZE.json")
    if sha256_bytes(PRIVATE.read_bytes()) != freeze["private_sha256"]:
        raise SystemExit("private oracle hash does not match FREEZE.json")

    # Provenance: the embedded function must be byte-identical to installed requests.
    import requests  # noqa: PLC0415

    installed_source = inspect.getsource(requests.utils.parse_header_links)
    embedded = public["program"]["source"].replace("  # TARGET_A", "")
    embedded = embedded[embedded.index("def "):]
    if installed_source.strip() != embedded.strip():
        raise SystemExit("embedded function differs from installed requests")
    version = requests.__version__
    if version != "2.31.0":
        raise SystemExit(f"expected requests 2.31.0, found {version}")

    entry = public["program"]["entry"]
    target_line = public["program"]["target_A"]["line"]
    plus_source = public["program"]["source"]
    minus_source = public["deletion"]["p_minus_source"]
    if sha256_bytes(plus_source.encode()) != public["program"]["source_sha256"]:
        raise SystemExit("P+ source hash mismatch")
    if sha256_bytes(minus_source.encode()) != public["deletion"]["p_minus_source_sha256"]:
        raise SystemExit("P- source hash mismatch")

    # The upstream test block itself must pass against the installed function.
    test_ns: Dict[str, Any] = {"parse_header_links": requests.utils.parse_header_links}
    exec(compile(public["existing_tests"]["adapted_source"], "<upstream-test>", "exec"),
         test_ns)  # noqa: S102
    upstream_test_passed = True
    upstream_error = None
    try:
        test_ns["test_parse_header_links"]()
    except Exception as exc:  # noqa: BLE001
        upstream_test_passed = False
        upstream_error = f"{type(exc).__name__}: {exc}"

    cases = load_cases(public)
    rows: List[Dict[str, Any]] = []
    for case_id, value, expected in cases:
        plus = execute(plus_source, entry, value, target_line)
        minus = execute(minus_source, entry, value, target_line)
        installed_result = requests.utils.parse_header_links(value)
        expected_norm = normalize(expected)
        plus_passed = plus["observation"] == ["return", expected_norm]
        minus_passed = minus["observation"] == ["return", expected_norm]
        installed_passed = normalize(installed_result) == expected_norm
        observations_equal = plus["observation"] == minus["observation"]
        local_effect = plus["snapshot_after_A"] != minus["snapshot_after_A"]
        if not plus_passed or not minus_passed:
            gap = "test_broken"
        elif plus_passed != minus_passed:
            gap = "would_be_caught"
        elif not observations_equal:
            gap = "assertion_gap"
        elif local_effect:
            gap = "masked"
        else:
            gap = "unexercised"
        rows.append({
            "case_id": case_id,
            "value": value,
            "expected": expected,
            "installed_passed": installed_passed,
            "plus": plus,
            "minus": minus,
            "plus_test_passed": plus_passed,
            "minus_test_passed": minus_passed,
            "observations_equal": observations_equal,
            "a_has_local_effect": local_effect,
            "target_executed_plus": plus["target_executed"],
            "target_executed_minus": minus["target_executed"],
            "gap": gap,
        })

    oracle_cases = {c["case_id"]: c for c in private["test_cases"]}
    mismatches = []
    for row in rows:
        oracle = oracle_cases.get(row["case_id"])
        if oracle is None:
            mismatches.append({"case_id": row["case_id"], "reason": "missing in oracle"})
            continue
        for key, ours in (("value", row["value"]),
                          ("observations_equal", row["observations_equal"]),
                          ("a_has_local_effect", row["a_has_local_effect"]),
                          ("gap", row["gap"])):
            if oracle.get(key) != ours:
                mismatches.append({"case_id": row["case_id"], "key": key,
                                   "oracle": oracle.get(key), "ours": ours})
        if bool(oracle["plus"]["passed"]) != row["plus_test_passed"]:
            mismatches.append({"case_id": row["case_id"], "key": "plus.passed"})
        if bool(oracle["minus"]["passed"]) != row["minus_test_passed"]:
            mismatches.append({"case_id": row["case_id"], "key": "minus.passed"})

    counts = {
        "all_original_tests_pass_on_p_plus": all(r["plus_test_passed"] for r in rows),
        "all_original_tests_pass_on_p_minus": all(r["minus_test_passed"] for r in rows),
        "caught": sum(r["gap"] == "would_be_caught" for r in rows),
        "masked_with_local_effect": sum(r["gap"] == "masked" for r in rows),
        "unexercised": sum(r["gap"] == "unexercised" for r in rows),
        "assertion_gap": sum(r["gap"] == "assertion_gap" for r in rows),
        "test_broken": sum(r["gap"] == "test_broken" for r in rows),
        "a_exercised": sum(r["a_has_local_effect"] for r in rows),
        "p_plus_minus_observations_differ": sum(not r["observations_equal"] for r in rows),
    }

    payload = {
        "schema_version": "mace-story-verification-v1",
        "task_id": public["task_id"],
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "provenance": {
            "requests_version": version,
            "installed_source_sha256": sha256_bytes(installed_source.encode()),
            "embedded_source_sha256": public["program"]["source_sha256"],
            "p_minus_sha256": public["deletion"]["p_minus_source_sha256"],
            "upstream_test_path": public["existing_tests"]["provenance"]["path"],
            "upstream_test_line_range": public["existing_tests"]["provenance"]["line_range"],
            "upstream_test_block_sha256": public["existing_tests"]["provenance"]["block_sha256"],
        },
        "upstream_test_passes_on_installed": upstream_test_passed,
        "upstream_test_error": upstream_error,
        "cases": rows,
        "counts": counts,
        "oracle_agreement": {
            "matches": not mismatches,
            "mismatches": mismatches,
        },
    }
    write_json(RUN_DIR / "story_verification.json", payload)

    lines = [
        f"task_id: {public['task_id']}",
        f"requests: {version}",
        f"installed source sha256: {payload['provenance']['installed_source_sha256']}",
        f"upstream test block passes on installed function: {upstream_test_passed}",
        "",
        "case  plus  minus  local_effect  observations_equal  gap",
    ]
    for r in rows:
        lines.append(
            f"{r['case_id']:4s}  {str(r['plus_test_passed']):5s} {str(r['minus_test_passed']):5s}  "
            f"{str(r['a_has_local_effect']):12s}  {str(r['observations_equal']):18s}  {r['gap']}")
    lines += ["", f"counts: {json.dumps(counts, ensure_ascii=False)}",
              f"oracle agreement: {payload['oracle_agreement']['matches']}"]
    (RUN_DIR / "story_verification.log").write_text("\n".join(lines) + "\n",
                                                    encoding="utf-8", newline="\n")

    print("\n".join(lines))
    if not payload["oracle_agreement"]["matches"]:
        print("MISMATCH WITH FROZEN ORACLE", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
