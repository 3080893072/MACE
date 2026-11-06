"""Close the two src-layout INCOMPLETE tasks without any new Qwen call.

Only the harness sys.path defect is repaired, in-memory:
  * the variant root AND <variant>/<top> (e.g. <variant>/src) are on sys.path.
  * _run_probe, a_executes and trace_run use the same corrected paths.
The frozen runner/prompt/verifier/search code is imported unchanged.
Cached Qwen responses and stats are replayed; no HTTP request is made.
"""
from __future__ import annotations

import importlib.util
import json
import io
import os
import subprocess
import sys
import tempfile
import shutil
from pathlib import Path
from types import SimpleNamespace

KIT = Path(__file__).resolve().parents[1]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from benchmark_v4_dataset.tools.sd_algorithm_pilot import SDExecutor, VENVS  # noqa: E402
from mace.paths import venv_python  # noqa: E402
from benchmark_v3_baselines.graph_search import payload_key  # noqa: E402
CIDS = ["sd_attrs_asdict_loop_m7", "sd_humanize_filesize_gnu_m5"]
CLOSURE = KIT / "runs" / "candidate_discovery_v2_1_closure"
RESULT = KIT / "results" / "MACE_candidate_discovery_v2_1_dev.json"

spec = importlib.util.spec_from_file_location(
    "cd21", KIT / "scripts" / "run_candidate_discovery_v2_1.py")
m = importlib.util.module_from_spec(spec)
spec.loader.exec_module(m)

ENV_KEYS = ("PATH", "SystemRoot", "TEMP", "TMP", "HOME", "USERPROFILE",
            "LOCALAPPDATA", "APPDATA")


def _env():
    e = {k: v for k, v in os.environ.items() if k in ENV_KEYS}
    e.update({"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
              "PYTHONHASHSEED": "0"})
    return e


class FixedSDExecutor(SDExecutor):
    def _run_probe(self, disabled, side: str) -> dict:
        key = (tuple(sorted(disabled)), side)
        cached = self._observed_all.get(key)
        if cached is not None:
            return cached
        vdir = self.variant_dir(disabled, side)
        boot = (
            "import sys, runpy\n"
            f"sys.path.insert(0, {str(vdir)!r})\n"
            f"sys.path.insert(0, {str(vdir / self.top)!r})\n"
            f"runpy.run_path({str(self.probe)!r}, run_name='__main__')\n")
        scratch = Path(tempfile.mkdtemp(prefix="sd_pilot_"))
        try:
            proc = subprocess.run(
                [str(venv_python(self.slug)),
                 "-I", "-c", boot], cwd=str(scratch), env=_env(),
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=300)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        self.probe_executions += 1
        if proc.returncode != 0:
            data = {"__probe_error__": True, "stderr": proc.stderr[-500:]}
        else:
            try:
                data = json.loads(proc.stdout.strip().splitlines()[-1])
            except Exception:  # noqa: BLE001
                data = {"__probe_error__": True, "stdout": proc.stdout[-500:]}
        self._observed_all[key] = data
        return data

    def a_executes(self, payload: dict) -> bool:
        key = payload_key(payload)
        if key in self._trace:
            return self._trace[key]
        vdir = self.variant_dir([], "plus")
        target = str((vdir / self.rel).resolve())
        boot = (
            "import json, runpy, sys\n"
            f"target = {target!r}\n"
            f"line = {self.a_line}\n"
            "hit = []\n"
            "def tr(frame, event, arg):\n"
            "    if event == 'line' and frame.f_lineno == line and "
            "frame.f_code.co_filename == target:\n"
            "        hit.append(1)\n"
            "    return tr\n"
            f"sys.path.insert(0, {str(vdir)!r})\n"
            f"sys.path.insert(0, {str(vdir / self.top)!r})\n"
            "sys.settrace(tr)\n"
            "try:\n"
            f"    runpy.run_path({str(self.probe)!r}, run_name='__main__')\n"
            "finally:\n"
            "    sys.settrace(None)\n"
            "print(json.dumps({'executed': bool(hit)}))\n")
        scratch = Path(tempfile.mkdtemp(prefix="sd_trace_"))
        try:
            proc = subprocess.run(
                [str(venv_python(self.slug)),
                 "-I", "-c", boot], cwd=str(scratch), env=_env(),
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=300)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        executed = False
        for line in reversed(proc.stdout.strip().splitlines()):
            try:
                executed = json.loads(line).get("executed") is True
                break
            except Exception:  # noqa: BLE001
                continue
        self._trace[key] = executed
        return executed


def fixed_trace_run(executor, payload: dict, side: str) -> dict:
    vdir = executor.variant_dir([], side)
    target = str((vdir / executor.rel).resolve())
    boot = (
        "import json, runpy, sys\n"
        f"target = {target!r}\n"
        "hit = []\n"
        "def tr(frame, event, arg):\n"
        "    if event == 'line' and frame.f_code.co_filename == target:\n"
        "        hit.append(frame.f_lineno)\n"
        "    return tr\n"
        f"sys.path.insert(0, {str(vdir)!r})\n"
        f"sys.path.insert(0, {str(vdir / executor.top)!r})\n"
        "sys.settrace(tr)\n"
        "try:\n"
        f"    runpy.run_path({str(executor.probe)!r}, run_name='__main__')\n"
        "finally:\n"
        "    sys.settrace(None)\n"
        "print(json.dumps({'lines': hit}))\n")
    scratch = Path(tempfile.mkdtemp(prefix="mace_trace_"))
    try:
        proc = subprocess.run(
            [str(venv_python(executor.slug)),
             "-I", "-c", boot], cwd=str(scratch), env=_env(),
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=300)
        lines = []
        for line in reversed(proc.stdout.strip().splitlines()):
            try:
                lines = list(m.extract_json(line).get("lines") or [])
                break
            except Exception:  # noqa: BLE001
                continue
        return {"side": side, "lines": lines, "returncode": proc.returncode,
                "stderr_tail": proc.stderr[-300:] if proc.stderr else ""}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)


orig = json.load(io.open(RESULT, encoding="utf-8"))
CACHE = {}
for cid in CIDS:
    raw = json.load(io.open(KIT / "runs" / "candidate_discovery_v2_1" /
                            "raw" / f"{cid}.json", encoding="utf-8"))
    CACHE[cid] = {"raw_response": raw.get("raw_response"),
                  "stats": raw.get("stats") or {},
                  "messages": raw.get("messages"),
                  "prompt_sha256": raw.get("prompt_sha256")}


class CachedQwen:
    def __init__(self, *args, **kwargs):
        pass

    def chat(self, messages, purpose=None, **kwargs):
        cid = (purpose or "").replace("cd_v2_", "")
        rec = CACHE.get(cid)
        if rec is None or not rec.get("raw_response"):
            raise RuntimeError(f"no cached response for {cid}")
        return SimpleNamespace(content=rec["raw_response"], stats=rec["stats"])


m.SDExecutor = FixedSDExecutor
m.trace_run = fixed_trace_run
m.QwenClient = CachedQwen
m.RUN = CLOSURE
m.BASE_DIR = CLOSURE / "baselines"

CLOSURE.mkdir(parents=True, exist_ok=True)
out = CLOSURE / "results.json"
sys.argv = [str(Path(__file__).name), "--tasks", *CIDS, "--out", str(out)]
rc = m.main()
if rc:
    raise SystemExit(rc)

closure = json.load(io.open(out, encoding="utf-8"))
fixed_records = {}
for cid in CIDS:
    x = closure["tasks"][cid]
    old = orig["tasks"][cid]
    x["qwen_cache_reused"] = True
    x["qwen_calls_actual"] = 0
    x["qwen_calls_reused"] = 1
    x["cached_prompt_sha256"] = CACHE[cid]["prompt_sha256"]
    x["prompt_matches_cached"] = (
        x.get("prompt_sha256") == CACHE[cid]["prompt_sha256"])
    x["cached_prompt_messages"] = CACHE[cid]["messages"]
    x["pre_closure"] = {
        "status": old.get("status"),
        "evaluation_status": old.get("evaluation_status"),
        "scoring": old.get("scoring"),
        "c0_exact": old.get("baseline", {}).get("c0_exact"),
        "note": old.get("evaluation_note"),
    }
    x["call"]["stats"] = CACHE[cid]["stats"]
    x["call"]["messages"] = x["call"].get("messages") or CACHE[cid]["messages"]
    fixed_records[cid] = x

# Keep the original prompt message alongside; the rebuilt prompt is stored in
# call.messages by the frozen runner.  The model output is the cached one.
final = json.loads(json.dumps(orig))
for cid in CIDS:
    final["tasks"][cid] = fixed_records[cid]
final.setdefault("closure", {})
final["closure"].update({
    "date_utc": "2026-11-04",
    "fixed_tasks": CIDS,
    "method": ("in-memory sys.path repair for src-layout variants; cached "
               "Qwen responses replayed, no new Qwen calls"),
    "new_qwen_calls": 0,
    "qwen_cache_reused": True,
    "prompt_matches_cached": {cid: fixed_records[cid]["prompt_matches_cached"]
                              for cid in CIDS},
})

CLOSURE.mkdir(parents=True, exist_ok=True)
(CLOSURE / "combined_pre_analysis.json").write_text(
    json.dumps(final, ensure_ascii=False, indent=2), encoding="utf-8")
print("wrote", CLOSURE / "combined_pre_analysis.json")
for cid in CIDS:
    x = fixed_records[cid]
    print(cid, "status", x["status"], "scored", x["scoring"]["masking_inputs"],
          "exact", x["scoring"]["exact"], "c0",
          x["baseline"]["c0_exact"], "prompt_match",
          x["prompt_matches_cached"])
