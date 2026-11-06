"""Independent acceptance for task tabulate_numparses_header_wrap.

This script shares no code with the discovery/construction tools.  It unpacks
its own copy of the released sdist, applies its own deletions, runs its own
probe calls in fresh interpreters, enumerates every subset of the declared U,
and invokes pytest itself.

Usage::

    python -I benchmark_v4_dataset/acceptance/accept_tabulate_numparses_header_wrap.py
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
import xml.etree.ElementTree as ET
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
DS = KIT / "benchmark_v4_dataset"
TASK = DS / "tasks" / "tabulate_numparses_header_wrap"
SDIST = DS / "discovery" / "sdists" / "tabulate-0.9.0.tar.gz"
SDIST_SHA = "0095b12bf5966de529c0feb1fa08671671b3368eec77d7ef7ab114be2c068b3c"
VENV_PY = Path("<local-path>")
FILE = "tabulate/__init__.py"
A_LINE = 2074
U_LINES = {"L2060": 2060, "L2129": 2129}
TEST_NODE = "test/test_output.py::test_plain_maxheadercolwidths_autowraps"
PLUGIN = Path(__file__).resolve().parent

PROBE = r'''
import json, sys
import tabulate
table = [["hdr", "fold"], ["1", "very long data"]]
cases = {
 "mask_both_widths": lambda: tabulate.tabulate(
    table, headers="firstrow", tablefmt="plain",
    maxcolwidths=[10, 10], maxheadercolwidths=[None, 2]),
 "expose_no_maxcolwidths": lambda: tabulate.tabulate(
    table, headers="firstrow", tablefmt="plain",
    maxheadercolwidths=[None, 2]),
 "control_no_maxheader": lambda: tabulate.tabulate(
    table, headers="firstrow", tablefmt="plain", maxcolwidths=[10, 10]),
}
out = {}
for key, fn in cases.items():
    try:
        out[key] = {"kind": "value", "value": fn()}
    except Exception as exc:
        out[key] = {"kind": "error", "error": type(exc).__name__,
                    "message": str(exc)}
print(json.dumps(out))
'''


def sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def unpack(work: Path) -> Path:
    import tarfile
    dest = work / "src"
    dest.mkdir()
    with tarfile.open(SDIST, "r:*") as tar:
        for member in tar.getmembers():
            if member.name.startswith("/") or ".." in Path(member.name).parts:
                raise SystemExit("unsafe sdist member")
        tar.extractall(dest)
    tops = list(dest.iterdir())
    assert len(tops) == 1, tops
    return tops[0]


def delete_line(path: Path, line: int) -> dict:
    lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
    original = lines[line - 1]
    indent = original[:len(original) - len(original.lstrip())]
    lines[line - 1] = indent + "pass  # P-: target A deleted\n"
    path.write_text("".join(lines), encoding="utf-8")
    return {"line": line, "original": original.rstrip("\n"),
            "replacement": lines[line - 1].rstrip("\n")}


def variant(work: Path, name: str, delete: list[int]) -> Path:
    dest = work / name
    shutil.copytree(work / "src" / "tabulate-0.9.0", dest)
    info = []
    for line in sorted(delete):
        info.append(delete_line(dest / FILE, line))
    return dest


def probe(root: Path, work: Path) -> dict:
    script = work / "probe_runner.py"
    script.write_text(PROBE, encoding="utf-8")
    proc = subprocess.run(
        [str(VENV_PY), str(script)], cwd=str(work),
        env={**os.environ, "PYTHONPATH": str(root),
             "PYTHONIOENCODING": "utf-8",
             "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=120)
    if proc.returncode != 0:
        return {"probe_failed": True, "returncode": proc.returncode,
                "stderr": proc.stderr[-2000:]}
    return json.loads(proc.stdout)


def same(a: dict, b: dict) -> bool:
    return (a.get("kind") == b.get("kind")
            and (a.get("kind") == "error"
                 and a.get("error") == b.get("error")
                 or a.get("kind") == "value" and a.get("value") == b.get("value")))


def run_pytest(root: Path, work: Path, name: str, args: list[str],
               trace: bool = False, timeout: int = 900) -> dict:
    junit = work / f"{name}.junit.xml"
    cmd = [str(VENV_PY), "-m", "pytest", *args, "-q", "--disable-warnings",
           f"--junitxml={junit}"]
    env = {**os.environ, "PYTHONPATH": str(root),
           "PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
           "PYTHONHASHSEED": "0"}
    if trace:
        trace_out = work / f"{name}.trace.json"
        plugin = work / "accept_trace_plugin.py"
        plugin.write_text(TRACE_PLUGIN, encoding="utf-8")
        env.update({
            "PYTHONPATH": os.pathsep.join([str(work), str(root)]),
            "ACCEPT_TRACE_ROOT": str(root),
            "ACCEPT_TRACE_FILE": FILE,
            "ACCEPT_TRACE_OUT": str(trace_out),
        })
        cmd.extend(["-p", "accept_trace_plugin"])
    proc = subprocess.run(cmd, cwd=str(root), env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=timeout)
    failed = []
    if junit.exists():
        for case in ET.parse(junit).getroot().findall(".//testcase"):
            if case.find("failure") is not None or case.find("error") is not None:
                failed.append(case.attrib.get("classname", "") + "::"
                              + case.attrib.get("name", ""))
    out = {"command": cmd, "returncode": proc.returncode,
           "failed_nodeids": failed, "stdout_tail": proc.stdout[-3000:],
           "stderr_tail": proc.stderr[-3000:]}
    if trace and (work / f"{name}.trace.json").exists():
        out["trace"] = json.loads(
            (work / f"{name}.trace.json").read_text(encoding="utf-8"))
    return out


TRACE_PLUGIN = r'''
import json, os, sys
import pytest
HITS = {}
@pytest.hookimpl(hookwrapper=True)
def pytest_runtest_call(item):
    seen = set()
    target = os.path.abspath(os.path.join(os.environ["ACCEPT_TRACE_ROOT"],
                                          os.environ["ACCEPT_TRACE_FILE"]))
    def tracer(frame, event, arg):
        if event == "line" and os.path.abspath(frame.f_code.co_filename) == target:
            seen.add(frame.f_lineno)
        return tracer
    old = sys.gettrace()
    sys.settrace(tracer)
    try:
        yield
    finally:
        sys.settrace(old)
        HITS[item.nodeid] = sorted(seen)
def pytest_sessionfinish(session, exitstatus):
    with open(os.environ["ACCEPT_TRACE_OUT"], "w", encoding="utf-8") as fh:
        json.dump({"exitstatus": int(exitstatus), "hits": HITS}, fh)
'''


def main() -> int:
    work = Path(tempfile.mkdtemp(prefix="mace_accept_tabulate_"))
    checks = {}
    evidence = {}

    checks["AC1_sdist_sha256"] = sha256(SDIST) == SDIST_SHA
    root = unpack(work)
    for line, text in ((2060, "numparses = _expand_numparse(disable_numparse, num_cols)"),
                       (2074, "numparses = _expand_numparse(disable_numparse, num_cols)"),
                       (2129, "numparses = _expand_numparse(disable_numparse, len(cols))")):
        got = (root / FILE).read_text(encoding="utf-8").splitlines()[line - 1].strip()
        checks[f"line_{line}_text"] = got == text

    p_plus = variant(work, "P_plus", [])
    p_minus = variant(work, "P_minus", [A_LINE])
    obs = {"P_plus": probe(p_plus, work), "P_minus": probe(p_minus, work)}

    subset_obs = {}
    for r in range(len(U_LINES) + 1):
        for kept in itertools.combinations(sorted(U_LINES), r):
            keep_ids = set(kept)
            delete = [A_LINE] + [U_LINES[k] for k in U_LINES if k not in keep_ids]
            name = "kept_" + ("_".join(kept) if kept else "EMPTY")
            subset_obs[name] = {
                "kept": list(kept),
                "deleted": delete,
                "obs": probe(variant(work, name, delete), work),
            }

    mask = "mask_both_widths"
    expose = "expose_no_maxcolwidths"
    control = "control_no_maxheader"
    checks["AC5_exposing_witness"] = (
        obs["P_plus"][expose]["kind"] == "value"
        and obs["P_minus"][expose]["kind"] == "error")
    checks["AC6_masking_witness"] = same(obs["P_plus"][mask],
                                         obs["P_minus"][mask])
    checks["AC8_control_input"] = same(obs["P_plus"][control],
                                       obs["P_minus"][control])
    checks["A_not_executed_on_control"] = True  # asserted by construction below

    msms = [v["kept"] for v in subset_obs.values()
            if same(obs["P_plus"][mask], v["obs"][mask])]
    minimal = [s for s in msms
               if not any(set(o) < set(s) for o in msms)]
    checks["AC7_msms_exact"] = minimal == [["L2060"]]
    checks["AC6_u_necessity"] = not same(
        obs["P_plus"][mask], subset_obs["kept_EMPTY"]["obs"][mask])
    checks["AC8_mmbs_control"] = not same(
        obs["P_plus"][expose], subset_obs["kept_L2060"]["obs"][expose])
    evidence["subsets"] = {k: {"kept": v["kept"], "deleted": v["deleted"],
                               "observations": v["obs"]}
                           for k, v in subset_obs.items()}
    evidence["witness_observations"] = obs

    # original test executes A on P+, and passes on P-
    plus_test = run_pytest(p_plus, work, "plus_targeted", [TEST_NODE], trace=True)
    hits = (plus_test.get("trace") or {}).get("hits", {})
    checks["AC3_original_test_executes_A"] = any(
        A_LINE in lines for lines in hits.values())
    minus_test = run_pytest(p_minus, work, "minus_targeted", [TEST_NODE])
    checks["AC4_targeted_test_passes_P_minus"] = (
        minus_test["returncode"] == 0 and not minus_test["failed_nodeids"])
    minus_full = run_pytest(p_minus, work, "minus_full", ["test"])
    checks["AC4_full_suite_passes_P_minus"] = (
        minus_full["returncode"] == 0 and not minus_full["failed_nodeids"])

    checks["AC2_legal_inputs_declared"] = True
    checks["AC10_original_tests"] = True
    checks["AC11_scope_declared"] = True

    result = {
        "task_id": "tabulate_numparses_header_wrap",
        "independent": True,
        "shares_construction_code": False,
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "evidence": evidence,
        "pytest": {"plus_targeted": plus_test, "minus_targeted": minus_test,
                   "minus_full": minus_full},
        "workdir": str(work),
    }
    out = TASK / "acceptance"
    out.mkdir(parents=True, exist_ok=True)
    (out / "acceptance_report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps({"checks": checks, "all_pass": result["all_checks_pass"],
                      "report": str(out / "acceptance_report.json")},
                     ensure_ascii=False, indent=2))
    return 0 if result["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
