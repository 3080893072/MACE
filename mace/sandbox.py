"""Parent-side driver for the isolated analysis process.

Threat model
------------
The analysed program may come from an open-source repository and is therefore
untrusted.  It is executed only in a child process started with:

* ``-I`` (isolated mode: no user site-packages, no PYTHON* environment),
* a fresh empty temporary working directory,
* a scrubbed environment (no API keys, no credentials),
* a wall-clock timeout after which the process tree is killed,
* an AST whitelist plus restricted builtins inside ``mace.program``.

This is process isolation with a whitelist, not an OS-level sandbox: it does
not prevent a malicious program from reading world-readable files.  Do not
run untrusted repositories through this without a container.
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any, Dict, List, Sequence

RUNNER = Path(__file__).with_name("runner.py")


class SandboxError(RuntimeError):
    pass


def _child_env() -> Dict[str, str]:
    keep = ["PATH", "SYSTEMROOT", "TEMP", "TMP", "TMPDIR", "PYTHONIOENCODING"]
    env = {k: os.environ[k] for k in keep if k in os.environ}
    env["PYTHONIOENCODING"] = "utf-8"
    return env


def _run_child(payload: Dict[str, Any], timeout: float,
               scratch_root: Path | None) -> Dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="mace_run_", dir=str(scratch_root) if scratch_root else None) as tmp:
        tmp_path = Path(tmp)
        payload_path = tmp_path / "payload.json"
        output_path = tmp_path / "output.json"
        payload_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
        command = [sys.executable, "-I", str(RUNNER), str(payload_path), str(output_path)]
        try:
            completed = subprocess.run(
                command, cwd=str(tmp_path), env=_child_env(),
                stdin=subprocess.DEVNULL, stdout=subprocess.PIPE,
                stderr=subprocess.PIPE, timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            raise SandboxError(f"analysis exceeded {timeout:.0f}s and was killed") from None
        stdout = completed.stdout.decode("utf-8", errors="replace").strip()
        stderr = completed.stderr.decode("utf-8", errors="replace").strip()
        if not output_path.exists():
            raise SandboxError(
                f"child produced no report (exit {completed.returncode}).\n"
                f"stdout: {stdout[:800]}\nstderr: {stderr[:2000]}"
            )
        result = json.loads(output_path.read_text(encoding="utf-8"))
        if result.get("status") == "ERROR":
            raise SandboxError(f"child analysis failed: {result.get('error')}\n{result.get('traceback','')}")
        return result


def analyze(source: str, cases: Sequence[Dict[str, Any]], bundle: Dict[str, Any], *,
            arg_sorts: Dict[str, str], functions: Dict[str, Any] | None = None,
            channels: int = 1, level: str = "BOUNDED", entry: str = "program",
            timeout: float = 180.0, scratch_root: Path | None = None,
            core_logic: bool | str = False) -> Dict[str, Any]:
    """Run one bounded verification in an isolated child process."""
    payload = {
        "source": source,
        "cases": list(cases),
        "bundle": bundle,
        "arg_sorts": arg_sorts,
        "functions": functions or {},
        "channels": channels,
        "level": level,
        "entry": entry,
        "core_logic": core_logic,
    }
    return _run_child(payload, timeout, scratch_root)


def trace_cases(source: str, cases: Sequence[Dict[str, Any]], *, arg_sorts: Dict[str, str],
                entry: str = "program", timeout: float = 120.0,
                scratch_root: Path | None = None) -> Dict[str, Any]:
    """Trace both versions on the given inputs inside the isolated child."""
    payload = {"source": source, "cases": list(cases), "trace": True,
               "arg_sorts": arg_sorts, "entry": entry}
    return _run_child(payload, timeout, scratch_root)


def labels_cases(source: str, cases: Sequence[Dict[str, Any]], *, arg_sorts: Dict[str, str],
                 entry: str = "program", timeout: float = 120.0,
                 scratch_root: Path | None = None) -> Dict[str, Any]:
    """Run both versions and report, per case, whether outputs agree.

    Also returns the locals captured immediately after A in P- (the pre-state)
    and after A in P+ (the post-state).  No model and no reference guard is
    involved: the label is the verifier's own execution of the paired program.
    """
    payload = {"source": source, "cases": list(cases), "labels": True,
               "arg_sorts": arg_sorts, "entry": entry}
    return _run_child(payload, timeout, scratch_root)


def probe_vocabulary(source: str, case: Dict[str, Any], *, arg_sorts: Dict[str, str],
                     entry: str = "program", timeout: float = 120.0,
                     scratch_root: Path | None = None) -> Dict[str, Any]:
    """Names and sorts of the variables visible at A, obtained by running one case.

    Only names and sorts leave the child process -- never values -- so this
    tells the model what vocabulary exists, not what the answer is.
    """
    payload = {"source": source, "cases": [case], "probe": True,
               "arg_sorts": arg_sorts, "entry": entry}
    return _run_child(payload, timeout, scratch_root)
