"""Reproduce the round-3 screening observations for rejected candidates.

Each screen uses the upstream file as the executable task source.  Relative
imports are rewritten in memory only; the files on disk are not modified.
Results are saved as JSON next to the other qualification evidence.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
QUAL = Path(__file__).resolve().parent
PROJECTS = Path("<local-path>")
OUT = QUAL / "out" / "round3_screening.json"

for entry in (KIT, PROJECTS / "packaging-23.1/src", PROJECTS / "click-8.4.1/src"):
    if str(entry) not in sys.path:
        sys.path.insert(0, str(entry))

from benchmark_pilot import verifier_v2 as v2  # noqa: E402


def _click_source(path: Path) -> str:
    source = path.read_text(encoding="utf-8")
    return (
        source.replace("from ._compat", "from click._compat")
        .replace("from .exceptions", "from click.exceptions")
        .replace("from .utils", "from click.utils")
        .replace("from .parser", "from click.parser")
        .replace("from ._textwrap", "from click._textwrap")
    )


def _run_case_set(
    source: str,
    target_line: int,
    ops: dict[str, int],
    entry: str,
    cases: list[tuple[str, dict]],
    arg_names: list[str],
) -> dict:
    validated = v2.validate_cases(cases, arg_names)
    minus = v2.replace_line_with_pass(source, target_line)
    matrix = v2.run_matrix(
        source, minus, ops, validated, entry=entry, target_line=target_line
    )
    out = {}
    for case in validated:
        row = matrix.row(frozenset(), case.case_id)
        if row is None:
            raise RuntimeError(f"missing base row for {case.case_id}")
        out[case.case_id] = {
            "status": row.status,
            "target_hit": row.plus.target_hit,
            "plus": row.plus.observation,
            "minus": row.minus.observation,
            "relations": v2.discover_relations(matrix, case.case_id),
        }
    return out


def main() -> int:
    payload = {}

    # click.formatting.wrap_text: line 90 resets the paragraph indent, line 95
    # recomputes it.  Deletion is masked only when the stale indent happens to
    # equal the recomputed one; disabling line 95 does not expose it.
    wrap_src = _click_source(PROJECTS / "click-8.4.1/src/click/formatting.py")
    payload["click_wrap_text"] = {
        "file": "click-8.4.1/src/click/formatting.py",
        "target_A": {"line": 90, "code": "indent = None"},
        "operation_B": {"line": 95, "code": "indent = orig_len - term_len(line)"},
        "cases": _run_case_set(
            wrap_src,
            90,
            {"B": 95},
            "wrap_text",
            [
                (
                    "mask_equal_indent",
                    {
                        "text": "a\n\nb",
                        "width": 78,
                        "initial_indent": "",
                        "subsequent_indent": "",
                        "preserve_paragraphs": True,
                    },
                ),
                (
                    "expose_changed_indent",
                    {
                        "text": "  a\n\nb",
                        "width": 78,
                        "initial_indent": "",
                        "subsequent_indent": "",
                        "preserve_paragraphs": True,
                    },
                ),
            ],
            [
                "text",
                "width",
                "initial_indent",
                "subsequent_indent",
                "preserve_paragraphs",
            ],
        ),
    }

    # jinja2.utils.urlize: line 282 strips a leading delimiter after copying
    # the same delimiter into `head`; deleting it duplicates the delimiter.
    urlize_src = (PROJECTS / "jinja2-3.1.3/src/jinja2/utils.py").read_text(
        encoding="utf-8"
    )
    payload["jinja2_urlize"] = {
        "file": "jinja2-3.1.3/src/jinja2/utils.py",
        "target_A": {"line": 282, "code": "middle = middle[match.end() :]"},
        "operations": {str(line): line for line in (292, 307, 322, 330, 335)},
        "cases": _run_case_set(
            urlize_src,
            282,
            {f"O{line}": line for line in (292, 307, 322, 330, 335)},
            "urlize",
            [
                (
                    "mask_A_not_executed",
                    {
                        "text": "abc",
                        "trim_url_limit": None,
                        "rel": None,
                        "target": None,
                        "extra_schemes": None,
                    },
                ),
                (
                    "expose_parenthesized_text",
                    {
                        "text": "(abc)",
                        "trim_url_limit": None,
                        "rel": None,
                        "target": None,
                        "extra_schemes": None,
                    },
                ),
                (
                    "expose_parenthesized_url",
                    {
                        "text": "(http://example.com)",
                        "trim_url_limit": None,
                        "rel": None,
                        "target": None,
                        "extra_schemes": None,
                    },
                ),
            ],
            ["text", "trim_url_limit", "rel", "target", "extra_schemes"],
        ),
    }

    # packaging.version._parse_letter_version: line 464 lowercases the letter,
    # but no downstream operation overwrites `letter`; the lowercase path is a
    # no-op and the uppercase path is exposed directly.
    version_src = (PROJECTS / "packaging-23.1/src/packaging/version.py").read_text(
        encoding="utf-8"
    ).replace("from ._structures", "from packaging._structures")
    payload["packaging_parse_letter_version"] = {
        "file": "packaging-23.1/src/packaging/version.py",
        "target_A": {"line": 464, "code": "letter = letter.lower()"},
        "operation_B": {"line": 470, "code": 'letter = "post"'},
        "cases": _run_case_set(
            version_src,
            464,
            {"B": 470},
            "_parse_letter_version",
            [
                ("mask_no_value_change", {"letter": "alpha", "number": 1}),
                ("expose_uppercase", {"letter": "ALPHA", "number": 1}),
            ],
            ["letter", "number"],
        ),
    }

    OUT.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    for name, block in payload.items():
        print(name)
        for case_id, row in block["cases"].items():
            print(
                f"  {case_id:32} {row['status']:8} hit={row['target_hit']} "
                f"plus={row['plus']} minus={row['minus']}"
            )
    print(f"wrote {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
