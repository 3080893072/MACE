"""Stage 4 probe harness: deletion, subset enumeration, observation equality.

Given a candidate A, a declared finite universe U and a project-specific probe
script, this tool builds one source tree per subset S (keep S, delete A and
U \\ S), runs the probe in a fresh interpreter with PYTHONPATH pointing at that
tree, and reports which subsets reproduce P+ exactly.

The probe script must print a single JSON object mapping an input name to an
observation.  It runs outside the tree it exercises (``cwd`` is a scratch
directory) so a planted module cannot shadow stdlib imports.

Usage::

    python -I benchmark_v4_dataset/tools/stage4_probe.py \\
        --slug pygments-2.17.2 --file pygments/formatters/bbcode.py \\
        --a-line 64 --u L67:67,L70:70,L73:73 \\
        --probe benchmark_v4_dataset/discovery/stage4/probes/bbcode64.py \\
        --out benchmark_v4_dataset/discovery/stage4/bbcode64.json
"""
from __future__ import annotations

import argparse
import itertools
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
DS = KIT / "benchmark_v4_dataset"
DISC = DS / "discovery"
import sys as _mace_sys  # noqa: E402
if str(KIT) not in _mace_sys.path:
    _mace_sys.path.insert(0, str(KIT))
from mace.paths import venv_python, venvs_root, work_root  # noqa: E402
WORK = work_root("stage4_work")
VENVS = venvs_root()


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def stage0(slug: str) -> dict:
    for p in load(DISC / "stage0" / "projects.json")["projects"]:
        if p["slug"] == slug:
            return p
    raise SystemExit(f"unknown slug {slug}")


def venv_python(slug: str) -> Path:
    return venv_python(slug)


def clone_tree(src: Path, dest: Path) -> None:
    """Hardlink clone where possible; fall back to copying."""
    def link(a, b):
        try:
            os.link(a, b)
        except OSError:
            shutil.copy2(a, b)
    shutil.copytree(src, dest, copy_function=link,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc",
                                                  ".git", ".tox", ".venv"))


def delete_lines(path: Path, lines: list[int]) -> list[dict]:
    text = path.read_text(encoding="utf-8").splitlines(keepends=True)
    info = []
    for line in sorted(lines):
        original = text[line - 1]
        indent = original[:len(original) - len(original.lstrip())]
        text[line - 1] = indent + "pass  # P-: target A deleted\n"
        info.append({"line": line, "original": original.rstrip("\n"),
                     "replacement": text[line - 1].rstrip("\n")})
    path.unlink()
    path.write_text("".join(text), encoding="utf-8")
    return info


def run_probe(slug: str, root: Path, probe: Path, timeout: int = 300) -> dict:
    # ``-I`` ignores PYTHONPATH, so the variant root is inserted from inside
    # the interpreter instead of through the environment.
    scratch = Path(tempfile.mkdtemp(prefix="mace_probe_"))
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(root)!r})\n"
        f"exec(compile(open({str(probe)!r}, encoding='utf-8').read(),"
        f" {str(probe)!r}, 'exec'))\n"
    )
    proc = subprocess.run(
        [str(venv_python(slug)), "-I", "-c", code], cwd=str(scratch),
        env={**os.environ,
             "PYTHONIOENCODING": "utf-8",
             "PYTHONDONTWRITEBYTECODE": "1",
             "PYTHONHASHSEED": "0"},
        capture_output=True, text=True, encoding="utf-8", errors="replace",
        timeout=timeout)
    shutil.rmtree(scratch, ignore_errors=True)
    if proc.returncode != 0:
        return {"probe_failed": True, "returncode": proc.returncode,
                "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}
    try:
        return json.loads(proc.stdout)
    except Exception:
        return {"probe_failed": True, "returncode": 0,
                "stdout": proc.stdout[-4000:], "stderr": proc.stderr[-4000:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--slug", required=True)
    ap.add_argument("--file", required=True)
    ap.add_argument("--a-line", type=int, required=True)
    ap.add_argument("--u", required=True,
                    help="comma separated label:line pairs, e.g. L67:67,L70:70")
    ap.add_argument("--probe", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--keep-work", action="store_true")
    args = ap.parse_args()

    meta = stage0(args.slug)
    root = DISC / meta["root"]
    rel = Path(args.file)
    u = {}
    for item in args.u.split(","):
        label, line = item.split(":")
        u[label.strip()] = int(line)

    probe = Path(args.probe).resolve()
    work = WORK / (Path(args.out).stem)
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    variants = {}
    labels = sorted(u)
    for r in range(len(labels) + 1):
        for kept in itertools.combinations(labels, r):
            name = "KEEP_" + ("_".join(kept) if kept else "EMPTY")
            tree = work / name
            clone_tree(root, tree)
            deleted = [args.a_line] + [u[k] for k in labels if k not in kept]
            info = delete_lines(tree / rel, deleted)
            variants[name] = {
                "kept": list(kept),
                "deleted": deleted,
                "deletion": info,
                "tree": tree,
            }

    observations = {}
    for name, variant in variants.items():
        observations[name] = run_probe(args.slug, variant["tree"], probe)

    plus = observations["KEEP_" + "_".join(labels)]
    keys = [k for k in plus if k != "probe_failed"] if isinstance(plus, dict) else []
    if not keys:
        print(json.dumps({"error": "P+ probe failed", "plus": plus},
                         ensure_ascii=False, indent=2))
        return 1

    def same(a, b, key):
        x, y = a.get(key), b.get(key)
        return x == y

    report = {
        "slug": args.slug,
        "file": args.file,
        "A_line": args.a_line,
        "U": u,
        "source_root": str(root),
        "variants": {
            name: {k: v for k, v in variant.items() if k != "tree"}
            for name, variant in variants.items()
        },
        "observations": observations,
        "per_input": {},
    }
    for key in keys:
        mask_sets = [variant["kept"] for name, variant in variants.items()
                     if same(plus, observations[name], key)]
        minimal = [s for s in mask_sets
                   if not any(set(o) < set(s) for o in mask_sets)]
        exposed = not same(plus, observations["KEEP_EMPTY"], key)
        report["per_input"][key] = {
            "masking_sets": mask_sets,
            "minimal_masking_sets": minimal,
            "empty_kept_masks": [] in [list(s) for s in mask_sets],
            "exposed_with_universe_disabled": exposed,
        }

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n",
                   encoding="utf-8")
    if not args.keep_work:
        shutil.rmtree(work, ignore_errors=True)
    print(json.dumps({"out": str(out),
                      "per_input": report["per_input"]},
                     ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
