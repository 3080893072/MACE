"""Assemble per-case task packages for the source-derived track.

Every package is written to ``source_derived/tasks/<case_id>/`` and contains

    task.json        problem statement (RESEARCHER_CONSTRUCTED)
    reference.json   target operation, candidate universe, expected outputs
    provenance.json  upstream sdist identity, evidence and acceptance pointers
    patch.diff       unified diff (insertions only; A is never removed)
    acceptance.json  independent acceptance report

The builder only *reads* the evidence produced by ``sd_harness.py`` and
``sd_acceptance.py``; it never re-runs the probes.
"""
from __future__ import annotations

import argparse
import ast
import json
import re
import shutil
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
DS = KIT / "benchmark_v4_dataset"
DISC = DS / "discovery"
SD = DS / "source_derived"
import sys as _mace_sys  # noqa: E402
if str(KIT) not in _mace_sys.path:
    _mace_sys.path.insert(0, str(KIT))
from mace.paths import venv_python, venvs_root, work_root  # noqa: E402


def load(path: Path):
    return json.loads(path.read_text("utf-8"))


def registry_row(slug: str) -> dict:
    for row in load(DISC / "manifest" / "source_registry.json")["projects"]:
        if row["slug"] == slug:
            return row
    raise SystemExit(f"unknown slug {slug}")


def stage0_row(slug: str) -> dict:
    for row in load(DISC / "stage0" / "projects.json")["projects"]:
        if row["slug"] == slug:
            return row
    raise SystemExit(f"unknown slug {slug}")


def enclosing_function(text: str, a_line: int) -> str:
    """Innermost function whose AST span covers A (1-based line)."""
    tree = ast.parse(text)
    cands = [n for n in ast.walk(tree)
             if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef))
             and n.lineno <= a_line <= (n.end_lineno or n.lineno)]
    return max(cands, key=lambda n: n.lineno).name if cands else "<module>"


def subset_label(kept: list[str]) -> str:
    return "[]" if not kept else "[" + ",".join(kept) + "]"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--root", default=str(SD),
                    help="dataset root with cases/, evidence/, acceptance/")
    ap.add_argument("--out", default="",
                    help="package output directory (default <root>/tasks)")
    ap.add_argument("--clean", action="store_true",
                    help="remove the output directory before building")
    args = ap.parse_args()
    root = Path(args.root).resolve()
    out_root = Path(args.out).resolve() if args.out else root / "tasks"
    if args.clean and out_root.exists():
        shutil.rmtree(out_root)
    out_root.mkdir(parents=True, exist_ok=True)

    test_map = load(root / "test_map.json") \
        if (root / "test_map.json").exists() else load(SD / "test_map.json")
    suite = load(SD / "evidence" / "original_test_suite.json") \
        if (SD / "evidence" / "original_test_suite.json").exists() else {}

    for case_path in sorted((root / "cases").glob("*.json")):
        spec = load(case_path)
        cid = spec["case_id"]
        slug = spec["base"]["slug"]
        rel = spec["base"]["file"]
        reg = registry_row(slug)
        meta = stage0_row(slug)
        ev = root / "evidence" / cid
        enumeration = load(ev / "enumeration.json")
        acceptance = load(root / "acceptance" / f"{cid}.json")

        original = (ev / "original" / Path(rel).name).read_text("utf-8").splitlines()
        a_index = int(spec["base"]["A_line"]) - 1
        function = enclosing_function("\n".join(original),
                                      int(spec["base"]["A_line"]))

        # candidate universe entries with patched-file line numbers
        universe = []
        for block in spec["patch"]:
            rng = enumeration["line_map"][block["id"]]
            universe.append({
                "id": block["id"],
                "file": rel,
                "line": rng["begin"] + 2,
                "code": block["lines"][0],
                "role": block.get("role", ""),
                "patch_anchor_line": block["after_line"],
                "block_span": [rng["begin"] + 1, rng["end"] + 1],
            })

        inputs = {}
        for key, per in enumeration["per_input"].items():
            role = ("masking" if key.startswith("mask_")
                    else "exposing" if key.startswith("expose_")
                    else "negative_control" if key.startswith("nc_")
                    else "control")
            entry = {
                "role": role,
                "description": spec["inputs"].get(key, ""),
                "p_plus": per["plus"],
                "p_minus": per["p_minus"],
                "p_minus_equals_plus": per["p_minus_equals_plus"],
                "msms": per["minimal_masking_sets"],
                "mmbs": per["mmbs"],
                "empty_kept_masks": per["empty_kept_masks"],
                "u_necessary": per["u_necessary"],
            }
            inputs[key] = entry

        all_u = [b["id"] for b in spec["patch"]]
        # one subset table per case (observations are per input, keep the table
        # of masking verdicts for the first masking input and note the rest)
        mask_keys = [k for k, v in inputs.items() if v["role"] == "masking"]
        subset_table = {}
        if mask_keys:
            first = mask_keys[0]
            for name in enumeration["per_input"][first]["by_variant"]:
                kept = [] if name == "KEEP_EMPTY" else name[5:].split("_")
                subset_table[subset_label(kept)] = (
                    "equal to P+"
                    if enumeration["per_input"][first]["by_variant"][name]
                    == enumeration["per_input"][first]["plus"]
                    else "differs from P+")

        task = {
            "task_id": cid,
            "project": meta["name"],
            "version": meta["version"],
            "split": spec.get("split", "DEV"),
            "track": spec["track"],
            "researcher_constructed": True,
            "mechanism": spec["mechanism"],
            "construction_note": (
                "A is a real statement in the released source.  The deletion "
                "and the candidate operations U are researcher-constructed: "
                "this task must not be reported as a natural upstream defect."),
            "construction_rationale": spec.get("rationale", ""),
            "masking_conditions": (
                "The masking verdicts hold exactly on the declared finite "
                "input set; the exposing input lies outside the declared "
                "repair domain of U and restores the A-effect."),
            "target_operation": {
                "file": rel,
                "line": spec["base"]["A_line"],
                "function": function,
                "code": spec["base"]["A_code"],
                "statement": "single statement; deletion keeps the line and indentation",
            },
            "deletion_method": (
                "replace the line with equal-indentation "
                "'pass  # P-: target A deleted'; line numbers are preserved"),
            "legal_input_contract": {
                "api": {
                    "sd_pygments_bbcode70_italic": "pygments.highlight(code, lexer, BBCodeFormatter(style=...))",
                    "sd_pygments_bbcode64_color": "pygments.highlight(code, lexer, BBCodeFormatter(style=...))",
                    "sd_pygments_groff73_italic": "pygments.highlight(code, lexer, GroffFormatter(style=...))",
                    "sd_pygments_latex297_italic": "pygments.highlight(code, lexer, LatexFormatter(style=...)); Formatter(style=...).get_style_defs()",
                    "sd_pygments_style95_cache": "pygments.style.Style.style_for_token(token)",
                    "sd_tabulate_1052_strip_right": "tabulate.tabulate(data, tablefmt=..., colalign=...)",
                    "sd_tabulate_1056_strip_center": "tabulate.tabulate(data, tablefmt=..., colalign=...)",
                    "sd_tabulate_2557_curlen": "tabulate._CustomTextWrap(width=..., max_lines=...).wrap(text)",
                    "sd_networkx_gexf448_slices": "networkx.write_gexf(G, path, version=...)",
                    "sd_jsonschema_1145_pointer": "validators.RefResolver(base_uri, referrer).resolve_fragment(document, fragment)",
                }.get(cid, "see probe"),
                "constraints": [
                    "inputs use only public/declared API arguments",
                    "no source edits beyond the recorded patch",
                    "observation is the returned value, the serialised output, "
                    "or the exception type and message",
                ],
            },
            "declared_inputs": [
                {"id": k, "role": v["role"], "description": v["description"]}
                for k, v in inputs.items()],
            "original_tests": test_map.get(cid, {}).get("tests", []),
            "original_test_suite": suite.get(cid, {}),
            "scope_note": (
                "Exact over the declared finite inputs and the declared "
                "candidate universe U; not a claim over all legal inputs or "
                "operations outside U."),
        }

        reference = {
            "task_id": cid,
            "story": "SOURCE_DERIVED_MASKING_STORY",
            "target_operation": task["target_operation"],
            "candidate_universe": universe,
            "inputs": inputs,
            "minimality": {
                "domain": "FINITE_DOMAIN_EXACT over U=" + subset_label(all_u),
                "subsets": subset_table,
                "note": (
                    "The subset table is shown for the first masking input; "
                    "every input has its own exact table in "
                    "evidence/%s/enumeration.json." % cid),
            },
            "not_claimed": [
                "this is not a naturally occurring upstream defect",
                "no claim that the original test suite exposes the deletion",
                "no claim outside the declared finite inputs and U",
            ] + ([] if any(v["role"] == "control" for v in inputs.values()) else [
                "no control input exists for this mechanism: A runs during "
                "class construction for every standard token, so no input "
                "reaches an observation without A or U; no prerequisite "
                "relation is claimed (PROTOCOL AC8 alternative)",
            ]),
        }

        provenance = {
            "task_id": cid,
            "track": spec["track"],
            "researcher_constructed": True,
            "sdist": {
                "url": reg["url"],
                "sha256": reg["sha256"],
                "size": reg["size"],
                "filename": reg["filename"],
            },
            "license": reg.get("license") or reg.get("license_classifiers", [""])[0],
            "requires_python": reg.get("requires_python", ""),
            "source_file": rel,
            "source_file_sha256": enumeration["original_sha256"],
            "patched_sha256": enumeration["patched_sha256"],
            "python": "Python 3.11.7",
            "pytest": "7.4.0",
            "venv": str(venvs_root() / slug),
            "evidence": {
                "original": f"source_derived/evidence/{cid}/original/{Path(rel).name}",
                "patched": f"source_derived/evidence/{cid}/patched/{Path(rel).name}",
                "patch_diff": f"source_derived/evidence/{cid}/patch.diff",
                "enumeration": f"source_derived/evidence/{cid}/enumeration.json",
                "acceptance": f"source_derived/acceptance/{cid}.json",
            },
            "acceptance": {
                "independent": acceptance["independent"],
                "shares_construction_code": acceptance["shares_construction_code"],
                "all_checks_pass": acceptance["all_checks_pass"],
                "failed_checks": [k for k, v in acceptance["checks"].items() if not v],
            },
            "original_test_suite": suite.get(cid, {}),
        }

        dest = out_root / cid
        dest.mkdir()
        (dest / "task.json").write_text(
            json.dumps(task, ensure_ascii=False, indent=2) + "\n", "utf-8")
        (dest / "reference.json").write_text(
            json.dumps(reference, ensure_ascii=False, indent=2) + "\n", "utf-8")
        (dest / "provenance.json").write_text(
            json.dumps(provenance, ensure_ascii=False, indent=2) + "\n", "utf-8")
        (dest / "acceptance.json").write_text(
            json.dumps(acceptance, ensure_ascii=False, indent=2) + "\n", "utf-8")
        shutil.copy2(ev / "patch.diff", dest / "patch.diff")
        print(cid, "ok" if acceptance["all_checks_pass"] else "ACCEPTANCE_FAIL")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
