"""Build and freeze the first small blind task (MACE benchmark protocol v1).

The task is a real function (``requests.utils.parse_header_links`` from
requests 2.31.0) with one *explicitly hypothetical* deletion.  This script

* verifies the embedded upstream source against the installed package,
* derives every label by executing P+ / P- and the candidate-operation
  interventions (never from a hand-written formula),
* writes a public task statement and a private oracle separately,
* writes a content-addressed FREEZE manifest.

Run ``python scripts/blind_build.py`` to (re)build, and
``python scripts/blind_build.py --check`` to verify that the frozen files are
still byte-identical to a fresh derivation.

No network access is required.  The upstream files are embedded below and
identified by SHA-256 in the provenance record.
"""
from __future__ import annotations

import argparse
import ast
import hashlib
import itertools
import json
import random
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from benchmark_pilot import engine  # noqa: E402

OUT = ROOT / "benchmark_blind_v1"
PUBLIC_DIR = OUT / "public"
PRIVATE_DIR = OUT / "private"
LOG_DIR = OUT / "logs"
TASK_ID = "blind_01_parse_header_links"

# -- exact upstream source --------------------------------------------------
# psf/requests v2.31.0, requests/utils.py, lines 912-946.
# SHA-256 of this function text (with a trailing newline): c9193a0d...
FUNCTION_SOURCE = r'''def parse_header_links(value):
    """Return a list of parsed link headers proxies.

    i.e. Link: <http:/.../front.jpeg>; rel=front; type="image/jpeg",<http://.../back.jpeg>; rel=back;type="image/jpeg"

    :rtype: list
    """

    links = []

    replace_chars = " '\""

    value = value.strip(replace_chars)
    if not value:
        return links

    for val in re.split(", *<", value):
        try:
            url, params = val.split(";", 1)
        except ValueError:
            url, params = val, ""

        link = {"url": url.strip("<> '\"")}

        for param in params.split(";"):
            try:
                key, value = param.split("=")
            except ValueError:
                break

            link[key.strip(replace_chars)] = value.strip(replace_chars)

        links.append(link)

    return links'''

# psf/requests v2.31.0, tests/test_utils.py, lines 644-664.
# SHA-256 of this block (with a trailing newline): bc1dc592...
UPSTREAM_TEST_BLOCK = r'''@pytest.mark.parametrize(
    "value, expected",
    (
        (
            '<http:/.../front.jpeg>; rel=front; type="image/jpeg"',
            [{"url": "http:/.../front.jpeg", "rel": "front", "type": "image/jpeg"}],
        ),
        ("<http:/.../front.jpeg>", [{"url": "http:/.../front.jpeg"}]),
        ("<http:/.../front.jpeg>;", [{"url": "http:/.../front.jpeg"}]),
        (
            '<http:/.../front.jpeg>; type="image/jpeg",<http://.../back.jpeg>;',
            [
                {"url": "http:/.../front.jpeg", "type": "image/jpeg"},
                {"url": "http://.../back.jpeg"},
            ],
        ),
        ("", []),
    ),
)
def test_parse_header_links(value, expected):
    assert parse_header_links(value) == expected
'''

UPSTREAM = {
    "project": "psf/requests",
    "version": "2.31.0",
    "tag": "v2.31.0",
    "tag_object_sha": "0106aced5faa299e6ede89d1230bd6784f2c3660",
    "commit_sha": "147c8511ddbfa5e8f71bbf5c18ede0c4ceb3bba4",
    "license": "Apache-2.0",
    "license_file_sha256": "09e8a9bcec8067104652c168685ab0931e7868f9c8284b66f5ae6edae5f1130b",
    "source_path": "requests/utils.py",
    "source_file_sha256": "eacc765f7708540f018163a0f28771172fbf95b5831444d4f072387d4e119aac",
    "function_line_range": [912, 946],
    "function_sha256": "c9193a0df87262a9a6041998cfa34600d32e8152f508e79b862a31ab5482a720",
    "test_path": "tests/test_utils.py",
    "test_file_sha256": "5a98862b9e19412592ff497fd9df5920e6c3ab5852f581c21280bbb6af773fc2",
    "test_line_range": [644, 664],
    "test_block_sha256": "bc1dc592ba999659c69065eb51f9a6bf435edf3c98c76180f7e80dd4428791e9",
    "source_url": "https://github.com/psf/requests/blob/v2.31.0/requests/utils.py#L912-L946",
    "test_url": "https://github.com/psf/requests/blob/v2.31.0/tests/test_utils.py#L644-L664",
    "deletion_is_hypothetical": True,
    "deletion_note": (
        "A is present in upstream requests 2.31.0.  The deletion analysed here is an "
        "explicitly constructed hypothetical, not a historical commit and not a claim "
        "that upstream ever removed this line."
    ),
}

TARGET_TEXT = "    value = value.strip(replace_chars)"
TARGET_MARKED = TARGET_TEXT + "  # TARGET_A"
GUARD_EXPR = "not (nonempty and all_special)"
GUARD_FEATURES = {
    "nonempty": "len(value) > 0",
    "all_special": "all(ch in \" '\"\" for ch in value)",
}
EVAL_CASES = [
    ("m1", " \"<http://a>\" ", "masked_local_effect"),
    ("m2", " <http://a>; rel=x", "masked_local_effect"),
    ("m3", "<http://a>; rel=x ", "masked_local_effect"),
    ("m4", "<http://a>;rel=\"x\"", "masked_local_effect"),
    ("m5", " \"<http://a>; rel=x\" ", "masked_local_effect"),
    ("m6", " <http://a> ; rel = x ", "masked_local_effect"),
    ("e1", " ", "exposed_local_effect"),
    ("e2", "\"\"", "exposed_local_effect"),
    ("e3", "''", "exposed_local_effect"),
    ("e4", " \" ", "exposed_local_effect"),
    ("n1", "", "no_local_effect"),
    ("n2", "<http://a>", "no_local_effect"),
    ("n3", "http://a", "no_local_effect"),
    ("n4", "<http://a>; rel=x, <http://b>", "no_local_effect"),
]

# Public probes are labelled in the private oracle, but only their IDs and
# inputs are public.  They give every method the same small set on which to
# report masking attribution; the hidden evaluation set remains disjoint.
PUBLIC_PROBES = [
    ("p1", " \"<http://p>\" ", "masked_local_effect", [["op_1"]], "independent"),
    ("p2", "<http://p>; rel=y ", "masked_local_effect", [["op_3"]], "independent"),
    ("p3", " \"<http://p>; rel=y\" ", "masked_local_effect",
     [["op_1", "op_3"]], "cooperative"),
    ("p4", "  ", "exposed_local_effect", [], "none"),
]


def sha256_text(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def dump_json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, indent=2) + "\n"


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(dump_json(value), encoding="utf-8", newline="\n")


def build_program() -> Tuple[str, str]:
    program = "import re\n\n\n" + FUNCTION_SOURCE.rstrip("\n") + "\n"
    lines = program.splitlines()
    hits = [i for i, line in enumerate(lines) if line == TARGET_TEXT]
    if len(hits) != 1:
        raise SystemExit(f"expected one target line in program, found {len(hits)}")
    lines[hits[0]] = TARGET_MARKED
    program = "\n".join(lines) + "\n"
    if engine.target_line(program) != hits[0] + 1:
        raise SystemExit("target marker line mismatch")
    return program, engine.replace_target_with_pass(program)


def operation_table(program: str) -> Dict[str, Dict[str, Any]]:
    target = engine.target_line(program)
    found: Dict[str, Dict[str, Any]] = {}
    for node in ast.walk(ast.parse(program)):
        if not (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "strip"
                and isinstance(node.func.value, ast.Name)
                and node.lineno != target):
            continue
        receiver = node.func.value.id
        op_id = {"url": "op_1", "key": "op_2", "value": "op_3"}.get(receiver)
        if op_id is None:
            raise SystemExit(f"unexpected strip receiver {receiver!r}")
        found[op_id] = {
            "id": op_id,
            "source_position": {
                "line": node.lineno,
                "col": node.col_offset,
                "end_col": node.end_col_offset,
            },
            "receiver": receiver,
            "expression": ast.get_source_segment(program, node),
            "line_text": program.splitlines()[node.lineno - 1],
            "disable_by": (
                "replace the expression at the source position with its receiver "
                f"``{receiver}``; no other edit"
            ),
        }
    if sorted(found) != ["op_1", "op_2", "op_3"]:
        raise SystemExit(f"expected op_1..op_3, got {sorted(found)}")
    return found


def disable_ops(source: str, ops: Dict[str, Dict[str, Any]],
                disabled: Iterable[str]) -> str:
    """Textual identity replacement, preserving every line number."""
    lines = source.splitlines()
    edits: Dict[int, List[Tuple[int, int, str]]] = {}
    for op_id in disabled:
        info = ops[op_id]
        pos = info["source_position"]
        edits.setdefault(pos["line"], []).append(
            (pos["col"], pos["end_col"], info["receiver"]))
    for line_no, spans in edits.items():
        text = lines[line_no - 1]
        for col, end_col, receiver in sorted(spans, reverse=True):
            text = text[:col] + receiver + text[end_col:]
        lines[line_no - 1] = text
    return "\n".join(lines) + "\n"


def extract_test_cases() -> List[Tuple[str, Any]]:
    tree = ast.parse(UPSTREAM_TEST_BLOCK)
    fn = next(n for n in tree.body if isinstance(n, ast.FunctionDef))
    decorator = fn.decorator_list[0]
    if not (isinstance(decorator, ast.Call)
            and isinstance(decorator.func, ast.Attribute)
            and decorator.func.attr == "parametrize"):
        raise SystemExit("unexpected upstream test decorator")
    values = ast.literal_eval(decorator.args[1])
    return [(value, expected) for value, expected in values]


def adapted_test_source(cases: Sequence[Tuple[str, Any]]) -> str:
    body = ",\n".join(
        f"        ({value!r}, {expected!r})" for value, expected in cases)
    return (
        "def test_parse_header_links():\n"
        "    cases = (\n"
        f"{body},\n"
        "    )\n"
        "    for value, expected in cases:\n"
        "        assert parse_header_links(value) == expected\n"
    )


def feature_values(value: str) -> Dict[str, bool]:
    return {
        "nonempty": len(value) > 0,
        "all_special": all(ch in " '\"" for ch in value),
    }


def compiled_guard():
    tree = engine.validate_guard(GUARD_EXPR, ["nonempty", "all_special"])
    code = compile(tree, "<blind-guard>", "eval")
    return lambda value: bool(eval(  # noqa: S307 - validated AST
        code, {"__builtins__": {}}, feature_values(value)))


def run_value(program: str, value: str, ops: Dict[str, Dict[str, Any]],
              disabled: Iterable[str], target: int) -> Dict[str, Any]:
    source = disable_ops(program, ops, disabled)
    compiled = engine.compile_source(source, capture_line=target)
    return compiled.call("parse_header_links", {"value": value})


def intervention_key(enabled: Iterable[str]) -> str:
    enabled = sorted(enabled)
    return "enabled_" + ("+".join(enabled) if enabled else "none")


def classify(value: str, plus: str, minus: str,
             ops: Dict[str, Dict[str, Any]], target: int) -> Dict[str, Any]:
    plus0 = run_value(plus, value, ops, [], target)
    minus0 = run_value(minus, value, ops, [], target)
    local_effect = plus0.get("snap") != minus0.get("snap")
    equal = plus0["observation"] == minus0["observation"]
    if not local_effect and not equal:
        raise SystemExit(
            f"inconsistent case {value!r}: no local effect but outputs differ")

    equality: Dict[str, bool] = {}
    for size in range(len(ops) + 1):
        for combo in itertools.combinations(sorted(ops), size):
            enabled = frozenset(combo)
            disabled = set(ops) - enabled
            p = run_value(plus, value, ops, disabled, target)
            m = run_value(minus, value, ops, disabled, target)
            equality[intervention_key(enabled)] = (
                p["observation"] == m["observation"])

    masking_sets: List[List[str]] = []
    masking_type = "not_applicable"
    if local_effect:
        if not equal:
            masking_type = "none"
        else:
            all_sets = {
                frozenset(key.replace("enabled_", "").split("+"))
                for key, eq in equality.items()
                if eq and key != "enabled_none"
            }
            minimal = engine.minimal_sets(all_sets)
            masking_sets = [sorted(s) for s in minimal]
            if equality.get("enabled_none"):
                raise SystemExit(
                    f"case {value!r}: all candidate ops disabled still masks; "
                    "the operation model does not explain this case")
            sizes = sorted({len(s) for s in masking_sets})
            if not masking_sets:
                masking_type = "unexplained"
            elif sizes == [1]:
                masking_type = "independent"
            elif sizes and sizes[0] >= 2:
                masking_type = "cooperative"
            else:
                masking_type = "mixed"

    if local_effect and equal:
        bucket = "masked_local_effect"
    elif local_effect and not equal:
        bucket = "exposed_local_effect"
    else:
        bucket = "no_local_effect"

    return {
        "case_id": "",
        "bucket": bucket,
        "args": {"value": value},
        "plus": {
            "observation": plus0["observation"],
            "snapshot_after_A": plus0.get("snap"),
        },
        "minus": {
            "observation": minus0["observation"],
            "snapshot_after_A": minus0.get("snap"),
        },
        "observations_equal": equal,
        "a_has_local_effect": local_effect,
        "all_operations_enabled": equal,
        "intervention_equality": equality,
        "minimal_masking_sets": masking_sets,
        "masking_type": masking_type,
    }


def test_gap(plus_passed: bool, minus_passed: bool, equal: bool,
             local_effect: bool) -> str:
    if not plus_passed:
        return "test_broken"
    if not minus_passed:
        return "would_be_caught" if not equal else "unexpected"
    if not local_effect:
        return "unexercised"
    if equal:
        return "masked"
    return "assertion_gap"


def exhaustive_check(plus: str, minus: str, predict) -> Dict[str, Any]:
    alphabet = " '\"<>;=,abc"
    start = time.perf_counter()
    counts = {"strings": 0, "masked": 0, "exposed": 0,
              "mismatch": 0}
    examples: List[Dict[str, Any]] = []
    plus_c = engine.compile_source(plus)
    minus_c = engine.compile_source(minus)
    for length in range(6):
        for chars in itertools.product(alphabet, repeat=length):
            value = "".join(chars)
            p = plus_c.call("parse_header_links", {"value": value})
            m = minus_c.call("parse_header_links", {"value": value})
            actual = p["observation"] == m["observation"]
            predicted = predict(value)
            counts["strings"] += 1
            counts["masked" if actual else "exposed"] += 1
            if actual != predicted:
                counts["mismatch"] += 1
                if len(examples) < 10:
                    examples.append({"value": value, "actual_masked": actual,
                                     "predicted_masked": predicted})
    counts["mismatch_examples"] = examples
    counts["wall_seconds"] = round(time.perf_counter() - start, 3)
    counts["alphabet"] = alphabet
    counts["max_length"] = 5
    counts["evidence_level"] = "BOUNDED"
    return counts


def random_check(plus: str, minus: str, predict) -> Dict[str, Any]:
    rng = random.Random(0)
    alphabet = " '\"<>;=,abcXYZ0123/-_"
    start = time.perf_counter()
    counts = {"strings": 0, "masked": 0, "exposed": 0, "mismatch": 0}
    examples: List[Dict[str, Any]] = []
    plus_c = engine.compile_source(plus)
    minus_c = engine.compile_source(minus)
    for _ in range(20000):
        length = rng.randrange(0, 31)
        value = "".join(rng.choice(alphabet) for _ in range(length))
        p = plus_c.call("parse_header_links", {"value": value})
        m = minus_c.call("parse_header_links", {"value": value})
        actual = p["observation"] == m["observation"]
        predicted = predict(value)
        counts["strings"] += 1
        counts["masked" if actual else "exposed"] += 1
        if actual != predicted:
            counts["mismatch"] += 1
            if len(examples) < 10:
                examples.append({"value": value, "actual_masked": actual,
                                 "predicted_masked": predicted})
    counts["mismatch_examples"] = examples
    counts["wall_seconds"] = round(time.perf_counter() - start, 3)
    counts["seed"] = 0
    counts["alphabet"] = alphabet
    counts["length_range"] = [0, 30]
    counts["evidence_level"] = "BOUNDED"
    return counts


def installed_check() -> Dict[str, Any]:
    try:
        import inspect
        import requests
        source = inspect.getsource(requests.utils.parse_header_links)
    except Exception as exc:  # noqa: BLE001
        return {"available": False, "reason": f"{type(exc).__name__}: {exc}"}
    return {
        "available": True,
        "version": requests.__version__,
        "path": requests.__file__,
        "function_sha256": sha256_text(source.rstrip("\n") + "\n"),
        "matches_embedded": sha256_text(FUNCTION_SOURCE.rstrip("\n") + "\n")
        == sha256_text(source.rstrip("\n") + "\n"),
    }


def build() -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    plus, minus = build_program()
    target = engine.target_line(plus)
    ops = operation_table(plus)
    predict = compiled_guard()

    public_spec_hash = sha256_text(FUNCTION_SOURCE.rstrip("\n") + "\n")
    if public_spec_hash != UPSTREAM["function_sha256"]:
        raise SystemExit("embedded function hash does not match provenance")

    cases = extract_test_cases()
    adapted = adapted_test_source(cases)
    test_source = [{"name": "test_parse_header_links", "source": adapted}]
    plus_tests = engine.run_tests(plus, test_source)
    minus_tests = engine.run_tests(minus, test_source)

    test_rows = []
    for index, (value, expected) in enumerate(cases, 1):
        p = run_value(plus, value, ops, [], target)
        m = run_value(minus, value, ops, [], target)
        equal = p["observation"] == m["observation"]
        local = p.get("snap") != m.get("snap")
        test_rows.append({
            "case_id": f"t{index}",
            "value": value,
            "expected": expected,
            "plus": {"passed": plus_tests["test_parse_header_links"]["passed"],
                     "observation": p["observation"]},
            "minus": {"passed": minus_tests["test_parse_header_links"]["passed"],
                      "observation": m["observation"]},
            "observations_equal": equal,
            "a_has_local_effect": local,
            "gap": test_gap(
                plus_tests["test_parse_header_links"]["passed"],
                minus_tests["test_parse_header_links"]["passed"],
                equal, local),
        })

    eval_rows = []
    for case_id, value, expected_bucket in EVAL_CASES:
        row = classify(value, plus, minus, ops, target)
        row["case_id"] = case_id
        if row["bucket"] != expected_bucket:
            raise SystemExit(
                f"{case_id}: expected bucket {expected_bucket}, got {row['bucket']}")
        row["guard_predicted_masked"] = predict(value)
        row["guard_matches"] = row["guard_predicted_masked"] == row["observations_equal"]
        eval_rows.append(row)

    probe_rows = []
    for probe_id, value, expected_bucket, expected_sets, expected_type in PUBLIC_PROBES:
        row = classify(value, plus, minus, ops, target)
        row["case_id"] = probe_id
        if row["bucket"] != expected_bucket:
            raise SystemExit(
                f"{probe_id}: expected bucket {expected_bucket}, got {row['bucket']}")
        if [sorted(s) for s in row["minimal_masking_sets"]] != [
                sorted(s) for s in expected_sets]:
            raise SystemExit(
                f"{probe_id}: expected sets {expected_sets}, "
                f"got {row['minimal_masking_sets']}")
        if row["masking_type"] != expected_type:
            raise SystemExit(
                f"{probe_id}: expected type {expected_type}, "
                f"got {row['masking_type']}")
        probe_rows.append(row)

    guard_rows = []
    for row in eval_rows:
        actual = row["observations_equal"]
        predicted = predict(row["args"]["value"])
        if predicted != actual:
            guard_rows.append(row["case_id"])
    guard_summary = {
        "expression": GUARD_EXPR,
        "features": GUARD_FEATURES,
        "status": "BOUNDED",
        "eval_domain": {
            "n_cases": len(eval_rows),
            "false_accept": [r["case_id"] for r in eval_rows
                             if r["guard_predicted_masked"]
                             and not r["observations_equal"]],
            "false_reject": [r["case_id"] for r in eval_rows
                             if not r["guard_predicted_masked"]
                             and r["observations_equal"]],
            "sound": not any(r["guard_predicted_masked"]
                             and not r["observations_equal"] for r in eval_rows),
            "complete": not any(not r["guard_predicted_masked"]
                                and r["observations_equal"] for r in eval_rows),
        },
        "not_proven": (
            "The expression is checked by execution on a frozen finite domain. "
            "This is BOUNDED evidence, never a formal proof over all strings."
        ),
    }
    guard_summary["eval_domain"]["exact"] = (
        guard_summary["eval_domain"]["sound"]
        and guard_summary["eval_domain"]["complete"]
    )

    exhaustive = exhaustive_check(plus, minus, predict)
    random_sample = random_check(plus, minus, predict)
    if exhaustive["mismatch"] or random_sample["mismatch"]:
        raise SystemExit("guard mismatch in finite checks; refusing to freeze")
    timings = {
        "exhaustive_wall_seconds": exhaustive.pop("wall_seconds"),
        "random_sample_wall_seconds": random_sample.pop("wall_seconds"),
    }

    counts = {
        "eval_total": len(eval_rows),
        "eval_masked_total": sum(r["observations_equal"] for r in eval_rows),
        "eval_exposed_total": sum(not r["observations_equal"] for r in eval_rows),
        "masked_local_effect": sum(
            r["bucket"] == "masked_local_effect" for r in eval_rows),
        "exposed_local_effect": sum(
            r["bucket"] == "exposed_local_effect" for r in eval_rows),
        "no_local_effect": sum(
            r["bucket"] == "no_local_effect" for r in eval_rows),
        "masking_sets": {
            key: sum(key in [",".join(s) for s in r["minimal_masking_sets"]]
                     for r in eval_rows)
            for key in ["op_1", "op_2", "op_3", "op_1,op_3"]
        },
        "public_probes_total": len(probe_rows),
        "public_probe_masking_types": {
            kind: sum(r["masking_type"] == kind for r in probe_rows)
            for kind in ["independent", "cooperative", "none",
                         "not_applicable", "mixed", "unexplained"]
        },
        "tests_total": len(test_rows),
        "tests_pass_on_both": sum(
            r["plus"]["passed"] and r["minus"]["passed"] for r in test_rows),
        "test_gaps": {
            gap: sum(r["gap"] == gap for r in test_rows)
            for gap in ["unexercised", "masked", "would_be_caught",
                        "assertion_gap", "test_broken"]
        },
    }

    public = {
        "schema_version": "mace-benchmark-blind-v1",
        "task_id": TASK_ID,
        "kind": "real_source_hypothetical_deletion",
        "status": "frozen",
        "provenance": UPSTREAM,
        "program": {
            "language": "python",
            "python_version": "3.11.7",
            "entry": "parse_header_links",
            "source": plus,
            "source_sha256": sha256_text(plus),
            "target_A": {
                "line": engine.target_line(plus),
                "text": TARGET_MARKED,
                "kind": "assignment",
                "note": "The '# TARGET_A' marker is the only edit to this line.",
            },
        },
        "deletion": {
            "kind": "replace_line_with_pass",
            "rule": (
                "Replace the entire target line with ``pass`` at the same "
                "indentation.  No other edit."
            ),
            "p_minus_source": minus,
            "p_minus_source_sha256": sha256_text(minus),
        },
        "candidate_operations": [
            {k: v for k, v in ops[op_id].items() if k != "receiver"}
            for op_id in ["op_1", "op_2", "op_3"]
        ],
        "candidate_operation_note": (
            "These are all non-A string-normalization expressions in the "
            "function.  Each is an independent, neutral candidate.  Other "
            "lines are fixed infrastructure.  The private labels state which "
            "combinations actually absorb the deletion on the public probes "
            "and on the hidden inputs."
        ),
        "public_probes": {
            "note": (
                "Report masking attribution on these probes.  Their true "
                "labels are private.  The hidden evaluation set is disjoint "
                "from these probes."
            ),
            "probes": [
                {"probe_id": probe_id, "value": value}
                for probe_id, value, _, _, _ in PUBLIC_PROBES
            ],
        },
        "input_domain": {
            "argument": "value",
            "legal_rule": (
                "value must be a Python str (any Unicode, including the empty "
                "string).  Non-str values are outside the legal input domain; "
                "the function raises AttributeError on them."
            ),
            "observable_behavior": (
                "The return value.  A Python exception is also an observation. "
                "Equality is type-aware: bool and int are distinct, and dict "
                "order is ignored."
            ),
            "evaluation_domain": (
                "Private finite representative set; it is not part of the "
                "public statement and is not the full input domain."
            ),
            "guard_features": {
                "names": list(GUARD_FEATURES),
                "definitions": GUARD_FEATURES,
                "note": (
                    "The public guard language is a boolean expression over "
                    "these derived features (plus int/bool constants, and/or/"
                    "not, comparisons, arithmetic).  The correct expression "
                    "is private."
                ),
            },
            "guard_language": (
                "Python expression AST restricted to names, int/bool "
                "constants, and/or/not, comparisons, and arithmetic.  No "
                "strings, calls, attributes, or subscripts."
            ),
        },
        "existing_tests": {
            "role": "T_original (the programmer's existing tests; background)",
            "source_kind": "real_upstream_test",
            "provenance": {
                "path": "tests/test_utils.py",
                "line_range": [644, 664],
                "block_sha256": UPSTREAM["test_block_sha256"],
                "file_sha256": UPSTREAM["test_file_sha256"],
                "url": UPSTREAM["test_url"],
            },
            "upstream_source": UPSTREAM_TEST_BLOCK,
            "adapted_source": adapted,
            "adaptation_note": (
                "The only adaptation is replacing pytest's parametrization "
                "with an explicit loop over the same five (value, expected) "
                "pairs so the standalone engine can execute it.  No pair, "
                "assertion, or expected value was changed."
            ),
            "cases": [
                {"case_id": f"t{i}", "value": value, "expected": expected}
                for i, (value, expected) in enumerate(cases, 1)
            ],
        },
        "why_suspected_redundant": (
            "Later code strips the same leading/trailing characters from URLs "
            "and parameter keys/values, so the initial whole-string strip looks "
            "redundant to a maintainer."
        ),
        "hidden_data_notice": (
            "The correct Guard, probe/evaluation labels, hidden evaluation "
            "inputs, and per-input observations are only in ../private/ and "
            "must not be given to a method under evaluation.  The probe "
            "inputs themselves are public."
        ),
        "evidence_policy": {
            "finite_domain_is_bounded": True,
            "never_mark_finite_enumeration_as_proven": True,
            "unsupported_is_not_analyzed": True,
        },
    }

    private = {
        "schema_version": "mace-benchmark-blind-v1-private",
        "task_id": TASK_ID,
        "bindings": {
            "public_task_sha256": None,  # filled below
            "program_source_sha256": sha256_text(plus),
            "p_minus_source_sha256": sha256_text(minus),
            "upstream_function_sha256": UPSTREAM["function_sha256"],
        },
        "execution_semantics": {
            "entry": "parse_header_links",
            "capture_line": engine.target_line(plus),
            "observable": "return value or exception, type-aware canonical form",
            "local_effect": "snapshot of locals immediately after A differs",
            "intervention": (
                "A subset S of candidate operations is *enabled*; every "
                "operation not in S is replaced by its receiver in both P+ and "
                "P-, and the observations are compared.  'enabled_none' means "
                "all candidate operations are disabled."
            ),
            "masking_set": (
                "For a case with a local effect, a non-empty inclusion-minimal "
                "enabled set S such that P+ and P- agree with exactly S "
                "enabled.  Size 1 is independent, size >= 2 is cooperative."
            ),
        },
        "guard": guard_summary,
        "finite_checks": {
            "exhaustive": exhaustive,
            "random_sample": random_sample,
        },
        "counts": counts,
        "public_probe_labels": probe_rows,
        "eval_cases": eval_rows,
        "test_cases": test_rows,
        "test_gap_summary": {
            "all_original_tests_pass_on_p_plus": all(
                r["plus"]["passed"] for r in test_rows),
            "all_original_tests_pass_on_p_minus": all(
                r["minus"]["passed"] for r in test_rows),
            "caught": counts["test_gaps"]["would_be_caught"],
            "masked_with_local_effect": counts["test_gaps"]["masked"],
            "unexercised": counts["test_gaps"]["unexercised"],
            "assertion_gap": counts["test_gaps"]["assertion_gap"],
            "test_broken": counts["test_gaps"]["test_broken"],
            "interpretation": (
                "All five original tests pass on both versions.  Four never "
                "exercise A's local effect ('unexercised').  One (t1) does "
                "exercise it, but a downstream strip masks the difference "
                "('masked').  None of them reaches an exposed input."
            ),
        },
        "operation_analysis": {
            "op_1": {"appears_in_minimal_sets": counts["masking_sets"]["op_1"],
                     "role_in_frozen_domain": "absorbs leading whole-string specials"},
            "op_2": {"appears_in_minimal_sets": counts["masking_sets"]["op_2"],
                     "role_in_frozen_domain": (
                         "real normalization operation, but it never absorbs A "
                         "on the frozen domain; a decoy candidate")},
            "op_3": {"appears_in_minimal_sets": counts["masking_sets"]["op_3"],
                     "role_in_frozen_domain": "absorbs trailing whole-string specials"},
        },
        "not_proven_statement": (
            "All labels are derived by execution on a frozen finite domain. "
            "They are BOUNDED evidence, not a proof over all Unicode strings. "
            "No label was written by a human formula and then copied."
        ),
    }

    private["bindings"]["public_task_sha256"] = sha256_text(dump_json(public))

    freeze = {
        "schema_version": "mace-benchmark-blind-v1-freeze",
        "task_id": TASK_ID,
        "protocol": "docs/MACE_benchmark_protocol_v1.md",
        "public_file": "benchmark_blind_v1/public/task_01_parse_header_links.json",
        "private_file": "benchmark_blind_v1/private/task_01_oracle.json",
        "public_sha256": sha256_text(dump_json(public)),
        "private_sha256": sha256_text(dump_json(private)),
        "builder_sha256": sha256_file(Path(__file__).resolve()),
        "frozen_at_utc": None,  # preserved on unchanged rebuilds
        "method_order": (
            "Methods read only the public file.  The freeze must exist before "
            "any method result is produced."
        ),
        "method_access": {"public_only": True, "private_readable_by_methods": False},
    }
    schema_path = PUBLIC_DIR / "SUBMISSION_SCHEMA.json"
    if schema_path.exists():
        freeze["public_schema_file"] = "benchmark_blind_v1/public/SUBMISSION_SCHEMA.json"
        freeze["public_schema_sha256"] = sha256_file(schema_path)
    return public, private, freeze, timings


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true",
                        help="verify frozen files match a fresh derivation")
    args = parser.parse_args()

    public, private, freeze, timings = build()
    public_path = PUBLIC_DIR / "task_01_parse_header_links.json"
    private_path = PRIVATE_DIR / "task_01_oracle.json"
    freeze_path = OUT / "FREEZE.json"

    if args.check:
        problems = []
        for path, expected in [(public_path, dump_json(public)),
                               (private_path, dump_json(private))]:
            if not path.exists() or path.read_text(encoding="utf-8") != expected:
                problems.append(str(path.relative_to(ROOT)))
        if not freeze_path.exists():
            problems.append(str(freeze_path.relative_to(ROOT)))
        else:
            stored = json.loads(freeze_path.read_text(encoding="utf-8"))
            for key in ["public_sha256", "private_sha256"]:
                if stored.get(key) != freeze[key]:
                    problems.append(f"{freeze_path.name}:{key}")
            if freeze.get("public_schema_sha256") != stored.get("public_schema_sha256"):
                problems.append(f"{freeze_path.name}:public_schema_sha256")
        if problems:
            print("FREEZE CHECK FAILED: " + ", ".join(problems))
            return 1
        print("FREEZE CHECK OK")
        print(f"public  {freeze['public_sha256']}")
        print(f"private {freeze['private_sha256']}")
        return 0

    previous = None
    if freeze_path.exists():
        try:
            previous = json.loads(freeze_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            previous = None
    unchanged = (
        previous is not None
        and previous.get("public_sha256") == freeze["public_sha256"]
        and previous.get("private_sha256") == freeze["private_sha256"]
        and previous.get("builder_sha256") == freeze["builder_sha256"]
    )
    freeze["frozen_at_utc"] = (
        previous.get("frozen_at_utc") if unchanged and previous else
        datetime.now(timezone.utc).replace(microsecond=0).isoformat()
    )

    installed = installed_check()
    if (installed.get("available")
            and installed.get("version") == "2.31.0"
            and not installed.get("matches_embedded")):
        raise SystemExit(
            "embedded source does not match installed requests 2.31.0; "
            "refusing to freeze a different function")
    write_json(public_path, public)
    write_json(private_path, private)
    write_json(freeze_path, freeze)
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    (LOG_DIR / "build.log").write_text(
        "\n".join([
            f"task_id: {TASK_ID}",
            f"frozen_at_utc: {freeze['frozen_at_utc']}",
            f"public_sha256: {freeze['public_sha256']}",
            f"private_sha256: {freeze['private_sha256']}",
            f"builder_sha256: {freeze['builder_sha256']}",
            f"installed_requests: {json.dumps(installed, ensure_ascii=False)}",
            f"counts: {json.dumps(private['counts'], ensure_ascii=False)}",
            f"exhaustive: {json.dumps(private['finite_checks']['exhaustive'], ensure_ascii=False)}",
            f"random_sample: {json.dumps(private['finite_checks']['random_sample'], ensure_ascii=False)}",
            f"timings: {json.dumps(timings, ensure_ascii=False)}",
            "status: FROZEN",
        ]) + "\n",
        encoding="utf-8", newline="\n")
    print("FROZEN", TASK_ID)
    print("public ", freeze["public_sha256"], public_path.relative_to(ROOT))
    print("private", freeze["private_sha256"], private_path.relative_to(ROOT))
    print("counts ", json.dumps(private["counts"], ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
