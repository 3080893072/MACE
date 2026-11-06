"""Render the expansion funnel, qualifications and witnesses as Markdown.

Usage::

    python -m benchmark_real_v4.report
"""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

from benchmark_real_v4.config import EVIDENCE, V4

REPORTS = V4 / "reports"
QUAL = EVIDENCE / "qualification"
QUAL_DESIGNED = EVIDENCE / "qualification_designed"
WIT = EVIDENCE / "witnesses"
RELEASE = V4 / "release_candidates"


def _load(path: Path) -> Any:
    return json.loads(path.read_text(encoding="utf-8")) if path.exists() else None


def _funnel_rows(path: Path) -> List[Dict[str, Any]]:
    data = _load(path)
    return list(data["candidates"]) if data else []


def _qualification(candidate_id: str) -> Dict[str, Any] | None:
    slug = (candidate_id.replace(":", "_").replace("/", "_")
            .replace("\\", "_").replace(".", "_"))[:120]
    return _load(QUAL_DESIGNED / f"{slug}.json") or _load(QUAL / f"{slug}.json")


def _release(candidate_id: str) -> Dict[str, Any] | None:
    slug = (candidate_id.replace(":", "_").replace("/", "_")
            .replace("\\", "_").replace(".", "_"))[:120]
    return _load(RELEASE / f"{slug}.json")


def _witness(candidate_id: str) -> Dict[str, Any] | None:
    slug = (candidate_id.replace(":", "_").replace("/", "_")
            .replace("\\", "_").replace(".", "_"))[:120]
    return _load(WIT / f"{slug}.json")


def _class_counts(data: Dict[str, Any] | None) -> str:
    if not data:
        return "-"
    return ", ".join(f"{k}={v}" for k, v in sorted(data["counts"].items()))


def build_markdown() -> str:
    first = _funnel_rows(EVIDENCE / "screening_funnel.json")
    more = _funnel_rows(EVIDENCE / "screening_funnel_more.json")
    extra = _funnel_rows(EVIDENCE / "screening_funnel_extra.json")
    rows = first + more + extra
    # One candidate was screened by hand after the extra campaign closed.
    for path in sorted((EVIDENCE / "screening_rows_extra").glob("manual_*.json")):
        rows.append(_load(path))
    unique = {row["candidate_id"]: row for row in rows}
    unique_rows = list(unique.values())
    by_status = Counter(row["screening_status"] for row in unique_rows)
    by_project: Dict[str, Counter] = defaultdict(Counter)
    for row in unique_rows:
        by_project[row["project_id"]][row["screening_status"]] += 1
    survivors = [row for row in unique_rows
                 if row["screening_status"] == "TEST_SURVIVING_DELETION"]
    all_static = []
    for name in ("candidates_static.json", "candidates_static_more.json"):
        data = _load(V4 / "candidates" / name)
        if data:
            all_static.extend(data["candidates"])
    mechanisms = Counter(row.get("mechanism", "name-overwrite")
                         for row in all_static)
    lines = [
        "# v4 expansion: real masking candidates",
        "",
        f"Static candidates: {len(all_static)}  ",
        "Mechanisms: " + ", ".join(
            f"{key}={value}" for key, value in sorted(mechanisms.items())),
        "",
        "## Screening funnel",
        "",
        f"Rows reviewed: {len(rows)}; unique candidates: {len(unique_rows)}.  ",
        "",
        "| status | count |",
        "| --- | ---: |",
    ]
    for status, count in sorted(by_status.items(), key=lambda item: -item[1]):
        lines.append(f"| {status} | {count} |")
    lines += ["", "| project | " + " | ".join(sorted(by_status)) + " |",
              "| --- | " + " | ".join("---:" for _ in by_status) + " |"]
    for project in sorted(by_project):
        cells = [str(by_project[project].get(status, 0))
                 for status in sorted(by_status)]
        lines.append(f"| {project} | " + " | ".join(cells) + " |")
    lines += ["", "## Survivors", ""]
    if not survivors:
        lines.append("No candidate survived the applicable suite.")
    for row in sorted(survivors, key=lambda item: item["candidate_id"]):
        qual = _qualification(row["candidate_id"])
        wit = _witness(row["candidate_id"])
        lines += [
            f"### `{row['candidate_id']}`",
            "",
            f"- project: {row['project']} {row['version']}",
            f"- file/function: `{row['file']}` / `{row['function']}`",
            f"- A: line {row['target_A']['line']} — `{row['target_A']['code']}`",
            f"- mechanism: {row.get('mechanism', 'name-overwrite')}",
            f"- later operations: " + ", ".join(
                f"L{item['line']}" for item in row["later_assignments"]),
            f"- P+ hit tests: {row['p_plus_hit_test_count']}",
            f"- P- applicable suite: " + (
                "passed" if (row.get("full_minus") or {}).get("returncode") == 0
                else "not passed / not run"),
            f"- qualification: {_class_counts(qual)}",
            f"- witness: " + (
                f"exposing={wit['summary']['exposing']}, "
                f"masked={wit['summary']['masked']}, "
                f"msms={wit['summary']['verified_msms']}, "
                f"mmbs={wit['summary']['verified_mmbs']}"
                if wit else "-"),
            f"- release candidate: " + (
                ("promoted" if (_release(row["candidate_id"]) or {}).get("promoted")
                 else "not promoted")
                if _release(row["candidate_id"]) else "no release file"),
            "",
        ]
    lines += [
        "## Designed-test recoveries",
        "",
        "These candidates did not survive the original-suite funnel, but their",
        "target statements are real and their declared tests are explicitly",
        "marked DESIGNED.  All five were promoted only after execution showed",
        "the designed tests still pass under P-.",
        "",
        "| candidate | original screening | A | designed tests | qualification | witness |",
        "| --- | --- | --- | ---: | --- | --- |",
    ]
    for path in sorted(RELEASE.glob("*.json")):
        release = _load(path)
        if not release or not release.get("promoted"):
            continue
        cid = release["candidate_id"]
        original = unique.get(cid, {}).get("screening_status", "MANUAL")
        wit = _witness(cid) or {}
        summary = wit.get("summary", {})
        lines.append(
            f"| `{cid}` | {original} | "
            f"`{release['conditions']['1_real_source_and_A']['A']['code']}` | "
            f"{len(release['declared_tests'])} | "
            f"{_class_counts(_qualification(cid))} | "
            f"masked={summary.get('masked')}, exposing={summary.get('exposing')} |")
    lines += [
        "",
        "## Original-suite survivors rejected on review (0 of 26 promoted)",
        "",
        "| candidate | qualification | reason |",
        "| --- | --- | --- |",
    ]
    for row in sorted(survivors, key=lambda item: item["candidate_id"]):
        if (_release(row["candidate_id"]) or {}).get("promoted"):
            continue
        qual = _qualification(row["candidate_id"])
        lines.append(
            f"| `{row['candidate_id']}` | {_class_counts(qual)} | "
            f"{row.get('reason', '') or 'see qualification / manual review'} |")
    lines += [
        "",
        "## Non-survivors worth keeping",
        "",
        "| candidate | status | reason |",
        "| --- | --- | --- |",
    ]
    for row in sorted(unique_rows, key=lambda item: item["candidate_id"]):
        if row["screening_status"] == "TEST_SURVIVING_DELETION":
            continue
        if row["screening_status"] == "TARGETED_TEST_DETECTS_DELETION":
            continue
        lines.append(
            f"| `{row['candidate_id']}` | {row['screening_status']} | "
            f"{row.get('reason', '')} |")
    return "\n".join(lines) + "\n"


def main() -> int:
    REPORTS.mkdir(parents=True, exist_ok=True)
    path = REPORTS / "expansion_report.md"
    path.write_text(build_markdown(), encoding="utf-8")
    print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
