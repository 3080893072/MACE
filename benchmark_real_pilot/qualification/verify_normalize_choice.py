"""Verify the click Choice.normalize_choice masking relation with verifier v2.

The candidate file is an extraction of click 8.4.1's Choice class, plus a
small JSON-safe entry wrapper.  The method body is compared by AST with the
upstream source before any intervention is run.
"""
from __future__ import annotations

import ast
import hashlib
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
QUAL = Path(__file__).resolve().parent
UPSTREAM = Path("<local-path>")
CANDIDATE = QUAL / "candidates" / "click_normalize_choice.py"
OUTPUT = QUAL / "out" / "verifier_v2_click_normalize_choice.json"

for entry in (KIT, UPSTREAM.parents[1]):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from benchmark_pilot import verifier_v2 as v2  # noqa: E402

TARGET_LINE = 20
OPS = {"B": 23}
ENTRY = "_entry"


def _method_body(tree: ast.Module, class_name: str, method: str) -> list[ast.stmt]:
    classes = [
        n for n in tree.body
        if isinstance(n, ast.ClassDef) and n.name == class_name
    ]
    if len(classes) != 1:
        raise RuntimeError(f"expected one class {class_name!r}")
    methods = [
        n for n in classes[0].body
        if isinstance(n, ast.FunctionDef) and n.name == method
    ]
    if len(methods) != 1:
        raise RuntimeError(f"expected one method {method!r}")
    body = list(methods[0].body)
    if (
        body
        and isinstance(body[0], ast.Expr)
        and isinstance(body[0].value, ast.Constant)
        and isinstance(body[0].value.value, str)
    ):
        body = body[1:]
    return body


def main() -> int:
    source = CANDIDATE.read_text(encoding="utf-8")
    local_body = _method_body(ast.parse(source), "Choice", "normalize_choice")
    upstream_body = _method_body(
        ast.parse(UPSTREAM.read_text(encoding="utf-8")),
        "Choice",
        "normalize_choice",
    )
    body_equal = ast.dump(
        ast.Module(body=local_body, type_ignores=[]), include_attributes=False
    ) == ast.dump(
        ast.Module(body=upstream_body, type_ignores=[]), include_attributes=False
    )
    if not body_equal:
        raise RuntimeError("extracted method body differs from upstream")

    minus = v2.replace_line_with_pass(source, TARGET_LINE)
    cases = v2.validate_cases(
        [
            (
                "mask_ascii",
                {"choice": "ABC", "normalize_mode": "lower", "case_sensitive": False},
            ),
            (
                "mask_already",
                {"choice": "abc", "normalize_mode": "lower", "case_sensitive": False},
            ),
            (
                "expose_mapping",
                {"choice": "A-B", "normalize_mode": "map", "case_sensitive": False},
            ),
            (
                "expose_case_sensitive",
                {"choice": "ABC", "normalize_mode": "lower", "case_sensitive": True},
            ),
        ],
        ["choice", "normalize_mode", "case_sensitive"],
    )
    matrix = v2.run_matrix(
        source, minus, OPS, cases, entry=ENTRY, target_line=TARGET_LINE
    )

    evidence = {}
    for case in cases:
        row = matrix.row(frozenset(), case.case_id)
        if row is None:
            raise RuntimeError(f"missing base row for {case.case_id}")
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
        "candidate": "click_choice_normalize_choice",
        "project": "click",
        "version": "8.4.1",
        "upstream_file": "src/click/types.py",
        "upstream_sha256": hashlib.sha256(UPSTREAM.read_bytes()).hexdigest(),
        "candidate_sha256": hashlib.sha256(CANDIDATE.read_bytes()).hexdigest(),
        "extraction_method_body_equal_ignoring_docstring": body_equal,
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
            f"{case.case_id:24} {row['base']:8} hit={row['target_hit']} "
            f"plus={row['plus']} minus={row['minus']}"
        )
        for rel in row["discover"]["independent"]:
            print(
                f"  independent {rel['ops']} valid={rel['valid']} "
                f"minimal={rel['minimal']}"
            )
    print(f"wrote {OUTPUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
