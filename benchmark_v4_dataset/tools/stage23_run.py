"""Stage 2/3 dynamic validation for the broad DISCOVERY pool.

Stage 2: run each project's original suite under a line tracer and record,
for every candidate A, the original tests that execute it.

Stage 3: delete A (single-line ``pass  # P-: target A deleted``) in an
isolated copy, rerun exactly those tests, and -- only if they survive -- the
applicable full suite.  Budgeted; every candidate gets a checkpoint.

This tool does not import the candidate package in the controller and never
touches HELDOUT_BROAD.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

KIT = Path(__file__).resolve().parents[2]
DS = KIT / "benchmark_v4_dataset" / "discovery"
SOURCES = DS / "sources"
import sys as _mace_sys  # noqa: E402
if str(KIT) not in _mace_sys.path:
    _mace_sys.path.insert(0, str(KIT))
from mace.paths import host_python, venv_python, venvs_root, work_root  # noqa: E402
WORK = work_root("broad_work")
VENVS = venvs_root()
STAGE0 = DS / "stage0" / "projects.json"
STAGE1 = DS / "stage1" / "candidates_static.json"
OUT = DS / "stage2_3"
PLUGIN_ROOT = KIT

CPU_TIMEOUT_TARGETED = 180
CPU_TIMEOUT_FULL = 1200
MAX_TARGETED = 60
MAX_FULL = 20


def load_json(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def stage0_map() -> dict:
    return {p["slug"]: p for p in load_json(STAGE0)["projects"]}


def project_row(slug: str) -> dict:
    return next(p for p in load_json(
        DS / "manifest" / "source_registry.json")["projects"]
        if p["slug"] == slug)


def venv_python(slug: str) -> Path:
    return venv_python(slug)


def source_root(slug: str) -> Path:
    meta = stage0_map()[slug]
    return DS / meta["root"]


def run(command: list[str], cwd: Path, env: dict | None = None,
        timeout: int = 600) -> dict:
    started = time.time()
    proc = subprocess.Popen(command, cwd=str(cwd), env=env,
                            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                            text=True, encoding="utf-8", errors="replace")
    timed_out = False
    try:
        stdout, stderr = proc.communicate(timeout=timeout)
        rc = proc.returncode
    except subprocess.TimeoutExpired:
        timed_out = True
        if os.name == "nt":
            subprocess.run(["taskkill", "/F", "/T", "/PID", str(proc.pid)],
                           capture_output=True)
        else:
            proc.kill()
        try:
            stdout, stderr = proc.communicate(timeout=30)
        except subprocess.TimeoutExpired:
            proc.kill()
            stdout, stderr = proc.communicate()
        rc = None
    return {
        "command": command,
        "returncode": rc,
        "timed_out": timed_out,
        "stdout": (stdout or "")[-20000:],
        "stderr": (stderr or "")[-20000:],
        "seconds": round(time.time() - started, 2),
    }


# ------------------------------------------------------------------ env
def cmd_env(slug: str) -> int:
    root = source_root(slug)
    vpy = venv_python(slug)
    VENVS.mkdir(parents=True, exist_ok=True)
    if not vpy.exists():
        r = run([host_python(), "-m", "venv", str(VENVS / slug)], KIT,
                timeout=300)
        if r["returncode"] != 0:
            print(json.dumps(r, indent=2))
            return 1
    steps = []
    r = run([str(vpy), "-m", "pip", "install", "-q", "wheel",
             "pytest==7.4.0"], KIT, timeout=600)
    steps.append({"step": "bootstrap", **r})
    # runtime + build: prefer isolated builds; fall back to installing the
    # common PEP 517 backends and building without isolation.
    r = run([str(vpy), "-m", "pip", "install", "-q", "-e", str(root)], KIT,
            timeout=900)
    steps.append({"step": "install_project", **r})
    if r["returncode"] != 0:
        run([str(vpy), "-m", "pip", "install", "-q", "setuptools", "wheel",
             "hatchling", "flit_core", "setuptools_scm", "poetry-core"],
            KIT, timeout=600)
        r = run([str(vpy), "-m", "pip", "install", "-q", "-e", str(root),
                 "--no-build-isolation"], KIT, timeout=900)
        steps.append({"step": "install_project_no_isolation", **r})
    installed = r["returncode"] == 0
    # test extra, if declared
    extra = _pick_extra(root)
    if installed and extra:
        r = run([str(vpy), "-m", "pip", "install", "-q", "-e",
                 f"{root}[{extra}]"], KIT, timeout=900)
        steps.append({"step": f"install_extra_{extra}", **r})
    if not installed:
        for req in ("test-requirements.txt", "requirements-test.txt",
                    "requirements/test.txt", "tests/requirements.txt"):
            path = root / req
            if path.exists():
                r = run([str(vpy), "-m", "pip", "install", "-q", "-r",
                         str(path)], KIT, timeout=900)
                steps.append({"step": f"install_{req}", **r})
    freeze = run([str(vpy), "-m", "pip", "freeze"], KIT, timeout=120)
    payload = {
        "slug": slug,
        "root": str(root),
        "python": str(vpy),
        "extra": extra,
        "installed": installed,
        "steps": steps,
        "freeze": freeze["stdout"].splitlines(),
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{slug}.env.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps({"slug": slug, "installed": installed, "extra": extra,
                      "python": str(vpy),
                      "steps": [(s["step"], s["returncode"]) for s in steps]},
                     indent=2))
    return 0 if installed else 1


def _pick_extra(root: Path) -> str | None:
    pyproject = root / "pyproject.toml"
    if not pyproject.exists():
        return None
    try:
        import tomllib
        data = tomllib.loads(pyproject.read_text(encoding="utf-8"))
    except Exception:
        return None
    extras = data.get("project", {}).get("optional-dependencies", {})
    for name in ("test", "testing", "tests"):
        if name in extras:
            return name
    return None


# ------------------------------------------------------------------ plus
def cmd_plus(slug: str, limit_files: int = 0) -> int:
    meta = stage0_map()[slug]
    root = source_root(slug)
    work = WORK / f"{slug}_plus"
    if work.exists():
        shutil.rmtree(work)
    shutil.copytree(root, work, ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", ".git", ".tox", ".venv"))
    cands = [c for c in load_json(STAGE1)["candidates"]
             if c["project_id"] == slug]
    files = sorted({c["file"] for c in cands})
    if limit_files:
        files = files[:limit_files]
    trace_root = WORK / f"{slug}_trace"
    trace_root.mkdir(parents=True, exist_ok=True)
    trace_file = trace_root / "plus.trace.json"
    junit = trace_root / "plus.junit.xml"
    log = trace_root / "plus.log"
    env = os.environ.copy()
    env["PYTHONPATH"] = os.pathsep.join(
        [str(PLUGIN_ROOT), str((work / _source_dir(meta)).resolve())])
    env["V3_TRACE_ROOT"] = str(work.resolve())
    env["V3_TRACE_FILES"] = "\n".join(files)
    env["V3_TRACE_OUT"] = str(trace_file.resolve())
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PYTHONHASHSEED"] = "0"
    env.pop("PYTEST_ADDOPTS", None)
    tests = _test_args(meta, work)
    command = [str(venv_python(slug)), "-m", "pytest", *tests,
               *_deselect(slug), *_ignore(slug), "-q", "--disable-warnings",
               "-W", "ignore::pytest.PytestUnknownMarkWarning",
               f"--junitxml={junit}",
               "-p", "benchmark_real_v3.trace_plugin"]
    r = run(command, work, env, timeout=CPU_TIMEOUT_FULL)
    log.write_text("$ " + " ".join(command) + "\n\n--- stdout ---\n"
                   + r["stdout"] + "\n--- stderr ---\n" + r["stderr"],
                   encoding="utf-8")
    summary = _summary(trace_file, junit)
    payload = {"slug": slug, "returncode": r["returncode"],
               "seconds": r["seconds"], "summary": summary,
               "trace": str(trace_file), "log": str(log),
               "files_traced": len(files), "command": command}
    (trace_root / "plus.summary.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps({k: payload[k] for k in
                      ("slug", "returncode", "seconds", "summary",
                       "files_traced")}, indent=2))
    return 0


def _source_dir(meta: dict) -> str:
    # stage0 packages are project-relative; venv import path is the tree root
    # unless the project uses src/ layout.
    pkgs = meta.get("packages") or []
    if pkgs and all(p.startswith("src/") for p in pkgs):
        return "src"
    return "."


def _test_args(meta: dict, work: Path) -> list[str]:
    roots = [r for r in meta.get("test_roots", []) if (work / r).exists()]
    if roots:
        return roots
    return ["."]


def _deselect(slug: str) -> list[str]:
    """Per-project pre-existing failures, recorded in exclusions.json."""
    path = DS / "stage2_3" / "exclusions.json"
    if not path.exists():
        return []
    data = load_json(path)
    return [f"--deselect={nodeid}" for nodeid in data.get(slug, [])]


def _ignore(slug: str) -> list[str]:
    """Paths that fail at *collection* (missing optional dep / submodule).

    ``--deselect`` runs too late for a collection error, so these need
    ``--ignore``.  Recorded separately in exclusions.json under
    ``__ignore__`` and never counted as deletion detections.
    """
    path = DS / "stage2_3" / "exclusions.json"
    if not path.exists():
        return []
    data = load_json(path)
    return [f"--ignore={p}" for p in data.get("__ignore__", {}).get(slug, [])]


def _summary(trace_file: Path, junit: Path) -> dict:
    if not trace_file.exists():
        return {"reports": 0, "outcomes": {}, "failed_nodeids": []}
    data = load_json(trace_file)
    reports = data.get("reports", {})
    outcomes = Counter(r.get("outcome") for r in reports.values())
    return {
        "reports": len(reports),
        "outcomes": dict(outcomes),
        "failed_nodeids": sorted(k for k, v in reports.items()
                                 if v.get("outcome") in ("failed", "error"))[:50],
        "hit_tests": len(data.get("hits", {})),
    }


# ------------------------------------------------------------------ screen
def _delete_line(path: Path, line: int) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    original = lines[line - 1]
    indent = original[:len(original) - len(original.lstrip())]
    lines[line - 1] = indent + "pass  # P-: target A deleted\n"
    path.write_text("".join(lines), encoding="utf-8")
    return {"original_line": original.rstrip("\n"),
            "replacement": lines[line - 1].rstrip("\n")}


def _priority(c: dict) -> tuple:
    s = c["static_shape"]
    return (0 if (s["in_loop"] or s["in_try"] or s["in_if"]) else 1,
            1 if s["read_before_later_write"] else 0,
            0 if s["later_write_reads_A"] else 1,
            -c["later_count"], -c["target_A"]["line"])


def _diversify(items: list[dict], cap: int) -> list[dict]:
    """Keep at most ``cap`` candidates per source file.

    Without this, one unrolled/generated file (e.g. passlib's blowfish
    ``unrolled.py``) supplies dozens of top-ranked rows and starves the
    rest of the project.  This only changes *which* candidates get the
    targeted budget; it does not touch any acceptance rule.
    """
    if cap <= 0:
        return items
    seen: dict[str, int] = defaultdict(int)
    out = []
    for c in items:
        rel = c["file"]
        if seen[rel] >= cap:
            continue
        seen[rel] += 1
        out.append(c)
    return out


def cmd_screen(slug: str, budget_targeted: int = MAX_TARGETED,
               budget_full: int = MAX_FULL, max_per_file: int = 3) -> int:
    meta = stage0_map()[slug]
    cands = [c for c in load_json(STAGE1)["candidates"]
             if c["project_id"] == slug]
    trace_file = WORK / f"{slug}_trace" / "plus.trace.json"
    if not trace_file.exists():
        raise SystemExit(f"missing trace for {slug}: run plus first")
    trace = load_json(trace_file)
    hits = trace.get("hits", {})
    # line -> tests
    by_line: dict[tuple[str, int], list[str]] = defaultdict(list)
    for nodeid, files in hits.items():
        for rel, lines in files.items():
            for line in lines:
                by_line[(rel, int(line))].append(nodeid)
    rows = []
    for c in cands:
        tests = sorted(set(by_line.get((c["file"], c["target_A"]["line"]), [])))
        c = dict(c)
        c["p_plus_hit_tests"] = tests
        c["p_plus_hit_test_count"] = len(tests)
        s = c["static_shape"]
        if not tests:
            c["stage2"] = "NO_ORIGINAL_TEST_EXECUTES_A"
            c["status"] = "SCREENED_REJECT_NO_A_EXECUTION"
        elif not (s["read_before_later_write"] or s["later_write_reads_A"]):
            c["stage2"] = "A_EXECUTED_BUT_STATIC_DEAD_STORE"
            c["status"] = "SCREENED_REJECT_DEAD_BEFORE_READ"
        else:
            c["stage2"] = "A_EXECUTED_WITH_LOCAL_USE"
            c["status"] = "STATIC_ELIGIBLE"
        rows.append(c)

    signals = {}
    sig_path = DS / "stage3_5" / "recompute_signals.json"
    if sig_path.exists():
        signals = {r["candidate_id"]: r
                   for r in load_json(sig_path)["candidates"]}

    def rank_key(c):
        score = signals.get(c["candidate_id"], {}).get("score", 0)
        return (-score, *_priority(c))

    eligible = sorted([c for c in rows if c["status"] == "STATIC_ELIGIBLE"],
                      key=rank_key)
    eligible = _diversify(eligible, max_per_file)
    selected = eligible[:budget_targeted]
    prev: dict[str, dict] = {}
    prev_path = OUT / f"{slug}.screen.json"
    if prev_path.exists():
        prev = {c["candidate_id"]: c
                for c in load_json(prev_path).get("candidates", [])}
        rows = [prev.get(c["candidate_id"], c) for c in rows]
        selected = [c for c in selected
                    if "stage3" not in prev.get(c["candidate_id"], {})]
    root = source_root(slug)
    base = WORK / f"{slug}_minus"
    if base.exists():
        shutil.rmtree(base)
    shutil.copytree(root, base, ignore=shutil.ignore_patterns(
        "__pycache__", "*.pyc", ".git", ".tox", ".venv"))
    vpy = venv_python(slug)
    originals = {}
    targeted = sum(1 for c in prev.values() if c.get("targeted_minus"))
    full = sum(1 for c in prev.values() if c.get("full_minus"))
    for index, c in enumerate(selected):
        path = base / c["file"]
        if c["file"] not in originals:
            originals[c["file"]] = path.read_bytes()
        path.write_bytes(originals[c["file"]])
        c["deletion"] = _delete_line(path, c["target_A"]["line"])
        nodeids = c["p_plus_hit_tests"]
        select_file = WORK / f"{slug}_trace" / f"select_{index:04d}.txt"
        select_file.write_text("\n".join(nodeids) + "\n", encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = os.pathsep.join(
            [str(PLUGIN_ROOT), str((base / _source_dir(meta)).resolve())])
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONHASHSEED"] = "0"
        env["V3_SELECT_FILE"] = str(select_file)
        env.pop("PYTEST_ADDOPTS", None)
        files = sorted({n.split("::", 1)[0] for n in nodeids})
        if sum(len(f) + 1 for f in files) > 20000:
            # Windows limits the whole command line; collecting the suite is
            # slower but keeps the invocation valid.
            files = _test_args(meta, base)
        junit = WORK / f"{slug}_trace" / f"minus_{index:04d}.junit.xml"
        command = [str(vpy), "-m", "pytest", *files,
                   *_deselect(slug), *_ignore(slug), "-q", "--disable-warnings",
                   "-W", "ignore::pytest.PytestUnknownMarkWarning",
                   f"--junitxml={junit}",
                   "-p", "benchmark_real_v3.select_plugin"]
        r = run(command, base, env, timeout=CPU_TIMEOUT_TARGETED)
        targeted += 1
        c["targeted_minus"] = {k: r.get(k) for k in
                               ("returncode", "timed_out", "seconds",
                                "stdout", "stderr")}
        c["targeted_minus"]["failed_nodeids"] = _failed(junit)
        if (r["returncode"] != 0 or r.get("timed_out")
                or c["targeted_minus"]["failed_nodeids"]):
            c["stage3"] = "TARGETED_TEST_DETECTS_DELETION"
            c["status"] = "SCREENED_REJECT_TEST_DETECTS_DELETION"
            path.write_bytes(originals[c["file"]])
            continue
        c["stage3"] = "TARGETED_TESTS_SURVIVE"
        if full >= budget_full:
            c["status"] = "FULL_SUITE_NOT_RUN_BUDGET"
            path.write_bytes(originals[c["file"]])
            continue
        junit_full = WORK / f"{slug}_trace" / f"full_{index:04d}.junit.xml"
        command = [str(vpy), "-m", "pytest", *_test_args(meta, base),
                   *_deselect(slug), *_ignore(slug), "-q", "--disable-warnings",
                   "-W", "ignore::pytest.PytestUnknownMarkWarning",
                   f"--junitxml={junit_full}"]
        rf = run(command, base, env, timeout=CPU_TIMEOUT_FULL)
        full += 1
        c["full_minus"] = {k: rf.get(k) for k in
                           ("returncode", "timed_out", "seconds",
                            "stdout", "stderr")}
        c["full_minus"]["failed_nodeids"] = _failed(junit_full)
        if (rf["returncode"] != 0 or rf.get("timed_out")
                or c["full_minus"]["failed_nodeids"]):
            c["stage3"] = "FULL_SUITE_DETECTS_DELETION"
            c["status"] = "PROJECT_SUITE_DETECTS_DELETION"
        else:
            c["stage3"] = "FULL_SUITE_SURVIVES"
            c["status"] = "TEST_SURVIVING_DELETION"
        path.write_bytes(originals[c["file"]])
        print(slug, index, c["candidate_id"], c["status"])

    counts = Counter(c["status"] for c in rows)
    payload = {
        "slug": slug,
        "budget": {"targeted": budget_targeted, "full": budget_full,
                   "targeted_used": targeted, "full_used": full},
        "counts": dict(counts),
        "candidates": rows,
    }
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / f"{slug}.screen.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps({"slug": slug, "counts": dict(counts),
                      "targeted_used": targeted, "full_used": full},
                     indent=2))
    return 0


def _failed(junit: Path) -> list[str]:
    if not junit.exists():
        return []
    import xml.etree.ElementTree as ET
    root = ET.parse(junit).getroot()
    out = []
    for case in root.findall(".//testcase"):
        if case.find("failure") is not None or case.find("error") is not None:
            out.append(case.attrib.get("classname", "") + "::"
                       + case.attrib.get("name", ""))
    return sorted(out)[:50]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("stage", choices=["env", "plus", "screen"])
    parser.add_argument("slug")
    parser.add_argument("--targeted", type=int, default=MAX_TARGETED)
    parser.add_argument("--full", type=int, default=MAX_FULL)
    parser.add_argument("--max-per-file", type=int, default=3)
    args = parser.parse_args()
    if args.stage == "env":
        return cmd_env(args.slug)
    if args.stage == "plus":
        return cmd_plus(args.slug)
    return cmd_screen(args.slug, args.targeted, args.full,
                      getattr(args, "max_per_file", 3))


if __name__ == "__main__":
    raise SystemExit(main())
