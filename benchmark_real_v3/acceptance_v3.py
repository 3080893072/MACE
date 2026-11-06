"""Independent acceptance path for the five v3 benchmark tasks.

This module intentionally does not import ``verify_task``, ``variant_lab`` or
``run_suite``.  It rebuilds every artifact from the fixed upstream project
trees with its own copy/delete/probe/pytest code, compares the result with the
stored evidence, and writes a separate acceptance report.  Stored matrices and
the qualification registry are never overwritten.

Usage::

    python -m benchmark_real_v3.acceptance_v3
    python -m benchmark_real_v3.acceptance_v3 --tasks jinja2_bytecode_cache_read
    python -m benchmark_real_v3.acceptance_v3 --skip-suite --skip-t-task

The report is written to
``benchmark_real_v3/evidence/acceptance/acceptance_report.json``.
"""
from __future__ import annotations

import argparse
import hashlib
import itertools
import json
import os
import re
import shutil
import subprocess
import sys
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from benchmark_real_v3.config import EVIDENCE, PROJECTS, V3

TASKS = V3 / "tasks"
PROBES = V3 / "probes"
QUALIFIED = TASKS / "qualified_tasks.json"
PROJECT_HASHES = EVIDENCE / "project_source_hashes.json"
ACCEPT_ROOT = Path("<local-path>")
OUT_DIR = EVIDENCE / "acceptance"
OUT = OUT_DIR / "acceptance_report.json"
TRACE_HELPER = V3 / "acceptance_probe.py"

IGNORE = shutil.ignore_patterns(
    "__pycache__", "*.pyc", "*.pyo", ".pytest_cache", ".git", ".tox",
    ".venv", "venv", "build", "dist", "*.egg-info",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _project_hash(project_id: str) -> str:
    cfg = PROJECTS[project_id]
    digest = hashlib.sha256()
    for path in sorted((cfg["root"] / cfg["source_dir"]).rglob("*.py")):
        rel = path.relative_to(cfg["root"]).as_posix()
        digest.update(rel.encode("utf-8"))
        digest.update(b"\0")
        digest.update(path.read_bytes())
        digest.update(b"\0")
    return digest.hexdigest()


def _copy_project(project_id: str, destination: Path) -> None:
    if destination.exists():
        shutil.rmtree(destination)
    shutil.copytree(PROJECTS[project_id]["root"], destination, ignore=IGNORE)


def _delete_line(root: Path, file: str, line: int) -> Dict[str, Any]:
    path = root / file
    text = path.read_text(encoding="utf-8")
    lines = text.splitlines(keepends=True)
    original = lines[line - 1]
    if not original.strip():
        raise RuntimeError(f"target line is blank: {file}:{line}")
    indent = original[: len(original) - len(original.lstrip())]
    replacement = indent + "pass  # P-: target A deleted\n"
    lines[line - 1] = replacement
    path.write_text("".join(lines), encoding="utf-8")
    return {
        "file": file,
        "line": line,
        "original": original.rstrip("\n"),
        "replacement": replacement.rstrip("\n"),
    }


def _disable_operation(root: Path, op: Dict[str, Any]) -> None:
    path = root / op["file"]
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    if op.get("kind") == "block":
        first, last = int(op["first_line"]), int(op["last_line"])
        indent = lines[first - 1][
            : len(lines[first - 1]) - len(lines[first - 1].lstrip())]
        lines[first - 1:last] = [indent + "pass  # intervention: disabled block\n"]
    else:
        first = last = int(op["line"])
        indent = lines[first - 1][
            : len(lines[first - 1]) - len(lines[first - 1].lstrip())]
        lines[first - 1] = indent + "pass  # intervention: disabled operation\n"
    path.write_text("".join(lines), encoding="utf-8")


def _tree_diff(plus: Path, minus: Path, source_dir: str) -> Dict[str, Any]:
    a_root = plus / source_dir
    b_root = minus / source_dir
    a_files = {
        p.relative_to(a_root).as_posix(): p
        for p in a_root.rglob("*") if p.is_file()
    }
    b_files = {
        p.relative_to(b_root).as_posix(): p
        for p in b_root.rglob("*") if p.is_file()
    }
    only_plus = sorted(set(a_files) - set(b_files))
    only_minus = sorted(set(b_files) - set(a_files))
    changed: Dict[str, Any] = {}
    for rel in sorted(set(a_files) & set(b_files)):
        a_bytes = a_files[rel].read_bytes()
        b_bytes = b_files[rel].read_bytes()
        if a_bytes == b_bytes:
            continue
        try:
            a_lines = a_bytes.decode("utf-8").splitlines()
            b_lines = b_bytes.decode("utf-8").splitlines()
        except UnicodeDecodeError:
            changed[rel] = {"binary": True}
            continue
        diff_lines = [
            index + 1
            for index, (left, right) in enumerate(zip(a_lines, b_lines))
            if left != right
        ]
        changed[rel] = {
            "binary": False,
            "line_count_plus": len(a_lines),
            "line_count_minus": len(b_lines),
            "different_lines": diff_lines,
            "plus_lines": {line: a_lines[line - 1] for line in diff_lines},
            "minus_lines": {line: b_lines[line - 1] for line in diff_lines},
        }
    return {
        "only_in_plus": only_plus,
        "only_in_minus": only_minus,
        "changed": changed,
        "file_count": len(a_files),
    }


def _probe_env(root: Path, project_id: str) -> Dict[str, str]:
    cfg = PROJECTS[project_id]
    env = os.environ.copy()
    env["PYTHONPATH"] = str((root / cfg["source_dir"]).resolve())
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env["PYTHONIOENCODING"] = "utf-8"
    env.pop("PYTEST_ADDOPTS", None)
    return env


def _run_probe(
    project_id: str,
    root: Path,
    probe: str,
    payload: Dict[str, Any],
    *,
    trace_a: Tuple[str, int] | None = None,
    timeout: int = 180,
) -> Dict[str, Any]:
    cfg = PROJECTS[project_id]
    if trace_a is None:
        command = [cfg["python"], str(PROBES / probe)]
        request = payload
    else:
        command = [cfg["python"], str(TRACE_HELPER)]
        request = {
            "probe": str(PROBES / probe),
            "target_file": str((root / trace_a[0]).resolve()),
            "target_line": trace_a[1],
            "payload": payload,
        }
    completed = subprocess.run(
        command,
        input=json.dumps(request, ensure_ascii=False),
        cwd=str(root),
        env=_probe_env(root, project_id),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )
    payload_out: Any
    try:
        payload_out = json.loads(completed.stdout.strip().splitlines()[-1])
    except (ValueError, IndexError):
        payload_out = {
            "probe_crash": True,
            "stdout": completed.stdout[-4000:],
            "stderr": completed.stderr[-4000:],
        }
    if trace_a is None:
        return {
            "observation": payload_out,
            "returncode": completed.returncode,
            "stderr_tail": completed.stderr[-2000:],
        }
    return {
        "observation": payload_out.get("observation"),
        "executed": payload_out.get("executed"),
        "trace_error": payload_out.get("probe_error"),
        "parse_error": payload_out.get("parse_error"),
        "returncode": completed.returncode,
        "stderr_tail": completed.stderr[-2000:],
    }


def _executable(run: Dict[str, Any]) -> bool:
    observation = run.get("observation")
    return (
        run.get("returncode") == 0
        and isinstance(observation, dict)
        and "outcome" in observation
        and not observation.get("probe_crash")
    )


def _equal(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return a.get("observation") == b.get("observation")


def _powerset(ops: Sequence[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], ...]]:
    result: List[Tuple[Dict[str, Any], ...]] = []
    for size in range(len(ops) + 1):
        result.extend(itertools.combinations(ops, size))
    return result


def _subset_ids(subset: Iterable[Dict[str, Any]]) -> List[str]:
    return sorted(op["id"] for op in subset)


def _key(subset: Iterable[Dict[str, Any]]) -> str:
    return "+".join(_subset_ids(subset)) or "EMPTY"


def _canonical_relations(values: Iterable[Iterable[str]]) -> List[List[str]]:
    return sorted([sorted(item) for item in values])


def _minimal_sufficient(
    subset: Tuple[Dict[str, Any], ...],
    universe: Sequence[Dict[str, Any]],
    masked: Dict[str, bool],
) -> bool:
    if not subset:
        return False
    rest = [op for op in universe if op not in subset]
    if not masked[_key(rest)]:
        return False
    for size in range(1, len(subset)):
        for sub in itertools.combinations(subset, size):
            sub_rest = [op for op in universe if op not in sub]
            if masked[_key(sub_rest)]:
                return False
    return True


def _minimal_breaking(
    subset: Tuple[Dict[str, Any], ...],
    exposed: Dict[str, bool],
) -> bool:
    if not subset or not exposed[_key(subset)]:
        return False
    for size in range(0, len(subset)):
        for sub in itertools.combinations(subset, size):
            if exposed[_key(sub)]:
                return False
    return True


def _build_variant(
    project_id: str,
    root: Path,
    target: Dict[str, Any],
    disabled: Sequence[Dict[str, Any]],
    remove_target: bool,
    task_id: str,
    side: str,
    subset_key: str,
) -> Path:
    destination = root / f"{side}_{subset_key.replace('+', '_')}"
    _copy_project(project_id, destination)
    if remove_target:
        _delete_line(destination, target["file"], int(target["line"]))
    for op in disabled:
        _disable_operation(destination, op)
    return destination


def _matrix(
    project_id: str,
    spec: Dict[str, Any],
    task_root: Path,
    plus_base: Path,
    minus_base: Path,
) -> Dict[str, Any]:
    target = spec["target_operation"]
    universe = spec["candidate_universe"]
    probe = spec["probe"]
    inputs = spec["inputs"]

    variants: Dict[str, Dict[str, Path]] = {
        "plus": {"EMPTY": plus_base},
        "minus": {"EMPTY": minus_base},
    }
    for subset in _powerset(universe):
        key = _key(subset)
        if not subset:
            continue
        for side in ("plus", "minus"):
            variants[side][key] = _build_variant(
                project_id, task_root, target, list(subset),
                remove_target=(side == "minus"), task_id=spec["task_id"],
                side=side, subset_key=key,
            )

    runs: Dict[str, Dict[str, Dict[str, Dict[str, Any]]]] = {
        "plus": {}, "minus": {}}
    for subset in _powerset(universe):
        key = _key(subset)
        for side in ("plus", "minus"):
            for item in inputs:
                runs[side].setdefault(item["id"], {})[key] = _run_probe(
                    project_id, variants[side][key], probe, item["payload"])

    per_input: Dict[str, Any] = {}
    for item in inputs:
        iid = item["id"]
        masked: Dict[str, bool] = {}
        exposed: Dict[str, bool] = {}
        executable: Dict[str, bool] = {}
        for subset in _powerset(universe):
            key = _key(subset)
            plus = runs["plus"][iid][key]
            minus = runs["minus"][iid][key]
            ok = _executable(plus) and _executable(minus)
            executable[key] = ok
            masked[key] = bool(
                ok and plus["observation"].get("outcome") == "return"
                and _equal(plus, minus))
            exposed[key] = bool(ok and _equal(plus, minus) is False)
        msms = [
            _subset_ids(subset) for subset in _powerset(universe)
            if _minimal_sufficient(subset, universe, masked)
        ]
        mmbs = [
            _subset_ids(subset) for subset in _powerset(universe)
            if _minimal_breaking(subset, exposed)
        ]
        per_input[iid] = {
            "role": item.get("role", "unspecified"),
            "payload": item["payload"],
            "executable": executable,
            "masked_strict": masked,
            "exposed": exposed,
            "msms": _canonical_relations(msms),
            "mmbs": _canonical_relations(mmbs),
            "plus_observations": {
                key: runs["plus"][iid][key]["observation"] for key in masked
            },
            "minus_observations": {
                key: runs["minus"][iid][key]["observation"] for key in masked
            },
        }
    return {
        "task_id": spec["task_id"],
        "project_id": project_id,
        "target_operation": target,
        "candidate_universe": universe,
        "probe": probe,
        "inputs": per_input,
        "variants": {
            side: {key: str(path) for key, path in mapping.items()}
            for side, mapping in variants.items()
        },
    }


def _parse_count(text: str, label: str) -> int:
    match = re.search(r"(\d+)\s+" + re.escape(label), text)
    return int(match.group(1)) if match else 0


def _kill_tree(pid: int) -> None:
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/F", "/T", "/PID", str(pid)], capture_output=True)
    else:
        import signal
        try:
            os.killpg(os.getpgid(pid), signal.SIGKILL)
        except OSError:
            pass


def _run_pytest(
    project_id: str,
    root: Path,
    *,
    output: str,
    nodeids: Sequence[str] | None = None,
    timeout: int = 1800,
) -> Dict[str, Any]:
    cfg = PROJECTS[project_id]
    output_dir = root.parent
    log_path = output_dir / f"{output}.log"
    xml_path = output_dir / f"{output}.junit.xml"
    for path in (log_path, xml_path):
        if path.exists():
            path.unlink()
    env = _probe_env(root, project_id)
    command = [cfg["python"], "-m", "pytest"]
    if nodeids is None:
        command.extend(list(cfg["tests"]))
    else:
        command.extend(list(nodeids))
    command.extend([
        "-q", "--disable-warnings", f"--junitxml={xml_path}",
        *list(cfg["extra_args"]),
    ])
    started = datetime.now(timezone.utc)
    process = subprocess.Popen(
        command, cwd=str(root), env=env,
        stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        text=True, encoding="utf-8", errors="replace",
    )
    timed_out = False
    try:
        stdout, stderr = process.communicate(timeout=timeout)
        returncode = process.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        _kill_tree(process.pid)
        try:
            stdout, stderr = process.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            process.kill()
            stdout, stderr = process.communicate()
        returncode = None
        stdout = stdout or ""
        stderr = stderr or ""
    duration = (datetime.now(timezone.utc) - started).total_seconds()
    log_path.write_text(
        "$ " + " ".join(command) + "\n\n--- stdout ---\n" + stdout
        + "\n--- stderr ---\n" + stderr,
        encoding="utf-8",
    )
    summary: Dict[str, int] = {
        "passed": 0, "failed": 0, "error": 0, "skipped": 0,
        "deselected": 0, "xfailed": 0,
    }
    if xml_path.exists():
        try:
            root_xml = ET.parse(xml_path).getroot()
            for case in root_xml.findall(".//testcase"):
                bad = (
                    case.find("failure") is not None
                    or case.find("error") is not None
                )
                skipped = case.find("skipped") is not None
                if bad:
                    summary["failed"] += 1
                elif skipped:
                    summary["skipped"] += 1
                else:
                    summary["passed"] += 1
        except ET.ParseError:
            pass
    for label in ("passed", "failed", "error", "skipped", "deselected",
                  "xfailed"):
        summary[label] = max(summary[label], _parse_count(stdout, label))
    return {
        "command": command,
        "returncode": returncode,
        "timed_out": timed_out,
        "duration_seconds": duration,
        "summary": summary,
        "stdout_tail": stdout[-5000:],
        "stderr_tail": stderr[-3000:],
        "log": str(log_path),
        "junit": str(xml_path),
        "success": bool(
            not timed_out and returncode == 0
            and summary["failed"] == 0 and summary["error"] == 0),
    }


def _normalized(text: str) -> str:
    # Compare Python token text, not layout: deleted blocks may be reflowed
    # across lines and the spec records the compact statement.
    return "".join(text.split())


def _check_source(
    spec: Dict[str, Any],
    project_id: str,
    plus_root: Path,
    minus_root: Path,
    project_hashes: Dict[str, str],
) -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    cfg = PROJECTS[project_id]
    target = spec["target_operation"]
    path = plus_root / target["file"]
    lines = path.read_text(encoding="utf-8").splitlines()
    line_text = lines[int(target["line"]) - 1]
    if line_text.strip() != target["code"].strip():
        errors.append(
            f"target code mismatch at {target['file']}:{target['line']}: "
            f"{line_text!r} != {target['code']!r}")
    expected_hash = project_hashes.get(project_id)
    actual_hash = _project_hash(project_id)
    if expected_hash and expected_hash != actual_hash:
        errors.append(
            f"project source hash mismatch for {project_id}: "
            f"{actual_hash} != {expected_hash}")
    diff = _tree_diff(plus_root, minus_root, cfg["source_dir"])
    if diff["only_in_plus"] or diff["only_in_minus"]:
        errors.append("P+/P- source file sets differ")
    if len(diff["changed"]) != 1:
        errors.append(
            f"expected exactly one changed source file, got "
            f"{sorted(diff['changed'])}")
    else:
        rel, detail = next(iter(diff["changed"].items()))
        if detail.get("binary"):
            errors.append(f"changed source file is binary: {rel}")
        else:
            changed_lines = detail["different_lines"]
            if changed_lines != [int(target["line"])]:
                errors.append(
                    f"P+/P- differ on lines {changed_lines}, expected "
                    f"[{target['line']}]")
            target_rel = Path(target["file"]).relative_to(
                cfg["source_dir"]).as_posix()
            if rel != target_rel:
                errors.append(
                    f"changed file {rel} != target {target_rel}")
            plus_line = detail["plus_lines"].get(int(target["line"]))
            minus_line = detail["minus_lines"].get(int(target["line"]))
            if plus_line is not None and plus_line.strip() != target["code"].strip():
                errors.append("P+ target line does not match spec code")
            if minus_line is not None and "P-: target A deleted" not in minus_line:
                errors.append("P- target line lacks the declared deletion marker")
    return diff, errors


def _check_universe(
    spec: Dict[str, Any], plus_root: Path
) -> Tuple[List[Dict[str, Any]], List[str]]:
    errors: List[str] = []
    records: List[Dict[str, Any]] = []
    target = spec["target_operation"]
    seen = set()
    for op in spec["candidate_universe"]:
        location = (
            op["file"], int(op.get("first_line", op.get("line", -1))),
            int(op.get("last_line", op.get("line", -1))),
        )
        if location in seen:
            errors.append(f"duplicate universe location: {location}")
        seen.add(location)
        if (
            op["file"] == target["file"]
            and location[1] <= int(target["line"]) <= location[2]
        ):
            errors.append(f"universe operation overlaps A: {op['id']}")
        path = plus_root / op["file"]
        lines = path.read_text(encoding="utf-8").splitlines()
        first, last = location[1], location[2]
        if first < 1 or last > len(lines):
            errors.append(f"universe line out of range: {op['id']}")
            continue
        actual = _normalized("\n".join(lines[first - 1:last]))
        expected = _normalized(op["code"])
        if actual != expected:
            errors.append(
                f"universe code mismatch for {op['id']}: {actual!r} != "
                f"{expected!r}")
        records.append({
            "id": op["id"], "file": op["file"], "first_line": first,
            "last_line": last, "code": actual, "kind": op.get("kind", "statement"),
        })
    return records, errors


def _compare_matrix(
    stored: Dict[str, Any], independent: Dict[str, Any]
) -> List[str]:
    errors: List[str] = []
    for iid, expected in stored["inputs"].items():
        actual = independent["inputs"].get(iid)
        if actual is None:
            errors.append(f"independent matrix missing input {iid}")
            continue
        for field in ("masked_strict", "exposed"):
            if expected.get(field) != actual.get(field):
                errors.append(
                    f"{iid}.{field} mismatch: stored={expected.get(field)} "
                    f"independent={actual.get(field)}")
        for field in ("msms", "mmbs"):
            left = _canonical_relations(expected.get(field, []))
            right = _canonical_relations(actual.get(field, []))
            if left != right:
                errors.append(
                    f"{iid}.{field} mismatch: stored={left} independent={right}")
    return errors


def _check_task_specific(
    task_id: str,
    spec: Dict[str, Any],
    matrix: Dict[str, Any],
) -> Tuple[Dict[str, Any], List[str]]:
    errors: List[str] = []
    detail: Dict[str, Any] = {}
    inputs = matrix["inputs"]
    masking = [
        iid for iid, data in inputs.items()
        if data["role"] == "masking"]
    exposing = [
        iid for iid, data in inputs.items()
        if data["role"] == "exposing"]
    if not masking:
        errors.append("no declared masking input")
    if not exposing:
        errors.append("no declared exposing input")
    for iid in masking:
        data = inputs[iid]
        if not data["masked_strict"].get("EMPTY"):
            errors.append(f"{iid}: EMPTY is not strictly masked")
        if not data["msms"]:
            errors.append(f"{iid}: MSMS is empty")
        if not data["mmbs"]:
            errors.append(f"{iid}: MMBS is empty")
        for relation in data["msms"]:
            key = "+".join(sorted(relation))
            if not data["exposed"].get(key):
                errors.append(f"{iid}: MSMS {relation} does not break exposure")
    for iid in exposing:
        data = inputs[iid]
        plus = data["plus_observations"].get("EMPTY")
        minus = data["minus_observations"].get("EMPTY")
        if not data["exposed"].get("EMPTY"):
            errors.append(f"{iid}: EMPTY is not exposed")
        if plus is not None and plus.get("outcome") != "return":
            errors.append(f"{iid}: P+ did not return on the exposing input")
    if task_id == "werkzeug_get_host_default_empty":
        expected = {
            "mask_host_header": "overwrite_host_header",
            "mask_server": "overwrite_server",
        }
        for iid, op_id in expected.items():
            data = inputs.get(iid, {})
            if data.get("msms") != [[op_id]] or data.get("mmbs") != [[op_id]]:
                errors.append(
                    f"{iid}: expected MSMS=MMBS=[[{op_id}]], got "
                    f"{data.get('msms')} / {data.get('mmbs')}")
        detail["two_alternative_maskers"] = expected
        detail["distinct_paths"] = (
            len({op for op in expected.values()}) == len(expected))
    if task_id == "jinja2_bytecode_cache_read":
        data = inputs.get("mask_cache_benign", {})
        if data.get("msms") != [["compile_fallback"]] or data.get(
                "mmbs") != [["compile_fallback"]]:
            errors.append(
                "mask_cache_benign: expected MSMS=MMBS=[[compile_fallback]], "
                f"got {data.get('msms')} / {data.get('mmbs')}")
        fallback_key = "compile_fallback"
        plus = data.get("plus_observations", {}).get(fallback_key, {})
        minus = data.get("minus_observations", {}).get(fallback_key, {})
        if plus.get("value") != "42":
            errors.append("jinja2 fallback-disabled P+ did not render 42")
        if minus.get("outcome") != "raise" and minus == plus:
            errors.append(
                "jinja2 fallback-disabled P- did not expose the deletion")
        detail["fallback_observations"] = {"plus": plus, "minus": minus}
    return detail, errors


def _accept_task(
    spec: Dict[str, Any],
    project_hashes: Dict[str, str],
    qualified: Dict[str, Any],
    *,
    run_suite: bool,
    run_t_task: bool,
) -> Dict[str, Any]:
    task_id = spec["task_id"]
    project_id = spec["project_id"]
    task_root = ACCEPT_ROOT / task_id
    if task_root.exists():
        shutil.rmtree(task_root)
    task_root.mkdir(parents=True)
    plus_root = task_root / "plus_base"
    minus_root = task_root / "minus_base"
    _copy_project(project_id, plus_root)
    _copy_project(project_id, minus_root)
    deletion = _delete_line(minus_root, spec["target_operation"]["file"],
                            int(spec["target_operation"]["line"]))

    checks: Dict[str, Any] = {}
    errors: List[str] = []

    diff, diff_errors = _check_source(
        spec, project_id, plus_root, minus_root, project_hashes)
    checks["source_and_single_line_diff"] = {
        "ok": not diff_errors,
        "source_hash": _project_hash(project_id),
        "changed_files": sorted(diff["changed"]),
        "errors": diff_errors,
    }
    errors.extend(diff_errors)
    checks["deletion_record"] = deletion

    universe_records, universe_errors = _check_universe(spec, plus_root)
    checks["candidate_universe_positions"] = {
        "ok": not universe_errors,
        "operations": universe_records,
        "errors": universe_errors,
    }
    errors.extend(universe_errors)

    trace_results: Dict[str, Any] = {}
    for item in spec["inputs"]:
        result = _run_probe(
            project_id, plus_root, spec["probe"], item["payload"],
            trace_a=(spec["target_operation"]["file"],
                     int(spec["target_operation"]["line"])))
        trace_results[item["id"]] = {
            "role": item.get("role"),
            "executed": result.get("executed"),
            "observation": result.get("observation"),
            "trace_error": result.get("trace_error"),
        }
        if result.get("executed") is not True:
            errors.append(f"{item['id']}: A was not observed executing")
    checks["target_execution"] = {
        "ok": all(v["executed"] is True for v in trace_results.values()),
        "by_input": trace_results,
    }

    stored_path = EVIDENCE / f"{task_id}_matrix.json"
    stored = json.loads(stored_path.read_text(encoding="utf-8"))
    independent = _matrix(
        project_id, spec, task_root, plus_root, minus_root)
    independent_path = task_root / "independent_matrix.json"
    independent_path.write_text(
        json.dumps(independent, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    matrix_errors = _compare_matrix(stored, independent)
    checks["matrix_reproduction"] = {
        "ok": not matrix_errors,
        "stored": str(stored_path),
        "inputs": {
            iid: {
                "msms": data["msms"],
                "mmbs": data["mmbs"],
                "masked_EMPTY": data["masked_strict"].get("EMPTY"),
                "exposed_EMPTY": data["exposed"].get("EMPTY"),
            }
            for iid, data in independent["inputs"].items()
        },
        "errors": matrix_errors,
    }
    errors.extend(matrix_errors)

    minimality_errors: List[str] = []
    for iid, data in independent["inputs"].items():
        if not data["masked_strict"].get("EMPTY"):
            continue
        if not data["msms"]:
            minimality_errors.append(f"{iid}: no minimal sufficient set")
        if not data["mmbs"]:
            minimality_errors.append(f"{iid}: no minimal breaking set")
        for relation in data["msms"]:
            key = "+".join(sorted(relation))
            if not data["exposed"].get(key):
                minimality_errors.append(
                    f"{iid}: MSMS {relation} does not expose when broken")
    checks["minimality"] = {
        "ok": not minimality_errors,
        "errors": minimality_errors,
        "note": (
            "All subsets of the declared U were enumerated independently; "
            "minimality is exact over that finite universe."
        ),
    }
    errors.extend(minimality_errors)

    specific_detail, specific_errors = _check_task_specific(
        task_id, spec, independent)
    checks["task_specific"] = {
        "ok": not specific_errors,
        "detail": specific_detail,
        "errors": specific_errors,
    }
    errors.extend(specific_errors)

    if run_suite:
        suite = _run_pytest(
            project_id, minus_root, output=f"{task_id}_p_minus_full")
        checks["p_minus_full_suite"] = suite
        if not suite["success"]:
            errors.append("P- applicable suite did not pass")
    else:
        checks["p_minus_full_suite"] = {"skipped": True}

    if run_t_task:
        nodeids = qualified.get(task_id, {}).get("t_task", [])
        t_task = _run_pytest(
            project_id, plus_root, output=f"{task_id}_t_task",
            nodeids=nodeids)
        checks["t_task_on_p_plus"] = t_task
        if not nodeids:
            errors.append("no frozen T_task nodeids")
        if not t_task["success"]:
            errors.append("T_task did not pass on P+")
    else:
        checks["t_task_on_p_plus"] = {"skipped": True}

    return {
        "task_id": task_id,
        "project_id": project_id,
        "project": PROJECTS[project_id]["project"],
        "version": PROJECTS[project_id]["version"],
        "verdict": "PASS" if not errors else "NEEDS_REVIEW",
        "errors": errors,
        "checks": checks,
        "independent_matrix": str(independent_path),
        "work_root": str(task_root),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--tasks", nargs="*", default=None)
    parser.add_argument("--skip-suite", action="store_true")
    parser.add_argument("--skip-t-task", action="store_true")
    args = parser.parse_args()

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    ACCEPT_ROOT.mkdir(parents=True, exist_ok=True)
    project_hashes = (
        json.loads(PROJECT_HASHES.read_text(encoding="utf-8"))
        if PROJECT_HASHES.exists() else {}
    )
    qualified_payload = (
        json.loads(QUALIFIED.read_text(encoding="utf-8"))
        if QUALIFIED.exists() else {"tasks": []}
    )
    qualified = {
        task["task_id"]: task for task in qualified_payload.get("tasks", [])
    }

    selected = args.tasks
    specs = []
    for task_dir in sorted(p for p in TASKS.iterdir() if p.is_dir()):
        spec_path = task_dir / "spec.json"
        if not spec_path.exists():
            continue
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
        if selected and spec["task_id"] not in selected:
            continue
        specs.append(spec)

    results = []
    for spec in specs:
        print("accepting", spec["task_id"], flush=True)
        result = _accept_task(
            spec, project_hashes, qualified,
            run_suite=not args.skip_suite,
            run_t_task=not args.skip_t_task,
        )
        results.append(result)
        print(" ", result["verdict"], len(result["errors"]), "errors",
              flush=True)

    report = {
        "protocol": "benchmark_real_v3_acceptance",
        "generated_utc": datetime.now(timezone.utc).isoformat(),
        "method": (
            "Independent reimplementation: own project copies, own line "
            "deletion, own probe runner, own subset enumeration and own "
            "pytest invocation.  No call to verify_task/variant_lab/run_suite."
        ),
        "task_count": len(results),
        "accepted": sum(1 for r in results if r["verdict"] == "PASS"),
        "needs_review": sum(
            1 for r in results if r["verdict"] == "NEEDS_REVIEW"),
        "tasks": results,
    }
    OUT.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "accepted": report["accepted"],
        "needs_review": report["needs_review"],
        "report": str(OUT),
    }, ensure_ascii=False, indent=2))
    return 0 if report["needs_review"] == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
