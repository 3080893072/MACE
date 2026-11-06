"""Reproduce the round-2 candidate evidence with verifier v2.

Run with the isolated Werkzeug test environment (pytest 7.2.0) and put the
upstream source tree on ``sys.path``.  The script does not import or run the
upstream package's test suite; it only imports the extracted function's
dependencies and executes the extracted body under statement-line
interventions.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
QUAL = Path(__file__).resolve().parent
UPSTREAM_SRC = Path("<local-path>")
CANDIDATE = QUAL / "candidates" / "werkzeug_is_resource_modified.py"
UPSTREAM_FILE = UPSTREAM_SRC / "werkzeug" / "sansio" / "http.py"
OUTPUT = QUAL / "out" / "verifier_v2_is_resource_modified.json"

for entry in (KIT, UPSTREAM_SRC):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from benchmark_pilot import verifier_v2 as v2  # noqa: E402

ENTRY = "is_resource_modified"
TARGET_LINE = 43
OPS = {"B": 65, "C": 72, "D": 79, "E": 86}
ARG_NAMES = [
    "http_range",
    "http_if_range",
    "http_if_modified_since",
    "http_if_none_match",
    "http_if_match",
    "etag",
    "data",
    "last_modified",
    "ignore_if_range",
]


def _function_body(path: Path, name: str) -> list[ast.stmt]:
    tree = ast.parse(path.read_text(encoding="utf-8"))
    matches = [
        node for node in tree.body
        if isinstance(node, ast.FunctionDef) and node.name == name
    ]
    if len(matches) != 1:
        raise RuntimeError(f"{path}: expected one function {name!r}")
    body = list(matches[0].body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body


def _case(**overrides):
    args = {
        "http_range": None,
        "http_if_range": None,
        "http_if_modified_since": None,
        "http_if_none_match": None,
        "http_if_match": None,
        "etag": None,
        "data": None,
        "last_modified": None,
        "ignore_if_range": False,
    }
    args.update(overrides)
    return args


def main() -> int:
    source = CANDIDATE.read_text(encoding="utf-8")
    minus = v2.replace_line_with_pass(source, TARGET_LINE)

    local_body = _function_body(CANDIDATE, ENTRY)
    upstream_body = _function_body(UPSTREAM_FILE, ENTRY)
    body_equal = ast.dump(
        ast.Module(body=local_body, type_ignores=[]),
        include_attributes=False,
    ) == ast.dump(
        ast.Module(body=upstream_body, type_ignores=[]),
        include_attributes=False,
    )
    if not body_equal:
        raise RuntimeError("extracted body differs from upstream")

    cases = v2.validate_cases(
        [
            (
                "mask_b_c",
                _case(
                    http_range="bytes=0-1",
                    http_if_range='"abc"',
                    http_if_modified_since="Sun, 01 Jan 2023 00:00:00 GMT",
                    etag='"abc"',
                    last_modified="Sat, 31 Dec 2022 00:00:00 GMT",
                ),
            ),
            (
                "mask_b_only",
                _case(
                    http_if_modified_since="Sun, 01 Jan 2023 00:00:00 GMT",
                    last_modified="Sat, 31 Dec 2022 00:00:00 GMT",
                ),
            ),
            (
                "mask_c_only",
                _case(
                    http_range="bytes=0-1",
                    http_if_range='"abc"',
                    etag='"abc"',
                ),
            ),
            ("mask_d_only", _case(http_if_none_match='"abc"', etag='"abc"')),
            ("mask_e_only", _case(http_if_match='W/"abc"', etag='"abc"')),
            ("expose_none", _case()),
        ],
        ARG_NAMES,
    )
    matrix = v2.run_matrix(
        source,
        minus,
        OPS,
        cases,
        entry=ENTRY,
        target_line=TARGET_LINE,
    )

    evidence = {}
    for case in cases:
        row = matrix.row(frozenset(), case.case_id)
        assert row is not None
        evidence[case.case_id] = {
            "base": row.status,
            "target_hit": row.plus.target_hit,
            "plus": row.plus.observation,
            "minus": row.minus.observation,
            "discover": v2.discover_relations(matrix, case.case_id),
        }

    matrix_evidence = {}
    for disabled in v2.subsets(matrix.ops):
        key = "+".join(sorted(disabled)) or "<none>"
        if not matrix.subset_ok(disabled):
            matrix_evidence[key] = {"error": matrix.errors.get(disabled)}
            continue
        matrix_evidence[key] = {
            case.case_id: {
                "status": matrix.row(disabled, case.case_id).status,
                "plus": matrix.row(disabled, case.case_id).plus.observation,
                "minus": matrix.row(disabled, case.case_id).minus.observation,
            }
            for case in cases
        }

    payload = {
        "candidate": "werkzeug_is_resource_modified",
        "project": "Werkzeug",
        "version": "2.2.3",
        "upstream_file": "src/werkzeug/sansio/http.py",
        "upstream_sha256": hashlib.sha256(UPSTREAM_FILE.read_bytes()).hexdigest(),
        "candidate_sha256": hashlib.sha256(CANDIDATE.read_bytes()).hexdigest(),
        "extraction_body_equal_ignoring_docstring": body_equal,
        "target_line_local": TARGET_LINE,
        "operation_lines_local": OPS,
        "scope": "single_witness",
        "cases": evidence,
        "intervention_matrix": matrix_evidence,
    }
    OUTPUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )

    for case in cases:
        row = evidence[case.case_id]
        print(
            f"{case.case_id:12} {row['base']:8} hit={row['target_hit']} "
            f"plus={row['plus']} minus={row['minus']}"
        )
        for rel in row["discover"]["coexisting"]:
            print(f"  coexisting {rel['ops']} valid={rel['valid']} "
                  f"minimal={rel['minimal']}")
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
