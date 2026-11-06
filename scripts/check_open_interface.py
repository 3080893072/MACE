"""Interface feasibility check for open-ended masking discovery.

The question is narrow:

    Can Direct Qwen and the unmodified Full MACE pipeline accept the *same*
    open-discovery submission protocol and output operation positions,
    independent/cooperative masking relations, and input evidence?

This script does not create new tasks and does not use the hidden oracle to
change a model's reasoning.  It reads the old controlled Pilot tasks only to
build fixtures and to verify submissions.  The hidden operation lines are used
by the verifier, never placed in a prompt.

Run:
    python scripts/check_open_interface.py --model-path D:/tmp/qwen15b
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import itertools
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, FrozenSet, Iterable, List, Optional, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark_pilot import engine  # noqa: E402
from mace.loop import run_mode  # noqa: E402
from mace.qwen import Response, extract_json  # noqa: E402
from scripts.run_controlled_comparison import load_tasks, make_fixture  # noqa: E402

TASK_IDS = ("ctrl_01", "ctrl_02", "ctrl_03")
OUT = ROOT / "benchmark_open_v1" / "interface"
SCHEMA = ROOT / "benchmark_open_v1" / "SUBMISSION_SCHEMA.json"
ATTRIBUTION = ROOT / "benchmark_pilot" / "attribution.json"
MAX_RELATIONS = 5


# ---------------------------------------------------------------------------
# Generic public prompt
# ---------------------------------------------------------------------------

def numbered_source(source: str) -> str:
    return "\n".join(f"{i:>3} | {line}" for i, line in enumerate(source.splitlines(), 1))


def public_task(task: Dict[str, Any]) -> Dict[str, Any]:
    """The public view used by both methods.  No operation labels."""
    spec = task["input_domain"]
    return {
        "task_id": task["task_id"],
        "program": {
            "source": task["program"]["source"],
            "entry": task["entry"],
            "target_A": task["program"]["target_A"],
        },
        "deletion": task["deletion"],
        "input_domain": {
            "args": spec["args"],
            "cases": spec["cases"],
            "note": spec.get("note"),
        },
        "observable_behavior": task["observable_behavior"],
        "existing_tests": [
            {"name": t["name"], "input": t["input"], "source": t["source"]}
            for t in task["existing_tests"]
        ],
    }


def open_prompt(task: Dict[str, Any]) -> str:
    public = public_task(task)
    source = numbered_source(public["program"]["source"])
    target = public["program"]["target_A"]
    tests = "\n\n".join(
        f"### {t['name']}\n```python\n{t['source']}```\ninput: {json.dumps(t['input'], ensure_ascii=False)}"
        for t in public["existing_tests"])
    cases = json.dumps(public["input_domain"]["cases"], ensure_ascii=False)
    args = json.dumps(public["input_domain"]["args"], ensure_ascii=False)
    return f"""You are analysing a proposed deletion in a Python function.  Use only
the public information below.  A Python exception is an observation.  The best
evidence level is BOUNDED: execution on the declared finite domain, never a proof.

## Program with source line numbers
```text
{source}
```

## Target A
Line {target['line']}: `{target['text'].strip()}`
Deletion rule: replace exactly this line with `pass` at the same indentation.

## Legal inputs
Arguments: {args}
Frozen legal cases: {cases}
Every reported input must be one of these exact cases.

## Observable
{public['observable_behavior']['kind']}: {public['observable_behavior']['equality']}

## Existing tests
{tests}

## What to find
Find downstream operations (statements other than the target A) that can make
A's local effect unobservable.  An operation is a downstream statement such as
an `if`; report its 1-based source line.  Do not use any hidden operation name.

For each relation, report:
- `operations`: one or more downstream operations, each with `line` and `text`.
- `kind`:
  - `independent`: one operation alone makes P+ and P- observationally equal;
  - `cooperative`: two or more operations together make them equal, but no
    proper non-empty subset does;
  - `coexisting`: two or more operations must be disabled together to make
    P+ and P- observationally different, while no proper subset does.
- `input`: one exact legal case where the relation holds.
- `condition`: a boolean expression over the argument names that describes
  where this relation holds.  Use only the arguments, int/bool constants,
  comparisons, arithmetic, `and`, `or`, `not`.  No function calls, attribute
  access, or string constants.  For independent/cooperative the condition means
  "the declared set, enabled alone, masks A"; for coexisting it means
  "disabling the declared set exposes A".
- `explanation`: one sentence.
- `counterexample`: null, or {{"input": <exact legal case where deleting A
  changes the observable>}}.

Return at most {MAX_RELATIONS} different relations.  Do not repeat the same
operation set and kind.  If you cannot find any, return an empty list.

## Required JSON
{{
  "task_id": "{public['task_id']}",
  "relations": [
    {{
      "operations": [{{"line": <int>, "text": "<source line>"}}],
      "kind": "independent | cooperative | coexisting",
      "input": {{<argument>: <value>}},
      "condition": "<restricted boolean expression>",
      "explanation": "<one sentence>",
      "counterexample": null
    }}
  ],
  "guard": {{"expr": "<restricted boolean expression; true when A is masked>", "status": "BOUNDED | UNKNOWN"}},
  "test_gap": [{{"test": "<existing test name>", "verdict": "unexercised | masked | would_be_caught | assertion_gap | test_broken | not_covered"}}],
  "evidence": "<optional executable observations>"
}}
Return one JSON object and no prose outside it.
"""


# ---------------------------------------------------------------------------
# Private verification context
# ---------------------------------------------------------------------------

class Verifier:
    def __init__(self, task: Dict[str, Any], attribution: Dict[str, Any]):
        self.task = task
        self.attr = attribution
        self.source_plus = task["program"]["source"]
        self.source_minus = task["deletion"]["p_minus_source"]
        self.entry = task["entry"]
        self.target_line = task["program"]["target_A"]["line"]
        self.op_lines = {k: int(v) for k, v in attribution["op_lines"].items()}
        self.ops = list(attribution["ops"])
        self.arg_names = [a["name"] for a in task["input_domain"]["args"]]
        self.cases = [(f"case_{i:04d}", c) for i, c in
                      enumerate({k: v for k, v in c.items() if k != "id"}
                                for c in task["input_domain"]["cases"])]
        self.case_ids = {self.key(args): cid for cid, args in self.cases}
        self.executions = 0
        self._line_to_op = self._build_line_map()
        self._plus = engine.compile_source(self.source_plus, capture_line=self.target_line)
        self._minus = engine.compile_source(self.source_minus, capture_line=self.target_line)
        self.plus_rows = self._run_rows(self._plus)
        self.minus_rows = self._run_rows(self._minus)
        self.base_equal = {cid: self.plus_rows[cid]["observation"] ==
                                self.minus_rows[cid]["observation"]
                           for cid, _ in self.cases}
        self.local_effect = {cid: self.plus_rows[cid]["snap"] != self.minus_rows[cid]["snap"]
                             for cid, _ in self.cases}
        self._matrix_cache: Dict[FrozenSet[str], Dict[str, Any]] = {}

    @staticmethod
    def key(args: Dict[str, Any]) -> str:
        return json.dumps(args, sort_keys=True, ensure_ascii=False)

    def _run_rows(self, compiled: engine.Compiled) -> Dict[str, Any]:
        self.executions += len(self.cases)
        return engine.run_source_cases(compiled, self.entry, self.cases)

    def _build_line_map(self) -> Dict[int, str]:
        line_to_op: Dict[int, str] = {}
        tree = ast.parse(self.source_plus)
        for node in ast.walk(tree):
            if isinstance(node, ast.If) and node.lineno in self.op_lines.values():
                op = next(k for k, v in self.op_lines.items() if v == node.lineno)
                line_to_op[node.lineno] = op
                for stmt in node.body:
                    if isinstance(stmt, ast.stmt):
                        line_to_op.setdefault(stmt.lineno, op)
        return line_to_op

    def op_for_line(self, line: int) -> Optional[str]:
        return self._line_to_op.get(line)

    def matrix(self, disabled: FrozenSet[str]) -> Dict[str, Any]:
        if disabled not in self._matrix_cache:
            rows = engine.run_variant_pairs(
                self.source_plus, self.source_minus, self.entry,
                self.op_lines, [disabled], self.cases)
            self.executions += len(self.cases) * 2
            self._matrix_cache[disabled] = rows[disabled]
        return self._matrix_cache[disabled]

    def only_equal(self, ops: Iterable[str]) -> Dict[str, bool]:
        s = frozenset(ops)
        return self.matrix(frozenset(set(self.ops) - set(s)))["equal"]

    def disabled_equal(self, ops: Iterable[str]) -> Dict[str, bool]:
        return self.matrix(frozenset(ops))["equal"]

    def legal_case(self, value: Any) -> Optional[str]:
        if not isinstance(value, dict):
            return None
        try:
            return self.case_ids.get(self.key(value))
        except TypeError:
            return None

    def actual_relation_holds(self, kind: str, ops: FrozenSet[str]) -> Dict[str, bool]:
        if kind in ("independent", "cooperative"):
            return self.only_equal(ops)
        if kind == "coexisting":
            return {cid: not v for cid, v in self.disabled_equal(ops).items()}
        raise ValueError(kind)

    def verify_relation(self, relation: Any) -> Dict[str, Any]:
        out: Dict[str, Any] = {"status": "UNVERIFIED", "checks": {}}
        if not isinstance(relation, dict):
            out.update({"status": "FORMAT_ERROR", "reason": "relation is not an object"})
            return out
        raw_ops = relation.get("operations")
        if not isinstance(raw_ops, list) or not raw_ops:
            out.update({"status": "FORMAT_ERROR", "reason": "missing operations"})
            return out
        lines: List[int] = []
        for item in raw_ops:
            if not isinstance(item, dict) or not isinstance(item.get("line"), int):
                out.update({"status": "FORMAT_ERROR", "reason": "operation must have an int line"})
                return out
            lines.append(item["line"])
        if len(set(lines)) != len(lines):
            out.update({"status": "FORMAT_ERROR", "reason": "duplicate operation line"})
            return out
        ops = []
        for line in lines:
            op = self.op_for_line(line)
            if op is None:
                out.update({"status": "UNVERIFIED",
                            "reason": f"line {line} is not a declared downstream operation",
                            "reported_lines": lines})
                return out
            ops.append(op)
        s = frozenset(ops)
        kind = relation.get("kind")
        out["operations"] = sorted(s)
        out["kind"] = kind
        if kind not in ("independent", "cooperative", "coexisting"):
            out.update({"status": "FALSE", "reason": "invalid kind"})
            return out
        if kind == "independent" and len(s) != 1:
            out.update({"status": "FALSE", "reason": "independent relation must name one operation"})
            return out
        if kind in ("cooperative", "coexisting") and len(s) < 2:
            out.update({"status": "FALSE", "reason": f"{kind} relation must name at least two operations"})
            return out
        cid = self.legal_case(relation.get("input"))
        if cid is None:
            out.update({"status": "UNVERIFIED", "reason": "input is not one of the frozen legal cases"})
            return out
        out["case_id"] = cid
        out["input"] = relation.get("input")
        out["checks"]["a_has_local_effect"] = bool(self.local_effect[cid])
        out["checks"]["original_masks"] = bool(self.base_equal[cid])
        if not self.local_effect[cid]:
            out.update({"status": "FALSE", "reason": "A has no local effect on this input"})
            return out
        if not self.base_equal[cid]:
            out.update({"status": "FALSE", "reason": "the original program does not mask A on this input"})
            return out
        if kind in ("independent", "cooperative"):
            out["checks"]["only_set_masks"] = bool(self.only_equal(s)[cid])
            out["checks"]["disabling_set_exposes"] = not bool(self.disabled_equal(s)[cid])
            if not out["checks"]["only_set_masks"]:
                out.update({"status": "FALSE", "reason": "the declared set enabled alone does not mask A"})
                return out
            if not out["checks"]["disabling_set_exposes"]:
                out.update({"status": "FALSE", "reason": "disabling the declared set does not expose A"})
                return out
            subchecks = {}
            for r in range(1, len(s)):
                for sub in itertools.combinations(sorted(s), r):
                    subchecks[",".join(sub)] = not bool(self.only_equal(sub)[cid])
            out["checks"]["proper_subsets_do_not_mask"] = subchecks
            if not all(subchecks.values()):
                out.update({"status": "FALSE", "reason": "a proper non-empty subset also masks A"})
                return out
        else:  # coexisting
            out["checks"]["disabling_set_exposes"] = not bool(self.disabled_equal(s)[cid])
            if not out["checks"]["disabling_set_exposes"]:
                out.update({"status": "FALSE", "reason": "disabling the declared set does not expose A"})
                return out
            subchecks = {}
            for r in range(1, len(s)):
                for sub in itertools.combinations(sorted(s), r):
                    subchecks[",".join(sub)] = bool(self.disabled_equal(sub)[cid])
            out["checks"]["proper_subsets_do_not_expose"] = subchecks
            if not all(subchecks.values()):
                out.update({"status": "FALSE", "reason": "a proper subset already exposes A"})
                return out

        condition = relation.get("condition")
        if not isinstance(condition, str) or not condition.strip():
            out["condition"] = {"status": "ABSENT"}
        else:
            out["condition"] = self._check_condition(condition, kind, s)
            cond = out["condition"]
            if cond.get("status") == "VALID":
                witness_args = dict(next(a for c, a in self.cases if c == cid))
                try:
                    witness_value = bool(engine.eval_guard(
                        condition, self.arg_names, witness_args))
                except Exception as exc:  # noqa: BLE001
                    cond.update({"status": "INVALID",
                                 "error": f"{type(exc).__name__}: {exc}"})
                else:
                    cond["witness_value"] = witness_value
                    if not witness_value:
                        out.update({"status": "FALSE",
                                    "reason": "condition is false on the witness input"})
                        return out
        # Execution checks passed.  Complete validity additionally requires a
        # condition that is valid, true on the witness, and sound over the
        # declared finite domain.  A sound-but-incomplete condition under-claims;
        # an unsound condition over-claims and is a semantic error.
        cond = out.get("condition") or {}
        if cond.get("status") != "VALID":
            out["status"] = "INCOMPLETE"
            out["reason"] = "condition is absent or not in the allowed language"
        elif not cond.get("sound"):
            out["status"] = "FALSE"
            out["reason"] = ("condition is unsound: it accepts inputs where the "
                             "declared relation does not hold")
        elif not cond.get("exact"):
            out["status"] = "INCOMPLETE"
            out["reason"] = ("condition is sound but incomplete: it rejects inputs "
                             "where the declared relation does hold")
        else:
            out["status"] = "VERIFIED"
        return out

    def _check_condition(self, expr: str, kind: str, ops: FrozenSet[str]) -> Dict[str, Any]:
        try:
            engine.validate_guard(expr, self.arg_names)
        except Exception as exc:  # noqa: BLE001
            return {"status": "INVALID", "error": f"{type(exc).__name__}: {exc}"}
        actual = self.actual_relation_holds(kind, ops)
        predicted: Dict[str, bool] = {}
        errors = []
        for cid, args in self.cases:
            try:
                predicted[cid] = bool(engine.eval_guard(expr, self.arg_names, args))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{cid}: {type(exc).__name__}: {exc}")
        if errors:
            return {"status": "INVALID", "errors": errors[:3]}
        false_accept = [cid for cid in actual if predicted[cid] and not actual[cid]]
        false_reject = [cid for cid in actual if not predicted[cid] and actual[cid]]
        return {
            "status": "VALID",
            "exact": not false_accept and not false_reject,
            "sound": not false_accept,
            "complete": not false_reject,
            "false_accept": false_accept,
            "false_reject": false_reject,
        }

    def verify_submission(self, answer: Any) -> Dict[str, Any]:
        if not isinstance(answer, dict):
            return {"status": "FORMAT_ERROR", "reason": "submission is not a JSON object"}
        relations = answer.get("relations")
        if not isinstance(relations, list):
            return {"status": "FORMAT_ERROR", "reason": "missing relations list"}
        if len(relations) > MAX_RELATIONS:
            return {"status": "FORMAT_ERROR", "reason": f"more than {MAX_RELATIONS} relations"}
        if not relations:
            return {"status": "UNKNOWN", "reason": "no relations submitted", "relation_results": []}
        results = []
        seen: Dict[Tuple[Tuple[str, ...], Any], int] = {}
        for index, relation in enumerate(relations):
            result = self.verify_relation(relation)
            key = (tuple(result.get("operations") or ()), result.get("kind"))
            if result.get("operations") and key in seen:
                result["status"] = "DUPLICATE"
                result["duplicate_of"] = seen[key]
            elif result.get("operations"):
                seen[key] = index
            results.append(result)
        unique = [r for r in results if r["status"] != "DUPLICATE"]
        verified = sum(r["status"] == "VERIFIED" for r in unique)
        incomplete = sum(r["status"] == "INCOMPLETE" for r in unique)
        false = sum(r["status"] == "FALSE" for r in unique)
        unverified = sum(r["status"] == "UNVERIFIED" for r in unique)
        format_errors = sum(r["status"] == "FORMAT_ERROR" for r in unique)
        duplicates = len(results) - len(unique)
        if format_errors:
            status = "FORMAT_ERROR"
        elif verified == len(unique):
            status = "COMPLETE_VALID"
        elif verified > 0:
            status = "PARTIAL"
        elif false > 0:
            status = "SEMANTIC_ERROR"
        else:
            status = "UNVERIFIED"
        return {
            "status": status,
            "relation_results": results,
            "counts": {"submitted": len(unique), "verified": verified,
                       "incomplete": incomplete, "false": false,
                       "unverified": unverified, "format_error": format_errors,
                       "duplicates_ignored": duplicates},
        }

    def score_guard(self, answer: Dict[str, Any]) -> Dict[str, Any]:
        guard = answer.get("guard") or {}
        expr = guard.get("expr") if isinstance(guard, dict) else None
        if not isinstance(expr, str) or not expr.strip():
            return {"status": "ABSENT"}
        try:
            engine.validate_guard(expr, self.arg_names)
        except Exception as exc:  # noqa: BLE001
            return {"status": "INVALID", "error": f"{type(exc).__name__}: {exc}"}
        false_accept, false_reject, errors = [], [], []
        for cid, args in self.cases:
            try:
                predicted = bool(engine.eval_guard(expr, self.arg_names, args))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"{cid}: {type(exc).__name__}: {exc}")
                continue
            actual = bool(self.base_equal[cid])
            if predicted and not actual:
                false_accept.append(cid)
            elif not predicted and actual:
                false_reject.append(cid)
        return {
            "status": "INVALID" if errors else "BOUNDED",
            "exact": not errors and not false_accept and not false_reject,
            "sound": not errors and not false_accept,
            "complete": not errors and not false_reject,
            "false_accept": false_accept,
            "false_reject": false_reject,
            "errors": errors,
        }

    def test_gap_actual(self) -> Dict[str, str]:
        out: Dict[str, str] = {}
        for test in self.task["existing_tests"]:
            cid = self.legal_case(test["input"])
            if cid is None:
                out[test["name"]] = "not_covered"
                continue
            plus = test.get("results", {}).get("plus", {}).get("passed")
            minus = test.get("results", {}).get("minus", {}).get("passed")
            if not self.local_effect[cid]:
                out[test["name"]] = "unexercised"
            elif self.base_equal[cid]:
                out[test["name"]] = "masked"
            elif plus and not minus:
                out[test["name"]] = "would_be_caught"
            elif plus and minus:
                out[test["name"]] = "assertion_gap"
            else:
                out[test["name"]] = "test_broken"
        return out

    def score_test_gap(self, answer: Dict[str, Any]) -> Dict[str, Any]:
        expected = self.test_gap_actual()
        raw = answer.get("test_gap")
        if not isinstance(raw, list):
            return {"status": "ABSENT", "expected": expected}
        submitted = {}
        for item in raw:
            if isinstance(item, dict) and isinstance(item.get("test"), str):
                submitted[item["test"]] = item.get("verdict")
        rows = []
        for name, gap in expected.items():
            got = submitted.get(name)
            rows.append({"test": name, "expected": gap, "got": got,
                         "status": "uncovered" if got is None else
                                   ("correct" if got == gap else "wrong")})
        return {
            "status": "BOUNDED",
            "rows": rows,
            "exact": all(r["status"] == "correct" for r in rows),
            "covered": sum(r["status"] != "uncovered" for r in rows),
            "total": len(rows),
        }

    def score_counterexample(self, answer: Dict[str, Any]) -> Dict[str, Any]:
        ce = answer.get("counterexample")
        if ce is None:
            return {"status": "ABSENT"}
        value = ce.get("input") if isinstance(ce, dict) else ce
        cid = self.legal_case(value)
        if cid is None:
            return {"status": "INVALID", "reason": "counterexample input is not a legal case"}
        if not self.local_effect[cid]:
            return {"status": "INVALID", "reason": "A has no local effect on this input"}
        exposed = not self.base_equal[cid]
        return {"status": "VALID" if exposed else "INVALID",
                "input": value, "case_id": cid,
                "observation_plus": self.plus_rows[cid]["observation"],
                "observation_minus": self.minus_rows[cid]["observation"],
                "reason": "deletion is observable" if exposed else "deletion remains masked"}


# ---------------------------------------------------------------------------
# Full MACE interface probe
# ---------------------------------------------------------------------------

def _strip_angle_brackets(value: Any) -> Any:
    """Generic notation normalisation, not a reasoning change.

    The local 1.5B model wraps every MACE expression in ``<...>``.  Stripping
    the wrapper is the same kind of adaptation as accepting a fenced JSON
    block; it does not add, remove, or select any operation.
    """
    if isinstance(value, dict):
        return {k: _strip_angle_brackets(v) for k, v in value.items()}
    if isinstance(value, list):
        return [_strip_angle_brackets(v) for v in value]
    if isinstance(value, str):
        text = value.strip()
        if len(text) >= 2 and text.startswith("<") and text.endswith(">"):
            return text[1:-1].strip()
    return value


class NotationNormalizingClient:
    """Transport adapter that removes a model's ``<expr>`` notation.

    This is used only in a diagnostic run.  Raw responses are preserved on the
    underlying client.  It does not use any hidden label or oracle answer.
    """
    def __init__(self, inner: Any):
        self.inner = inner
        self.provider = f"{inner.provider}+notation-normalizer"
        self.model = inner.model
        self.calls = inner.calls
        self.rewrites = 0

    def chat(self, messages, *, purpose="contract", json_mode=True):
        response = self.inner.chat(messages, purpose=purpose, json_mode=json_mode)
        try:
            obj = extract_json(response.content)
        except Exception:  # noqa: BLE001 - leave unparsable output untouched
            return response
        normalized = _strip_angle_brackets(obj)
        content = json.dumps(normalized, ensure_ascii=False)
        if content != response.content:
            self.rewrites += 1
        return Response(content=content, stats=response.stats,
                        request_messages=response.request_messages)

    def model_info(self) -> Dict[str, Any]:
        info = self.inner.model_info()
        info["notation_normalizer"] = True
        info["rewrites"] = self.rewrites
        return info


class StaticClient:
    """A schema probe, not a model run.

    It returns a deliberately neutral, tautological contract so the pipeline can
    reach verification without encoding any hidden correct relation.  The point
    is to inspect what the *interface* can emit.
    """
    provider = "static-schema-probe"
    model = "static-schema-probe"

    def __init__(self, payload: Dict[str, Any]):
        self.payload = payload
        self.calls: List[Dict[str, Any]] = []

    def chat(self, messages, *, purpose="contract", json_mode=True):
        content = json.dumps(self.payload, ensure_ascii=False)
        stats = {"prompt_tokens": 0, "completion_tokens": 0, "wall_seconds": 0.0}
        self.calls.append({"purpose": purpose, "stats": stats})
        return Response(content=content, stats=stats, request_messages=messages)


def neutral_contract(task: Dict[str, Any]) -> Dict[str, Any]:
    source = task["program"]["source"]
    target = task["program"]["target_A"]["line"]
    tree = ast.parse(source)
    returns = [n.lineno for n in ast.walk(tree) if isinstance(n, ast.Return)]
    observer_line = min(returns) if returns else target
    return {
        "target_effects": [{"id": "T1", "expr": "v_post == v_post",
                            "source_lines": [target]}],
        "upstream": [{"id": "U1", "expr": "True", "condition": "True",
                      "role": "supporting", "source_lines": [1]}],
        "observers": [{"id": "O0", "channel": 0, "expr": "v",
                       "condition": "True", "source_lines": [observer_line]}],
        "mask_guard": {"expr": "True", "source_lines": [target]},
    }


def adapt_mace_result(result: Dict[str, Any]) -> Dict[str, Any]:
    """Try to express the existing MACE output in the open schema.

    This is an interface adapter, not a model-reasoning change.  It does not
    invent operation sets.  If the required fields are absent, the result is
    UNSUPPORTED.
    """
    bundle = result.get("final_bundle") or {}
    report = result.get("final_report") or {}
    relations = report.get("relations") or []
    attribution = report.get("attribution") or {}
    present_fields = {
        "bundle_keys": sorted(bundle.keys()),
        "relation_kinds": sorted({r.get("kind") for r in relations if r.get("kind")}),
        "relation_has_operations": any("operations" in r for r in relations),
        "relation_has_input": any("input" in r for r in relations),
        "attribution_keys": sorted(attribution.keys()),
        "contrast_is_argument_level": bool((attribution.get("contrast") or {}).get("arguments")),
    }
    missing = []
    if not present_fields["relation_has_operations"]:
        missing.append("relations[].operations (source-line operation sets)")
    if not present_fields["relation_has_input"]:
        missing.append("relations[].input (input-specific evidence)")
    if not bundle and not report:
        status = "NO_RESULT"
    elif missing:
        status = "UNSUPPORTED"
    else:
        status = "CANDIDATE"
    return {
        "status": status,
        "missing": missing,
        "present_fields": present_fields,
        "reason": ("No bundle/report was produced, so this run cannot be scored."
                   if status == "NO_RESULT" else
                   "The existing MACE contract emits target_effect/upstream/observer/"
                   "mask_guard relations and an argument-level contrast, not downstream "
                   "operation sets.  Guard or argument contrast cannot substitute for the "
                   "required operation attribution."),
    }


def run_full_mace(task: Dict[str, Any], client: Any, rounds: int,
                  tag: str = "full_mace") -> Dict[str, Any]:
    fixture = make_fixture(task)
    out_dir = OUT / "runs" / task["task_id"] / tag
    start = time.perf_counter()
    try:
        result = run_mode(fixture, client, "mace", rounds=rounds, seed=42,
                          out_dir=out_dir, timeout=300.0, guard_source="qwen")
        error = None
    except Exception as exc:  # noqa: BLE001
        result = {"status": "ERROR", "final_bundle": None, "final_report": None,
                  "final_guard": None, "usage": {}, "exchanges": []}
        error = f"{type(exc).__name__}: {exc}"
    return {
        "method": "full_mace",
        "tag": tag,
        "task_id": task["task_id"],
        "run_status": result.get("status"),
        "status": result.get("status"),
        "error": error,
        "wall_seconds": round(time.perf_counter() - start, 3),
        "usage": result.get("usage"),
        "final_guard": result.get("final_guard"),
        "final_bundle_keys": sorted((result.get("final_bundle") or {}).keys()),
        "report_keys": sorted((result.get("final_report") or {}).keys()),
        "adapter": adapt_mace_result(result),
        "interface_status": adapt_mace_result(result)["status"],
        "raw_exchanges": result.get("exchanges"),
    }


def schema_probe(task: Dict[str, Any]) -> Dict[str, Any]:
    fixture = make_fixture(task)
    out_dir = OUT / "runs" / task["task_id"] / "schema_probe"
    payload = neutral_contract(task)
    start = time.perf_counter()
    try:
        result = run_mode(fixture, StaticClient(payload), "mace", rounds=1,
                          seed=42, out_dir=out_dir, timeout=60.0, guard_source="qwen")
        error = None
    except Exception as exc:  # noqa: BLE001
        result = {"status": "ERROR", "final_bundle": None, "final_report": None}
        error = f"{type(exc).__name__}: {exc}"
    return {
        "kind": "schema_probe_not_a_model_run",
        "task_id": task["task_id"],
        "status": result.get("status"),
        "error": error,
        "wall_seconds": round(time.perf_counter() - start, 3),
        "final_bundle_keys": sorted((result.get("final_bundle") or {}).keys()),
        "report_keys": sorted((result.get("final_report") or {}).keys()),
        "adapter": adapt_mace_result(result),
        "interface_status": adapt_mace_result(result)["status"],
        "note": ("The neutral contract uses only tautologies. It is not a correct answer "
                 "and is not scored as a model submission."),
    }


def run_direct_open(task: Dict[str, Any], client: Any, max_new_tokens: int) -> Dict[str, Any]:
    prompt = open_prompt(task)
    banned = ["# OP_", "op_lines", "attribution", "absorber", "oracle",
              "sk-", "DASHSCOPE", "Bearer", "coexisting_unmasking_sets",
              "individually_masking_ops"]
    leaked = [b for b in banned if b.lower() in prompt.lower()]
    if leaked:
        raise RuntimeError(f"public prompt leaked private markers: {leaked}")
    messages = [
        {"role": "system", "content": "You are a precise program-semantics analyst. "
                                      "Return exactly one JSON object."},
        {"role": "user", "content": prompt},
    ]
    start = time.perf_counter()
    started = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    response = client.chat(messages, purpose=f"open/{task['task_id']}")
    wall = round(time.perf_counter() - start, 3)
    finished = datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    raw = {
        "schema_version": "mace-open-discovery-raw-v1",
        "task_id": task["task_id"],
        "method": "direct_qwen",
        "provider": client.provider,
        "model_info": client.model_info(),
        "generation": {"temperature": 0.0, "seed": 42,
                       "max_new_tokens": max_new_tokens, "do_sample": False},
        "prompt": prompt,
        "prompt_sha256": hashlib.sha256(prompt.encode("utf-8")).hexdigest(),
        "started_at_utc": started,
        "finished_at_utc": finished,
        "wall_seconds": wall,
        "stats": response.stats,
        "raw_response": response.content,
    }
    raw_path = OUT / "direct_qwen" / f"{task['task_id']}_raw.json"
    write_json(raw_path, raw)
    try:
        answer = extract_json(response.content)
        parse_error = None
        parse_status = "ANSWERED"
    except Exception as exc:  # noqa: BLE001
        answer = None
        parse_error = f"{type(exc).__name__}: {exc}"
        parse_status = "FORMAT_ERROR"
    verifier = Verifier(task, load_attribution()[task["task_id"]])
    if answer is None:
        verified = {"status": parse_status, "reason": parse_error}
        guard = {"status": "ABSENT"}
        test_gap = {"status": "ABSENT"}
        counterexample = {"status": "ABSENT"}
    else:
        verified = verifier.verify_submission(answer)
        guard = verifier.score_guard(answer)
        test_gap = verifier.score_test_gap(answer)
        counterexample = verifier.score_counterexample(answer)
    scored = {
        **{k: v for k, v in raw.items() if k not in ("prompt", "raw_response")},
        "parse_status": parse_status,
        "parse_error": parse_error,
        "answer": answer,
        "verification": verified,
        "guard": guard,
        "test_gap": test_gap,
        "counterexample": counterexample,
        "verification_executions": verifier.executions,
        "raw_path": str(raw_path.relative_to(ROOT)),
    }
    scored_path = OUT / "direct_qwen" / f"{task['task_id']}_scored.json"
    write_json(scored_path, scored)
    return scored


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def load_attribution() -> Dict[str, Any]:
    data = json.loads(ATTRIBUTION.read_text(encoding="utf-8"))
    return data["controlled"]


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                    encoding="utf-8", newline="\n")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--model-path", required=True)
    parser.add_argument("--rounds", type=int, default=2)
    parser.add_argument("--max-new-tokens", type=int, default=1536)
    parser.add_argument("--tasks", nargs="+", default=list(TASK_IDS),
                        choices=list(TASK_IDS))
    parser.add_argument("--skip-full", action="store_true")
    parser.add_argument("--skip-direct", action="store_true")
    args = parser.parse_args()

    OUT.mkdir(parents=True, exist_ok=True)
    tasks = load_tasks()
    attribution = load_attribution()

    from scripts.local_qwen_client import LocalQwenClient  # noqa: PLC0415
    client = LocalQwenClient(args.model_path, max_new_tokens=args.max_new_tokens,
                             temperature=0.0, seed=42)

    rows = []
    for task_id in args.tasks:
        task = tasks[task_id]
        direct = None
        if not args.skip_direct:
            print(f"== {task_id} direct_qwen", flush=True)
            direct = run_direct_open(task, client, args.max_new_tokens)
            print(json.dumps({k: direct.get(k) for k in
                              ("task_id", "parse_status", "verification", "guard")},
                             ensure_ascii=False)[:1200], flush=True)
        full = None
        if not args.skip_full:
            print(f"== {task_id} full_mace raw", flush=True)
            raw_full = run_full_mace(task, client, args.rounds, tag="full_mace")
            print(json.dumps({k: raw_full.get(k) for k in
                              ("task_id", "status", "adapter")},
                             ensure_ascii=False)[:1200], flush=True)
            print(f"== {task_id} full_mace normalized", flush=True)
            norm_full = run_full_mace(task, NotationNormalizingClient(client),
                                      args.rounds, tag="full_mace_norm")
            print(json.dumps({k: norm_full.get(k) for k in
                              ("task_id", "status", "adapter")},
                             ensure_ascii=False)[:1200], flush=True)
            full = {"raw": raw_full, "normalized": norm_full}
        print(f"== {task_id} schema_probe", flush=True)
        probe = schema_probe(task)
        rows.append({"task_id": task_id, "direct_qwen": direct,
                     "full_mace": full, "schema_probe": probe})

    payload = {
        "schema_version": "mace-open-interface-check-v1",
        "generated_at_utc": datetime.now(timezone.utc).replace(microsecond=0).isoformat(),
        "tasks": rows,
        "model": client.model_info(),
        "submission_schema": str(SCHEMA.relative_to(ROOT)),
        "note": ("ctrl_01/02/03 are old controlled Pilot tasks, not a new independent "
                 "test set.  This is an interface feasibility check, not a benchmark score. "
                 "No new real task was created in this phase."),
    }
    write_json(OUT / "ctrl_interface.json", payload)
    print("WROTE", OUT / "ctrl_interface.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
