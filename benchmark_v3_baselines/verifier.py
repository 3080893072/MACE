"""Baseline B: the deterministic intervention verifier.

The verifier receives a proposal (a list of claims) and re-executes it.  It
uses only public source and the public probes.  Its universe is the set of
operations the proposal itself names; it cannot invent operations the model
did not mention, and it cannot know the benchmark's hidden universe.  That
limitation is reported explicitly.

Verdicts
--------
VERIFIED   execution on the submitted finite input(s) agrees with the claim
REFUTED    execution contradicts the claim
UNKNOWN    the claim cannot be evaluated (bad location, budget, no evidence)
"""
from __future__ import annotations

import ast
import json
import textwrap
from typing import Any, Dict, List, Sequence, Tuple

from benchmark_v3_baselines.execution import Executor
from benchmark_v3_baselines.public_io import load_task, validate_payload

VERIFIER_VERSION = "intervention-verifier-1.0"


def _compact(text: str) -> str:
    return "".join(text.split())


def _source_lines(loaded: Dict[str, Any]) -> List[str]:
    return loaded["source_lines"]


def _op_from_ref(ref: Dict[str, Any], loaded: Dict[str, Any]) -> Dict[str, Any]:
    task = loaded["task"]
    if not isinstance(ref, dict):
        raise ValueError("operation must be an object")
    file = ref.get("file")
    line = ref.get("line")
    if not isinstance(file, str) or not isinstance(line, int) or line < 1:
        raise ValueError("operation needs file and positive integer line")
    if file != task["source_file"]:
        raise ValueError(f"operation file is not the target source: {file}")
    lines = _source_lines(loaded)
    if line > len(lines):
        raise ValueError(f"line {line} is outside {file}")
    end = ref.get("end_line", line)
    if not isinstance(end, int) or end < line or end > len(lines):
        raise ValueError("invalid end_line")
    actual = "\n".join(lines[line - 1:end])
    code = ref.get("code")
    if code is not None and _compact(code) != _compact(actual):
        raise ValueError("submitted code does not match the source text")
    try:
        # The range is extracted from inside a function body, so it carries
        # the original indentation; dedent before the standalone parse.
        ast.parse(textwrap.dedent(actual))
    except SyntaxError as exc:
        raise ValueError(f"line range does not parse as a statement: {exc}")
    return {
        "id": f"{file}:{line}-{end}",
        "file": file,
        "first_line": line,
        "last_line": end,
        "kind": "block" if end > line else "assignment",
        "code": actual,
    }


def proposal_universe(submission: Dict[str, Any],
                      loaded: Dict[str, Any],
                      max_ops: int) -> Tuple[List[Dict[str, Any]], List[str]]:
    ops: Dict[str, Dict[str, Any]] = {}
    problems: List[str] = []
    for index, claim in enumerate(submission.get("claims") or []):
        if not isinstance(claim, dict):
            continue
        for ref in claim.get("operations") or []:
            try:
                op = _op_from_ref(ref, loaded)
            except ValueError as exc:
                problems.append(f"claim[{index}]: {exc}")
                continue
            ops.setdefault(op["id"], op)
    ordered = sorted(ops.values(),
                     key=lambda op: (op["first_line"], op["last_line"]))
    if len(ordered) > max_ops:
        problems.append(
            f"proposal names {len(ordered)} operations; only the first "
            f"{max_ops} are used by the verifier")
        ordered = ordered[:max_ops]
    return ordered, problems


def _verdict(status: str, reason: str, **extra: Any) -> Dict[str, Any]:
    out = {"verdict": status, "reason": reason}
    out.update(extra)
    return out


def verify_claim(claim: Dict[str, Any], loaded: Dict[str, Any],
                 executor: Executor, max_inputs: int) -> Dict[str, Any]:
    task = loaded["task"]
    if not isinstance(claim, dict) or not isinstance(claim.get("type"), str):
        return _verdict("UNKNOWN", "claim must be an object with a type")
    kind = claim["type"]
    if kind == "PROVEN":
        return _verdict("UNKNOWN", "no proof checker exists in this verifier")
    if kind == "EXPOSING_COUNTEREXAMPLE":
        payload = claim.get("input")
        errors = validate_payload(task, payload)
        if errors:
            return _verdict("REFUTED", "illegal input: " + "; ".join(errors))
        if not executor.a_executes(payload):
            return _verdict("REFUTED", "A does not execute on this input")
        plus = executor.observation([], "plus", payload)
        minus = executor.observation([], "minus", payload)
        if plus.get("__probe_error__") or minus.get("__probe_error__"):
            return _verdict("UNKNOWN", "probe did not produce an observation")
        if plus == minus:
            return _verdict("REFUTED", "P+ and P- observations are equal")
        return _verdict("VERIFIED", "P+ and P- differ on the submitted input",
                        observations={"plus": plus, "minus": minus})
    if kind in ("MSMS", "MMBS"):
        payloads = claim.get("inputs")
        if payloads is None:
            payloads = [claim.get("input")]
        if not isinstance(payloads, list) or not payloads:
            return _verdict("UNKNOWN", "claim has no input or inputs list")
        ids = []
        for ref in claim.get("operations") or []:
            try:
                ids.append(_op_from_ref(ref, loaded)["id"])
            except ValueError as exc:
                return _verdict("UNKNOWN", str(exc))
        if not ids:
            return _verdict("REFUTED", "empty operation set")
        target = sorted(set(ids))
        details = []
        for payload in payloads:
            errors = validate_payload(task, payload)
            if errors:
                return _verdict("REFUTED", "illegal input: " + "; ".join(errors))
            if not executor.a_executes(payload):
                return _verdict("REFUTED",
                                "A does not execute on a submitted input")
            rel = executor.relations(payload, executor.universe.keys())
            computed = rel["msms_ids"] if kind == "MSMS" else rel["mmbs_ids"]
            matched = target in [sorted(item) for item in computed]
            details.append({"input": payload, "matched": matched,
                            "computed_minimal_sets": computed,
                            "masked_at_empty": rel["masked"].get("EMPTY", False)})
            if not matched:
                if kind == "MSMS" and not rel["masked"].get("EMPTY", False):
                    return _verdict("REFUTED",
                                    "a submitted input is not masked at EMPTY",
                                    inputs=details)
                return _verdict(
                    "REFUTED",
                    "set is not a minimal relation over the proposal's "
                    "operation universe on a submitted input",
                    inputs=details)
        return _verdict(
            "VERIFIED",
            "set matches an enumerated minimal relation over the "
            "proposal's operation universe on every submitted input",
            inputs=details,
            scope=("only the operations the proposal named were "
                   "enumerated; a missing operation can weaken or "
                   "invalidate the relation against the hidden universe"))
    if kind == "PREREQUISITE_BREAKING":
        payload = claim.get("input")
        control = claim.get("control_input")
        for name, value in (("input", payload), ("control_input", control)):
            errors = validate_payload(task, value)
            if errors:
                return _verdict("REFUTED", f"{name}: " + "; ".join(errors))
        ids = []
        for ref in claim.get("operations") or []:
            try:
                ids.append(_op_from_ref(ref, loaded)["id"])
            except ValueError as exc:
                return _verdict("UNKNOWN", str(exc))
        if not ids:
            return _verdict("REFUTED", "empty operation set")
        for name, value in (("input", payload), ("control_input", control)):
            if not executor.a_executes(value):
                return _verdict("REFUTED", f"A does not execute on {name}")
        conditioned = executor.relations(payload, executor.universe.keys())
        control_rel = executor.relations(control, executor.universe.keys())
        target = sorted(set(ids))
        condition_ok = (
            conditioned["masked"].get("EMPTY", False)
            and target in [sorted(item) for item in conditioned["mmbs_ids"]])
        control_ok = target not in [
            sorted(item) for item in control_rel["mmbs_ids"]]
        if condition_ok and control_ok:
            return _verdict("VERIFIED",
                            "minimal breaking set on input, not breaking on control")
        return _verdict("REFUTED",
                        "the two inputs do not satisfy the stated pattern")
    if kind == "CONDITIONAL_CORRECTNESS":
        return _verdict("UNKNOWN",
                        "conditional-correctness claims are not produced by "
                        "this baseline and are not verified here")
    return _verdict("UNKNOWN", f"unsupported claim type: {kind}")


def verify_submission(task_id: str, submission: Dict[str, Any], *,
                      max_ops: int = 6,
                      max_inputs: int = 8,
                      variant_prefix: str | None = None) -> Dict[str, Any]:
    loaded = load_task(task_id)
    task = loaded["task"]
    universe, problems = proposal_universe(submission, loaded, max_ops)
    executor = Executor(task_id, task["project_id"],
                        task.get("probe") or _probe_for(task_id),
                        task["target_operation"],
                        variant_prefix or f"b_{task_id}")
    executor.set_universe(universe)
    verdicts = []
    for index, claim in enumerate(submission.get("claims") or []):
        result = verify_claim(claim, loaded, executor, max_inputs)
        result["index"] = index
        result["type"] = claim.get("type") if isinstance(claim, dict) else None
        verdicts.append(result)
    verified_claims = [
        claim for claim, verdict in zip(submission.get("claims") or [], verdicts)
        if verdict["verdict"] == "VERIFIED"
    ]
    return {
        "verifier_version": VERIFIER_VERSION,
        "task_id": task_id,
        "universe": universe,
        "universe_problems": problems,
        "verdicts": verdicts,
        "verified_submission": {
            "task_id": task_id,
            "submission_id": submission.get("submission_id", "baseline-B"),
            "claims": verified_claims,
        },
        "counts": {
            "total": len(verdicts),
            "verified": sum(1 for v in verdicts if v["verdict"] == "VERIFIED"),
            "refuted": sum(1 for v in verdicts if v["verdict"] == "REFUTED"),
            "unknown": sum(1 for v in verdicts if v["verdict"] == "UNKNOWN"),
        },
        "probe_executions": executor.probe_executions,
    }


def _probe_for(task_id: str) -> str:
    probes = {
        "jinja2_bytecode_cache_read": "probe_jinja_bytecode_cache.py",
        "werkzeug_bind_server_name_lower": "probe_werkzeug_bind_server_name.py",
        "werkzeug_filestorage_stream_name": "probe_werkzeug_filestorage.py",
        "werkzeug_get_host_default_empty": "probe_werkzeug_get_host.py",
        "werkzeug_secure_filename_ascii_filter": "probe_werkzeug_secure_filename.py",
    }
    return probes[task_id]
