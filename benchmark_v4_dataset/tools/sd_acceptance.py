"""Independent acceptance for source-derived (SD) cases.

This script deliberately shares **no construction code** with
``sd_harness.py``:

* the upstream file is re-extracted from the published sdist, not read from
  the discovery tree;
* P+ is assembled by a line-by-line emitter (anchor -> insertion map) rather
  than by descending slice insertion;
* U blocks are located by a scanning state machine rather than by ``next()``;
* subsets are enumerated by bitmask rather than ``itertools.combinations``;
* the probe is launched through ``runpy.run_path`` rather than
  ``exec(compile(...))``.

It independently recomputes every masking set and then compares the result
with the construction report in ``evidence/<case_id>/enumeration.json``.  A
case only passes when both computations agree and all structural checks hold.

Usage::

    python -I benchmark_v4_dataset/tools/sd_acceptance.py \
        --case benchmark_v4_dataset/source_derived/cases/<case>.json
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import tarfile
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


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def extract_sdist(slug: str, dest: Path) -> Path:
    """Unpack the published sdist and return the extracted top directory."""
    src = DISC / "sdists" / f"{slug}.tar.gz"
    if not src.exists():
        raise SystemExit(f"missing sdist {src}")
    with tarfile.open(src, "r:gz") as tf:
        # Filter defensively: sdists are archives of untrusted origin.
        members = [m for m in tf.getmembers()
                   if not (Path(m.name).is_absolute() or ".." in Path(m.name).parts)]
        tf.extractall(dest, members=members)
    tops = [p for p in dest.iterdir() if p.is_dir()]
    if len(tops) != 1:
        raise SystemExit(f"unexpected sdist layout: {tops}")
    return tops[0]


def assemble(original: list[str], patch: list[dict],
             a_line: int) -> tuple[list[str], int]:
    """Emit the patched file line by line, inserting blocks after anchors."""
    insertions: dict[int, list[str]] = {}
    for block in patch:
        indent = " " * int(block["indent"])
        chunk = [indent + BEGIN.format(id=block["id"]) + "\n"]
        chunk += [indent + line + "\n" for line in block["lines"]]
        chunk += [indent + END.format(id=block["id"]) + "\n"]
        insertions.setdefault(int(block["after_line"]), []).extend(chunk)

    out: list[str] = []
    for number, line in enumerate(original, start=1):
        out.append(line)
        out.extend(insertions.get(number, []))

    ahead = sum(len(v) for k, v in insertions.items() if k < a_line)
    return out, a_line - 1 + ahead


def delete_statement(text: list[str], index: int) -> list[str]:
    out = list(text)
    raw = out[index]
    pad = raw[: len(raw) - len(raw.lstrip())]
    out[index] = pad + "pass  # P-: target A deleted\n"
    return out


def block_bounds(text: list[str], block_id: str) -> tuple[int, int]:
    """Scan once, tracking markers, and return (begin, end) for one block."""
    want_begin = BEGIN.format(id=block_id).strip()
    want_end = END.format(id=block_id).strip()
    begin = end = None
    for i, line in enumerate(text):
        stripped = line.strip()
        if stripped == want_begin:
            begin = i
        elif stripped == want_end and begin is not None and end is None:
            end = i
            break
    if begin is None or end is None:
        raise SystemExit(f"block {block_id} markers not found")
    return begin, end


def disable_block(text: list[str], bounds: tuple[int, int]) -> list[str]:
    out = list(text)
    begin, end = bounds
    pad = out[begin][: len(out[begin]) - len(out[begin].lstrip())]
    for i in range(begin, end + 1):
        out[i] = "\n"
    out[begin] = pad + "pass  # P-: U operation disabled\n"
    return out


def stage_tree(root: Path, rel: str, text: list[str], dest: Path) -> Path:
    shutil.copytree(root, dest, copy_function=shutil.copy2,
                    ignore=shutil.ignore_patterns("__pycache__", "*.pyc",
                                                  ".git", ".tox", ".venv"))
    target = dest / rel
    target.write_text("".join(text), encoding="utf-8")
    return dest


def probe_once(slug: str, root: Path, sdir_rel: str, probe: Path,
               timeout: int) -> dict:
    scratch = Path(tempfile.mkdtemp(prefix="mace_accept_"))
    boot = (
        "import runpy, sys\n"
        f"sys.path.insert(0, {str(root / sdir_rel)!r})\n"
        f"runpy.run_path({str(probe)!r}, run_name='__main__')\n"
    )
    env = {k: v for k, v in os.environ.items()
           if k in ("PATH", "SystemRoot", "TEMP", "TMP", "HOME",
                    "USERPROFILE", "LOCALAPPDATA", "APPDATA")}
    env.update({"PYTHONIOENCODING": "utf-8", "PYTHONDONTWRITEBYTECODE": "1",
                "PYTHONHASHSEED": "0"})
    try:
        proc = subprocess.run(
            [str(venv_python(slug)), "-I", "-c", boot],
            cwd=str(scratch), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return {"__probe_failed__": "timeout"}
    finally:
        shutil.rmtree(scratch, ignore_errors=True)
    if proc.returncode != 0:
        return {"__probe_failed__": f"rc {proc.returncode}",
                "__stderr__": proc.stderr[-2000:]}
    try:
        return json.loads(proc.stdout.strip().splitlines()[-1])
    except Exception:
        return {"__probe_failed__": "unparsable stdout",
                "__stdout__": proc.stdout[-1000:]}


def minimal_sets(mask_bits: set[int], u_ids: list[str]) -> list[list[str]]:
    out = []
    for bits in sorted(mask_bits):
        # Minimal = no proper subset of this set also masks.
        if any((other & ~bits) == 0 and other != bits
               for other in mask_bits):
            continue
        out.append([u_ids[i] for i in range(len(u_ids)) if bits >> i & 1])
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", required=True)
    ap.add_argument("--timeout", type=int, default=300)
    ap.add_argument("--root", default=str(SD),
                    help="dataset root holding evidence/ and acceptance/")
    args = ap.parse_args()
    sd_root = Path(args.root).resolve()

    spec = load(Path(args.case))
    case_id = spec["case_id"]
    slug = spec["base"]["slug"]
    rel = spec["base"]["file"]
    probe = (KIT / spec["probe"]).resolve()
    meta = stage0_row(slug)
    discovery_root = (DISC / meta["root"]).resolve()
    evidence = sd_root / "evidence" / case_id

    checks: dict[str, bool] = {}
    notes: dict[str, object] = {}

    # --- AC1: upstream bytes, re-derived from the published sdist ----------
    with tempfile.TemporaryDirectory(prefix="mace_sdist_") as td:
        top = extract_sdist(slug, Path(td))
        sdist_file = top / rel
        sdist_bytes = sdist_file.read_bytes()
    disc_bytes = (discovery_root / rel).read_bytes()
    ev_bytes = (evidence / "original" / Path(rel).name).read_bytes()
    hashes = {"sdist": sha256_bytes(sdist_bytes),
              "discovery": sha256_bytes(disc_bytes),
              "evidence": sha256_bytes(ev_bytes)}
    checks["AC1_sdist_matches_discovery"] = hashes["sdist"] == hashes["discovery"]
    checks["AC1_evidence_matches_source"] = hashes["evidence"] == hashes["sdist"]
    notes["source_sha256"] = hashes["sdist"]

    original = sdist_bytes.decode("utf-8").splitlines(keepends=True)
    a_line = int(spec["base"]["A_line"])
    a_code = spec["base"]["A_code"]
    checks["AC1_A_line_text"] = original[a_line - 1].rstrip("\n") == a_code.rstrip("\n")

    # --- independent construction -----------------------------------------
    patched, a_index = assemble(original, spec["patch"], a_line)
    checks["patch_preserves_A"] = patched[a_index].rstrip("\n") == a_code.rstrip("\n")
    inserted = len(patched) - len(original)
    expected = sum(len(b["lines"]) + 2 for b in spec["patch"])
    checks["patch_only_inserts"] = inserted == expected
    notes["inserted_lines"] = inserted

    u_ids = [b["id"] for b in spec["patch"]]
    bounds = {bid: block_bounds(patched, bid) for bid in u_ids}
    checks["U_blocks_outside_A"] = all(
        not (b[0] <= a_index <= b[1]) for b in bounds.values())

    minus = delete_statement(patched, a_index)
    diff_lines = [(i, x, y) for i, (x, y) in enumerate(zip(patched, minus), 1)
                  if x != y]
    checks["P_minus_only_deletes_A"] = (
        len(diff_lines) == 1 and diff_lines[0][0] == a_index + 1
        and diff_lines[0][2] ==
        patched[a_index][: len(patched[a_index]) - len(patched[a_index].lstrip())]
        + "pass  # P-: target A deleted" + "\n")

    # diff must not show A as a removed line: blocks are insertions only
    patch_diff = (evidence / "patch.diff").read_text(encoding="utf-8")
    removed = [ln for ln in patch_diff.splitlines()
               if ln.startswith("-") and not ln.startswith("---")]
    checks["patch_diff_does_not_remove_A"] = all(
        ln[1:].rstrip("\n") != a_code.rstrip("\n") for ln in removed)
    added_count = sum(1 for ln in patch_diff.splitlines()
                      if ln.startswith("+") and not ln.startswith("+++"))
    checks["patch_diff_insert_count"] = added_count == inserted

    # --- probe runs -------------------------------------------------------
    base_sdir = discovery_root
    packages = meta.get("packages") or []
    if packages and len(Path(packages[0]).parts) > 1:
        base_sdir = (discovery_root / Path(packages[0]).parent).resolve()
    sdir_rel = str(base_sdir.relative_to(discovery_root))

    n = len(u_ids)
    bit_sets = list(range(1 << n))
    names = {}
    for bits in bit_sets:
        kept = tuple(u_ids[i] for i in range(n) if bits >> i & 1)
        names[bits] = kept

    with tempfile.TemporaryDirectory(prefix="mace_accept_tree_") as td:
        td = Path(td)

        def run(text: list[str], tag: str) -> dict:
            tree = td / tag
            stage_tree(discovery_root, rel, text, tree)
            return probe_once(slug, tree, sdir_rel, probe, args.timeout)

        plus = run(patched, "PLUS")
        minus_obs = run(minus, "P_MINUS")
        if "__probe_failed__" in plus or "__probe_failed__" in minus_obs:
            print(json.dumps({"case": case_id, "probe_failed": [plus, minus_obs]},
                             ensure_ascii=False, indent=2))
            return 1

        obs = {}
        per_input = {}
        for bits in bit_sets:
            text = delete_statement(patched, a_index)
            for i in range(n - 1, -1, -1):
                if not (bits >> i & 1):
                    text = disable_block(text, bounds[u_ids[i]])
            obs[bits] = run(text, "KEEP_" + ("_".join(names[bits]) or "EMPTY"))

    keys = [k for k in plus if not k.startswith("__")]
    for key in keys:
        target = plus[key]
        bits_masking = {b for b in bit_sets if obs[b].get(key) == target}
        recomputed = sorted(minimal_sets(bits_masking, u_ids))
        per_input[key] = {
            "p_minus_equals_plus": minus_obs.get(key) == target,
            "exposing_witness": minus_obs.get(key) != target,
            "masking_sets": sorted(names[b] for b in bits_masking),
            "minimal_masking_sets": recomputed,
            "empty_kept_masks": () in [names[b] for b in bits_masking],
        }

    # --- agreement with the construction report ---------------------------
    construction = load(evidence / "enumeration.json")
    agree = True
    for key in keys:
        claimed = construction["per_input"][key]
        mine = per_input[key]
        if sorted(tuple(s) for s in claimed["masking_sets"]) != \
                sorted(tuple(s) for s in mine["masking_sets"]):
            agree = False
        if sorted(tuple(s) for s in claimed["minimal_masking_sets"]) != \
                sorted(tuple(s) for s in mine["minimal_masking_sets"]):
            agree = False
        if claimed["p_minus_equals_plus"] != mine["p_minus_equals_plus"]:
            agree = False
    checks["enumeration_agrees"] = agree

    # --- role-based checks -------------------------------------------------
    roles = {}
    for key in keys:
        roles[key] = ("masking" if key.startswith("mask_")
                      else "exposing" if key.startswith("expose_")
                      else "control" if key.startswith("control_")
                      else "negative_control" if key.startswith("nc_")
                      else "undeclared")
    checks["roles_declared"] = all(r != "undeclared" for r in roles.values())

    masking_ok, exposing_ok, control_ok, nc_ok = True, True, True, True
    for key, role in roles.items():
        mine = per_input[key]
        if role == "masking":
            masking_ok &= (mine["p_minus_equals_plus"]
                           and mine["minimal_masking_sets"]
                           and not mine["empty_kept_masks"])
            # strict-subset minimality is enforced by minimal_sets()
        elif role == "exposing":
            exposing_ok &= mine["exposing_witness"]
        elif role == "control":
            control_ok &= mine["p_minus_equals_plus"]
        elif role == "negative_control":
            nc_ok &= (mine["exposing_witness"]
                      and not mine["minimal_masking_sets"]
                      and not mine["empty_kept_masks"])
    checks["masking_inputs_satisfied"] = masking_ok
    checks["exposing_inputs_satisfied"] = exposing_ok
    checks["control_inputs_satisfied"] = control_ok
    checks["negative_control_inputs_satisfied"] = nc_ok

    # A negative-control task must prove that no masking relation exists at
    # all over the declared inputs and U: every input must differ from P+ and
    # no kept subset may reproduce P+.  It may not declare masking inputs.
    if spec.get("mechanism") == "M10_NEGATIVE_CONTROL":
        nc_strict = bool(keys) and all(
            roles[k] == "negative_control"
            and per_input[k]["exposing_witness"]
            and not per_input[k]["minimal_masking_sets"]
            for k in keys)
        checks["negative_control_no_masking_relation"] = nc_strict

    # u_necessary: removing any single operation from a minimal set breaks it
    u_nec_ok = True
    for key, role in roles.items():
        if role != "masking":
            continue
        for ms in per_input[key]["minimal_masking_sets"]:
            full = sum(1 << u_ids.index(u) for u in ms)
            for u in ms:
                without = full & ~(1 << u_ids.index(u))
                if obs[without].get(key) == plus[key]:
                    u_nec_ok = False
    checks["u_necessary_in_minimal_sets"] = u_nec_ok

    report = {
        "case_id": case_id,
        "independent": True,
        "shares_construction_code": False,
        "checks": checks,
        "all_checks_pass": all(checks.values()),
        "hashes": hashes,
        "A": {"file": rel, "line": a_line, "code": a_code,
               "patched_index": a_index + 1},
        "U": u_ids,
        "per_input": per_input,
        "notes": notes,
    }
    out = sd_root / "acceptance"
    out.mkdir(parents=True, exist_ok=True)
    (out / f"{case_id}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8")
    print(json.dumps({"case": case_id,
                       "all_checks_pass": report["all_checks_pass"],
                       "failed": [k for k, v in checks.items() if not v]},
                      ensure_ascii=False))
    return 0 if report["all_checks_pass"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
