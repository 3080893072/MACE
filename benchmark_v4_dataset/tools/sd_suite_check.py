"""Run each case's declared original tests against the P+ tree.

The source-derived track does not *require* the upstream suite to exercise A
(that is an A-track requirement), but the patched file must still be a
drop-in replacement.  This script copies the pristine discovery tree, writes
the recorded P+ file over the original, and runs the test paths declared in
``source_derived/test_map.json`` with the project venv.

Usage::

    python -I benchmark_v4_dataset/tools/sd_suite_check.py [--case ID ...]
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
DS = KIT / "benchmark_v4_dataset"
DISC = DS / "discovery"
SD = DS / "source_derived"
import sys as _mace_sys  # noqa: E402
if str(KIT) not in _mace_sys.path:
    _mace_sys.path.insert(0, str(KIT))
from mace.paths import venv_python, venvs_root, work_root  # noqa: E402
WORK = work_root("sd_suite")
VENVS = venvs_root()


def stage0_row(slug: str) -> dict:
    data = json.loads((DISC / "stage0" / "projects.json").read_text("utf-8"))
    for row in data["projects"]:
        if row["slug"] == slug:
            return row
    raise SystemExit(f"unknown slug {slug}")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", action="append", default=[])
    args = ap.parse_args()

    test_map = json.loads((SD / "test_map.json").read_text("utf-8"))
    cases = sorted((SD / "cases").glob("*.json"))
    if args.case:
        cases = [c for c in cases if c.stem in set(args.case)]

    WORK.mkdir(parents=True, exist_ok=True)
    summary = {}
    for case_path in cases:
        spec = json.loads(case_path.read_text("utf-8"))
        cid = spec["case_id"]
        slug = spec["base"]["slug"]
        rel = spec["base"]["file"]
        meta = stage0_row(slug)
        root = (DISC / meta["root"]).resolve()

        tree = WORK / cid
        if tree.exists():
            shutil.rmtree(tree)
        shutil.copytree(root, tree, copy_function=shutil.copy2,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc",
                                                      ".git", ".tox", ".venv"))
        patched = (SD / "evidence" / cid / "patched" / Path(rel).name)
        (tree / rel).write_text(patched.read_text("utf-8"), encoding="utf-8")

        tests = test_map.get(cid, {}).get("tests", [])
        entry = {"tests": tests}
        if tests:
            proc = subprocess.run(
                [str(venv_python(slug)), "-m", "pytest",
                 "-q", "-p", "no:cacheprovider", *tests],
                cwd=str(tree), capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=1800)
            tail = [ln for ln in proc.stdout.splitlines() if ln.strip()][-1:]
            entry["returncode"] = proc.returncode
            entry["summary"] = tail[0] if tail else ""
            entry["passed"] = proc.returncode == 0
        else:
            entry["passed"] = None
            entry["summary"] = "no original test covers this path"
        summary[cid] = entry
        print(cid, entry["passed"], entry["summary"])

    (SD / "evidence" / "original_test_suite.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    return 0 if all(v["passed"] in (True, None) for v in summary.values()) else 1


if __name__ == "__main__":
    raise SystemExit(main())
