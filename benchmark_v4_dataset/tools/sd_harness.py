"""Source-derived (SD) case harness.

A *case* is a real upstream file plus a researcher-written patch that adds
compensating operations around a real target statement A.  The harness:

1. verifies the upstream file still matches the recorded A line;
2. applies the patch (blocks are delimited by ``# SD:U:<id>:begin/end`` and
   may be anchored anywhere in the file);
3. builds the P+ tree, the P- tree and one tree per kept-subset S of the
   declared U (deleting A and every operation in U \\ S);
4. runs the case probe in a fresh interpreter with the variant tree first on
   ``sys.path``;
5. enumerates, per declared input, every subset that reproduces the P+
   observation, derives the minimal sufficient masking sets (MSMS) and the
   minimal break sets (MMBS), and records the exposing witness (P- vs P+).

Line numbers of A are preserved in the delivered patch: blocks are inserted
at explicit anchors and never replace the A line itself.  A itself is only
ever replaced by an equal-indentation ``pass  # P-: target A deleted``.

Usage::

    python -I benchmark_v4_dataset/tools/sd_harness.py \\
        --case benchmark_v4_dataset/source_derived/cases/<case>.json
"""
from __future__ import annotations

import argparse
import difflib
import hashlib
import itertools
import json
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
DS = KIT / "benchmark_v4_dataset"
DISC = DS / "discovery"
SD = DS / "source_derived"
import sys as _mace_sys  # noqa: E402
if str(KIT) not in _mace_sys.path:
    _mace_sys.path.insert(0, str(KIT))
from mace.paths import venv_python, venvs_root, work_root  # noqa: E402
WORK = work_root("sd_work")
VENVS = venvs_root()

BEGIN = "# SD:U:{id}:begin"
END = "# SD:U:{id}:end"


def load(path: Path):
    return json.loads(path.read_text(encoding="utf-8"))


def stage0_row(slug: str) -> dict:
    for row in load(DISC / "stage0" / "projects.json")["projects"]:
        if row["slug"] == slug:
            return row
    raise SystemExit(f"unknown slug {slug}")


def venv_python(slug: str) -> Path:
    return venv_python(slug)


def clone_tree(src: Path, dest: Path) -> None:
    # Never hardlink: variant files are rewritten in place and a hardlink
    # would mutate the pristine upstream tree.
    shutil.copytree(src, dest, copy_function=shutil.copy2,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc",
                                                  ".git", ".tox", ".venv"))


def source_dir(meta: dict) -> Path:
    root = DISC / meta["root"]
    packages = meta.get("packages") or []
    if packages:
        first = Path(packages[0])
        if len(first.parts) > 1:
            return (root / first.parent).resolve()
    return root.resolve()


def verify_A(text: list[str], spec: dict) -> None:
    base = spec["base"]
    line = text[base["A_line"] - 1]
    if line.rstrip("\n") != base["A_code"].rstrip("\n"):
        raise SystemExit(
            f"A line mismatch at {base['file']}:{base['A_line']}\n"
            f"  expected: {base['A_code']!r}\n  found:    {line.rstrip()!r}")


def _indent_at(text: list[str], anchor: int, block: dict) -> int:
    if "indent" in block:
        return int(block["indent"])
    if anchor <= 0:
        raise SystemExit(f"block {block['id']} needs an explicit indent")
    line = text[anchor - 1]
    return len(line) - len(line.lstrip())


def apply_patch(text: list[str], spec: dict) -> tuple[list[str], int]:
    """Insert every block at its anchor.  Returns (text, A index)."""
    a_line = spec["base"]["A_line"]
    groups: dict[int, list[dict]] = {}
    for block in spec["patch"]:
        groups.setdefault(int(block["after_line"]), []).append(block)

    out = list(text)
    for anchor in sorted(groups, reverse=True):
        ins: list[str] = []
        for block in groups[anchor]:
            indent = _indent_at(text, anchor, block)
            ins.append(" " * indent + BEGIN.format(id=block["id"]) + "\n")
            ins.extend(" " * indent + line + "\n" for line in block["lines"])
            ins.append(" " * indent + END.format(id=block["id"]) + "\n")
        out[anchor:anchor] = ins

    shift = 0
    for anchor, blocks in groups.items():
        if anchor < a_line:
            shift += sum(len(b["lines"]) + 2 for b in blocks)
    return out, a_line - 1 + shift


def find_ranges(text: list[str], u_ids: list[str]) -> dict:
    ranges = {}
    for bid in u_ids:
        begin_s, end_s = BEGIN.format(id=bid), END.format(id=bid)
        begin = next(i for i, line in enumerate(text)
                     if line.strip() == begin_s)
        end = next(i for i, line in enumerate(text)
                   if line.strip() == end_s)
        ranges[bid] = {"begin": begin, "end": end}
    return ranges


def delete_A(text: list[str], a_index: int) -> list[str]:
    out = list(text)
    original = out[a_index]
    indent = original[: len(original) - len(original.lstrip())]
    out[a_index] = indent + "pass  # P-: target A deleted\n"
    return out


def delete_block(text: list[str], rng: dict) -> list[str]:
    out = list(text)
    begin, end = rng["begin"], rng["end"]
    indent = out[begin][: len(out[begin]) - len(out[begin].lstrip())]
    for i in range(begin, end + 1):
        out[i] = ""
    out[begin] = indent + "pass  # P-: U operation disabled\n"
    return out


def write_variant(dest: Path, rel: str, text: list[str]) -> None:
    (dest / rel).write_text("".join(text), encoding="utf-8")


def run_probe(slug: str, sdir: Path, probe: Path, timeout: int) -> dict:
    scratch = Path(tempfile.mkdtemp(prefix="mace_sd_"))
    code = (
        "import sys\n"
        f"sys.path.insert(0, {str(sdir)!r})\n"
        f"exec(compile(open({str(probe)!r}, encoding='utf-8').read(),"
        f" {str(probe)!r}, 'exec'))\n"
    )
    try:
        proc = subprocess.run(
            [str(venv_python(slug)), "-I", "-c", code], cwd=str(scratch),
            env={**os.environ, "PYTHONIOENCODING": "utf-8",
                 "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"},
            capture_output=True, text=True, encoding="utf-8",
            errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"__probe_failed__": "timeout"}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if proc.returncode != 0:
        return {"__probe_failed__": f"returncode {proc.returncode}",
                "__stdout__": proc.stdout[-2000:],
                "__stderr__": proc.stderr[-2000:]}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return {"__probe_failed__": "unparsable stdout",
                "__stdout__": proc.stdout[-2000:],
                "__stderr__": proc.stderr[-2000:]}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--keep-work", action="store_true")
    ap.add_argument("--root", default=str(SD),
                    help="dataset root that receives evidence/<case>/")
    args = ap.parse_args()
    sd_root = Path(args.root).resolve()

    spec = load(Path(args.case))
    case_id = spec["case_id"]
    slug = spec["base"]["slug"]
    meta = stage0_row(slug)
    root = (DISC / meta["root"]).resolve()
    rel = spec["base"]["file"]
    probe = (Path(spec["probe"]) if Path(spec["probe"]).is_absolute()
             else KIT / spec["probe"]).resolve()

    original_bytes = (root / rel).read_bytes()
    original = original_bytes.decode("utf-8").splitlines(keepends=True)
    verify_A(original, spec)
    patched, a_index = apply_patch(original, spec)
    u_ids = [b["id"] for b in spec["patch"]]
    ranges = find_ranges(patched, u_ids)

    work = WORK / case_id
    if work.exists():
        shutil.rmtree(work)
    work.mkdir(parents=True)

    def build(name: str, text: list[str]) -> Path:
        tree = work / name
        clone_tree(root, tree)
        write_variant(tree, rel, text)
        return tree

    base_sdir = source_dir(meta)

    def on_tree(tree: Path) -> dict:
        sdir = tree / base_sdir.relative_to(root)
        return run_probe(slug, sdir, probe, args.timeout)

    plus_tree = build("PLUS", patched)
    minus_tree = build("P_MINUS", delete_A(patched, a_index))
    plus = on_tree(plus_tree)
    minus = on_tree(minus_tree)
    if "__probe_failed__" in plus:
        print(json.dumps({"case": case_id, "P+ probe failed": plus},
                         ensure_ascii=False, indent=2))
        return 1
    if "__probe_failed__" in minus:
        print(json.dumps({"case": case_id, "P- probe failed": minus},
                         ensure_ascii=False, indent=2))
        return 1

    subsets = []
    for r in range(len(u_ids) + 1):
        subsets.extend(itertools.combinations(sorted(u_ids), r))
    variant_name = {s: "KEEP_" + ("_".join(s) if s else "EMPTY")
                    for s in subsets}

    observations = {"PLUS": plus, "P_MINUS": minus}
    for subset in subsets:
        text = delete_A(patched, a_index)
        for bid in sorted(u_ids, key=lambda b: ranges[b]["begin"], reverse=True):
            if bid not in subset:
                text = delete_block(text, ranges[bid])
        observations[variant_name[subset]] = on_tree(build(
            variant_name[subset], text))

    keys = [k for k in plus if not k.startswith("__")]
    report = {
        "case_id": case_id,
        "track": spec["track"],
        "mechanism": spec["mechanism"],
        "slug": slug,
        "file": rel,
        "A_line": spec["base"]["A_line"],
        "A_code": spec["base"]["A_code"],
        "original_sha256": hashlib.sha256(original_bytes).hexdigest(),
        "patched_sha256": hashlib.sha256("".join(patched).encode()).hexdigest(),
        "U": [{"id": b["id"], "after_line": b["after_line"],
               "role": b.get("role", ""), "lines": b["lines"]}
              for b in spec["patch"]],
        "line_map": {b["id"]: ranges[b["id"]] for b in spec["patch"]},
        "observations": observations,
        "per_input": {},
    }
    all_u = tuple(sorted(u_ids))
    for key in keys:
        pl = plus.get(key)
        mask = [list(s) for s in subsets
                if observations[variant_name[s]].get(key) == pl]
        minimal = [s for s in mask
                   if not any(set(o) < set(s) for o in mask)]
        u_necessary = all(
            observations[variant_name[tuple(x for x in all_u if x != u)]]
            .get(key) != pl for u in all_u)
        report["per_input"][key] = {
            "plus": pl,
            "p_minus": minus.get(key),
            "p_minus_equals_plus": minus.get(key) == pl,
            "exposing_witness": minus.get(key) != pl,
            "masking_sets": mask,
            "minimal_masking_sets": minimal,
            "mmbs": minimal,
            "empty_kept_masks": [] in mask,
            "u_necessary": u_necessary,
            "by_variant": {variant_name[s]: observations[variant_name[s]].get(key)
                           for s in subsets},
        }

    out = sd_root / "evidence" / case_id
    out.mkdir(parents=True, exist_ok=True)
    (out / "enumeration.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    (out / "original").mkdir(exist_ok=True)
    (out / "patched").mkdir(exist_ok=True)
    (out / "original" / Path(rel).name).write_bytes(original_bytes)
    (out / "patched" / Path(rel).name).write_text(
        "".join(patched), encoding="utf-8")
    diff = difflib.unified_diff(
        original, patched, fromfile="a/" + rel, tofile="b/" + rel, n=6)
    (out / "patch.diff").write_text("".join(diff), encoding="utf-8")

    print(json.dumps({
        "case": case_id,
        "inputs": {k: {"p_minus_equals_plus": v["p_minus_equals_plus"],
                       "exposing_witness": v["exposing_witness"],
                       "msms": v["minimal_masking_sets"],
                       "empty_kept_masks": v["empty_kept_masks"],
                       "u_necessary": v["u_necessary"]}
                   for k, v in report["per_input"].items()},
    }, ensure_ascii=False, indent=2))
    if not args.keep_work:
        shutil.rmtree(work, ignore_errors=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
