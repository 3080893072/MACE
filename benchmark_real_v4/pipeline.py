"""Static scan, P+ trace, deletion screening and funnel report for v4.

Usage::

    python -m benchmark_real_v4.pipeline scan
    python -m benchmark_real_v4.pipeline trace
    python -m benchmark_real_v4.pipeline screen
    python -m benchmark_real_v4.pipeline report

The logic is the v3 funnel, but every path, project and budget comes from
``benchmark_real_v4.config``.  The v3 package is imported only as a library;
its evidence and release directories are never written.
"""
from __future__ import annotations

import ast
import hashlib
import json
import shutil
import sys
from collections import defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, List, Tuple

from benchmark_real_v3 import run_suite as rs
from benchmark_real_v3.scan_candidates import (
    _assignment_code,
    _local_nodes,
    _reads_between,
    _reads_name,
    _scope_depth,
    _simple_assignment,
)
from benchmark_real_v4.config import (
    BUDGET,
    CANDIDATES,
    EVIDENCE,
    PROJECTS,
    WORK_ROOT,
)

STATIC_PATH = CANDIDATES / "candidates_static.json"
FUNNEL_PATH = EVIDENCE / "screening_funnel.json"
ROWS_DIR = EVIDENCE / "screening_rows"


# --------------------------------------------------------------------- scan
def _functions(tree: ast.Module) -> Iterable[ast.AST]:
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            yield node


def scan_project(project_id: str) -> List[Dict[str, Any]]:
    cfg = PROJECTS[project_id]
    root = cfg["root"]
    candidates: List[Dict[str, Any]] = []
    for rel in cfg["scan_files"]:
        path = root / rel
        text = path.read_text(encoding="utf-8")
        tree = ast.parse(text)
        lines = text.splitlines()
        for fn in _functions(tree):
            nodes = _local_nodes(fn)
            assignments: Dict[str, List[Tuple[int, str, ast.AST]]] = {}
            for stmt in nodes:
                parsed = _simple_assignment(stmt)
                if parsed is None:
                    continue
                name, line = parsed
                assignments.setdefault(name, []).append(
                    (line, type(stmt).__name__, stmt))
            for name, rows in assignments.items():
                rows = sorted(set(rows), key=lambda row: (row[0], row[1]))
                if len(rows) < 2:
                    continue
                for index, (line, kind, node) in enumerate(rows[:-1]):
                    later = [r for r in rows[index + 1:] if r[0] > line]
                    if not later:
                        continue
                    same_line = [
                        n for n in ast.walk(tree)
                        if isinstance(n, ast.stmt) and n.lineno == line
                    ]
                    if len(same_line) != 1:
                        continue
                    reads = _reads_between(nodes, name, line, later[0][0])
                    later_rows = [
                        {
                            "line": other_line,
                            "kind": other_kind,
                            "code": _assignment_code(lines, other_line),
                            "reads_A": _reads_name(other_node, name),
                        }
                        for other_line, other_kind, other_node in later
                    ]
                    flags = _scope_depth(nodes, line)
                    candidates.append({
                        "candidate_id": f"{project_id}:{rel}:{line}:{name}",
                        "project_id": project_id,
                        "project": cfg["project"],
                        "version": cfg["version"],
                        "file": rel,
                        "function": getattr(fn, "name", "<lambda>"),
                        "variable": name,
                        "target_A": {
                            "line": line,
                            "kind": kind,
                            "code": _assignment_code(lines, line),
                        },
                        "later_assignments": later_rows,
                        "read_between_A_and_first_later": reads,
                        "static_shape": {
                            **flags,
                            "read_before_later_write": bool(reads),
                            "later_write_reads_A": any(
                                row["reads_A"] for row in later_rows),
                            "later_write_is_plain_assign": (
                                later[0][1] == "Assign"),
                        },
                        "source_sha256": hashlib.sha256(
                            path.read_bytes()).hexdigest(),
                    })
    return candidates


def _tree_hash(project_id: str) -> str:
    cfg = PROJECTS[project_id]
    digest = hashlib.sha256()
    for rel in cfg["scan_files"]:
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update((cfg["root"] / rel).read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def cmd_scan() -> int:
    rows: List[Dict[str, Any]] = []
    meta = {}
    for project_id, cfg in PROJECTS.items():
        rows.extend(scan_project(project_id))
        meta[project_id] = {
            "project": cfg["project"],
            "version": cfg["version"],
            "root": str(cfg["root"]),
            "scan_files": cfg["scan_files"],
            "source_hash": _tree_hash(project_id),
            "python": cfg["python"],
            "pytest": cfg["pytest"],
            "suite_note": cfg["suite_note"],
        }
    rows.sort(key=lambda row: (row["project_id"], row["file"],
                               row["target_A"]["line"], row["variable"]))
    seen = set()
    unique = []
    for row in rows:
        if row["candidate_id"] in seen:
            continue
        seen.add(row["candidate_id"])
        unique.append(row)
    CANDIDATES.mkdir(parents=True, exist_ok=True)
    STATIC_PATH.write_text(json.dumps({
        "protocol": "benchmark_real_v4",
        "projects": meta,
        "candidates": unique,
        "counts": {
            pid: sum(1 for row in unique if row["project_id"] == pid)
            for pid in PROJECTS
        },
    }, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({
        "path": str(STATIC_PATH),
        "counts": {
            pid: sum(1 for row in unique if row["project_id"] == pid)
            for pid in PROJECTS
        },
        "total": len(unique),
    }, ensure_ascii=False, indent=2))
    return 0


# -------------------------------------------------------------------- trace
def _patch_runner() -> None:
    rs.PROJECTS = PROJECTS
    rs.WORK_ROOT = WORK_ROOT
    rs.EVIDENCE = EVIDENCE


def cmd_trace() -> int:
    _patch_runner()
    summary = {}
    for project_id, cfg in PROJECTS.items():
        WORK_ROOT.mkdir(parents=True, exist_ok=True)
        root = WORK_ROOT / f"{project_id}_plus"
        rs.copy_project(cfg["root"], root)
        run = rs.run_pytest(
            root, project_id, nodeids=None,
            output_name=f"{project_id}_plus",
            trace_files=cfg["scan_files"],
            timeout=BUDGET["full_timeout"],
        )
        summary[project_id] = {
            "returncode": run["returncode"],
            "timed_out": run["timed_out"],
            "duration_seconds": run["duration_seconds"],
            "summary": run["summary"],
            "log": run["log"],
            "trace": run["trace_json"],
        }
    (EVIDENCE / "plus_runs.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps({
        pid: {
            "rc": row["returncode"],
            "passed": row["summary"]["outcomes"].get("passed"),
            "failed": row["summary"]["outcomes"].get("failed"),
            "reports": row["summary"]["reports"],
            "seconds": round(row["duration_seconds"], 2),
        }
        for pid, row in summary.items()
    }, ensure_ascii=False, indent=2))
    return 0


# ------------------------------------------------------------------- screen
def _excluded_nodes(project_id: str) -> set:
    """Node ids deselected by the project's applicable-suite arguments."""
    args = PROJECTS[project_id].get("extra_args", [])
    out = set()
    for index, arg in enumerate(args):
        if arg == "--deselect" and index + 1 < len(args):
            out.add(args[index + 1])
    return out


def _hit_tests(plus: Dict[str, Any], file: str, line: int,
               excluded: set | None = None) -> List[str]:
    out = []
    for nodeid, files in plus.get("hits", {}).items():
        if excluded and nodeid in excluded:
            continue
        if line in files.get(file, []):
            out.append(nodeid)
    return sorted(out)


def _priority(row: Dict[str, Any]) -> Tuple:
    shape = row["static_shape"]
    return (
        0 if (shape["in_loop"] or shape["in_try"]) else 1,
        1 if shape["read_before_later_write"] else 0,
        len(row["later_assignments"]),
        -row["target_A"]["line"],
    )


def _round_robin(rows: List[Dict[str, Any]], limit: int) -> List[Dict[str, Any]]:
    per_project: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for row in rows:
        per_project[row["project_id"]].append(row)
    for project in per_project:
        per_project[project].sort(key=_priority, reverse=True)
    selected = []
    cursor = 0
    while len(selected) < limit:
        added = False
        for project in sorted(per_project):
            rows_p = per_project[project]
            if cursor < len(rows_p) and len(selected) < limit:
                selected.append(rows_p[cursor])
                added = True
        if not added:
            break
        cursor += 1
    return selected


def _safe(name: str) -> str:
    return (name.replace(":", "_").replace("/", "_").replace("\\", "_")
            .replace(".", "_"))[:120]


def _checkpoint(index: int, row: Dict[str, Any]) -> None:
    ROWS_DIR.mkdir(parents=True, exist_ok=True)
    (ROWS_DIR / f"{index:03d}.json").write_text(
        json.dumps(row, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def _prepare_base(project_id: str) -> Path:
    base = WORK_ROOT / f"{project_id}_minus_base"
    if not base.exists():
        rs.copy_project(PROJECTS[project_id]["root"], base)
    return base


def _restore_base(project_id: str, base: Path) -> None:
    cfg = PROJECTS[project_id]
    for rel in cfg["scan_files"]:
        target = base / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cfg["root"] / rel, target)


def cmd_screen() -> int:
    _patch_runner()
    static = json.loads(STATIC_PATH.read_text(encoding="utf-8"))
    plus = {
        pid: json.loads((EVIDENCE / f"{pid}_plus.trace.json").read_text(
            encoding="utf-8"))
        for pid in PROJECTS
    }
    rows = []
    for row in static["candidates"]:
        tests = _hit_tests(plus[row["project_id"]], row["file"],
                           row["target_A"]["line"],
                           _excluded_nodes(row["project_id"]))
        row = dict(row)
        row["p_plus_hit_tests"] = tests
        row["p_plus_hit_test_count"] = len(tests)
        if not tests:
            row["screening_status"] = "NO_ORIGINAL_TEST_EXECUTES_A"
            row["reason"] = "No P+ test executes A."
        elif not (row["static_shape"]["read_before_later_write"]
                  or row["static_shape"]["later_write_reads_A"]):
            row["screening_status"] = "STATIC_REJECT_DEAD_BEFORE_READ"
            row["reason"] = "Deleting A is a dead store on the static shape."
        else:
            row["screening_status"] = "STATIC_ELIGIBLE"
            row["reason"] = "P+ coverage and a read/later-use shape."
        rows.append(row)

    eligible = [r for r in rows if r["screening_status"] == "STATIC_ELIGIBLE"]
    review = _round_robin(eligible, BUDGET["max_candidates_reviewed"])
    review_ids = {r["candidate_id"] for r in review}
    for row in rows:
        if row["screening_status"] == "STATIC_ELIGIBLE" \
                and row["candidate_id"] not in review_ids:
            row["screening_status"] = "NOT_REVIEWED_BUDGET"
            row["reason"] = "Outside the predeclared review budget; no P- run."
            row["p_plus_hit_tests"] = row.get("p_plus_hit_tests", [])

    targeted_used = 0
    full_used = 0
    by_id = {row["candidate_id"]: row for row in rows}
    loaded: Dict[str, Dict[str, Any]] = {}
    if ROWS_DIR.exists():
        for path in sorted(ROWS_DIR.glob("*.json")):
            data = json.loads(path.read_text(encoding="utf-8"))
            loaded[data["candidate_id"]] = data
            targeted_used += int(bool(data.get("targeted_minus")))
            full_used += int(bool(data.get("full_minus")))

    bases: Dict[str, Path] = {}
    for index, row in enumerate(review):
        cid = row["candidate_id"]
        if cid in loaded:
            target = by_id[cid]
            target.clear()
            target.update(loaded[cid])
            continue
        if targeted_used >= BUDGET["max_targeted_minus_runs"]:
            row["screening_status"] = "TARGETED_NOT_RUN_BUDGET"
            row["reason"] = "Targeted P- budget exhausted."
            _checkpoint(index, row)
            continue
        pid = row["project_id"]
        base = bases.setdefault(pid, _prepare_base(pid))
        _restore_base(pid, base)
        row["deletion"] = rs.delete_line(
            base, row["file"], row["target_A"]["line"])
        run = rs.run_pytest(
            base, pid, nodeids=row["p_plus_hit_tests"],
            output_name=f"v4_screen_{index:03d}_{_safe(cid)}_targeted",
            trace_files=None,
            timeout=BUDGET["targeted_timeout"],
        )
        targeted_used += 1
        row["targeted_minus"] = {
            "returncode": run["returncode"],
            "timed_out": run["timed_out"],
            "summary": run["summary"],
            "log": run["log"],
        }
        caught = (run["timed_out"] or run["returncode"] != 0
                  or bool(run["summary"].get("failed_nodeids")))
        if caught:
            row["screening_status"] = "TARGETED_TEST_DETECTS_DELETION"
            row["reason"] = "An original test that executes A fails under P-."
            _restore_base(pid, base)
            _checkpoint(index, row)
            continue
        row["screening_status"] = "TARGETED_TESTS_SURVIVE"
        if full_used >= BUDGET["max_full_suite_minus_runs"]:
            row["screening_status"] = "FULL_SUITE_NOT_RUN_BUDGET"
            row["reason"] = "Full-suite P- budget exhausted."
            _restore_base(pid, base)
            _checkpoint(index, row)
            continue
        full = rs.run_pytest(
            base, pid, nodeids=None,
            output_name=f"v4_screen_{index:03d}_{_safe(cid)}_full",
            trace_files=None,
            timeout=BUDGET["full_timeout"],
        )
        full_used += 1
        row["full_minus"] = {
            "returncode": full["returncode"],
            "timed_out": full["timed_out"],
            "summary": full["summary"],
            "log": full["log"],
            "duration_seconds": full["duration_seconds"],
        }
        if (full["timed_out"] or full["returncode"] != 0
                or full["summary"].get("failed_nodeids")):
            row["screening_status"] = "PROJECT_SUITE_DETECTS_DELETION"
            row["reason"] = "Applicable project suite fails under P-."
        else:
            row["screening_status"] = "TEST_SURVIVING_DELETION"
            row["reason"] = "Targeted and applicable full suites pass under P-."
        _restore_base(pid, base)
        _checkpoint(index, row)

    counts: Dict[str, int] = defaultdict(int)
    for row in rows:
        counts[row["screening_status"]] += 1
    surviving = [row for row in rows
                 if row["screening_status"] == "TEST_SURVIVING_DELETION"]
    payload = {
        "protocol": "benchmark_real_v4",
        "budget": {
            **BUDGET,
            "targeted_runs_used": targeted_used,
            "full_suite_runs_used": full_used,
        },
        "counts": dict(sorted(counts.items())),
        "survivors": sorted(row["candidate_id"] for row in surviving),
        "candidates": rows,
    }
    FUNNEL_PATH.write_text(json.dumps(payload, ensure_ascii=False, indent=2)
                           + "\n", encoding="utf-8")
    print(json.dumps({
        "counts": payload["counts"],
        "budget": payload["budget"],
        "survivors": len(surviving),
        "by_project": {
            pid: sum(1 for row in surviving if row["project_id"] == pid)
            for pid in PROJECTS
        },
    }, ensure_ascii=False, indent=2))
    for row in surviving:
        print(" ", row["candidate_id"], f"tests={row['p_plus_hit_test_count']}")
    print("wrote", FUNNEL_PATH)
    return 0


# ------------------------------------------------------------------- report
def cmd_report() -> int:
    funnel = json.loads(FUNNEL_PATH.read_text(encoding="utf-8"))
    survivors = [row for row in funnel["candidates"]
                 if row["screening_status"] == "TEST_SURVIVING_DELETION"]
    report = {
        "protocol": "benchmark_real_v4",
        "counts": funnel["counts"],
        "budget": funnel["budget"],
        "survivors": [
            {
                "candidate_id": row["candidate_id"],
                "project": row["project"],
                "version": row["version"],
                "file": row["file"],
                "function": row["function"],
                "variable": row["variable"],
                "A": row["target_A"],
                "later_assignments": row["later_assignments"],
                "static_shape": row["static_shape"],
                "p_plus_hit_test_count": row["p_plus_hit_test_count"],
                "p_plus_hit_tests": row["p_plus_hit_tests"],
            }
            for row in sorted(survivors, key=lambda r: r["candidate_id"])
        ],
    }
    (EVIDENCE / "survivors.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps({
        "survivors": len(survivors),
        "by_project": {
            pid: sum(1 for row in survivors if row["project_id"] == pid)
            for pid in PROJECTS
        },
        "path": str(EVIDENCE / "survivors.json"),
    }, ensure_ascii=False, indent=2))
    return 0


def main() -> int:
    if len(sys.argv) != 2 or sys.argv[1] not in {
            "scan", "trace", "screen", "report"}:
        print("usage: python -m benchmark_real_v4.pipeline "
              "scan|trace|screen|report")
        return 2
    return {
        "scan": cmd_scan,
        "trace": cmd_trace,
        "screen": cmd_screen,
        "report": cmd_report,
    }[sys.argv[1]]()


if __name__ == "__main__":
    raise SystemExit(main())
