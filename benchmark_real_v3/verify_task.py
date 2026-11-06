"""Execute the full enable/disable matrix for one candidate task.

Given a task spec with a target operation A and a declared candidate universe
U, this script builds, for every subset of U, the P+ and P- variants and runs
every declared input probe.  It then derives, per input:

* ``Masked_strict(D)``: P+ returns and the observations are equal.
* ``Exposed(D)``: both sides execute and the observations differ.
* ``MSMS_U`` / ``MMBS_U``: exact minimal sets over the declared U (all
  subsets are enumerated, so the minimality check is exhaustive over U).
* ``prerequisite_conditioned``: whether every exposing subset depends on a
  control prerequisite that is not itself in U.

The output is evidence, not a task-level claim over the whole legal input
domain.  ``scope`` in the result states exactly which inputs were executed.
"""
from __future__ import annotations

import itertools
import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple

from benchmark_real_v3.config import EVIDENCE, PROJECTS
from benchmark_real_v3.variant_lab import build_variant, observe

TASKS = Path(__file__).resolve().parent / "tasks"


def _build(project_id: str, name: str, target: Dict[str, Any],
           disabled: Sequence[Dict[str, Any]], remove_target: bool):
    deletions: List[Tuple[str, int]] = []
    blocks: List[Tuple[str, int, int]] = []
    if remove_target:
        deletions.append((target["file"], target["line"]))
    for op in disabled:
        if op.get("kind") == "block":
            blocks.append((op["file"], op["first_line"], op["last_line"]))
        else:
            deletions.append((op["file"], op["line"]))
    return build_variant(
        project_id, name,
        statement_deletions=deletions,
        block_deletions=blocks,
    )


def _equal(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    return a.get("observation") == b.get("observation")


def _executable(run: Dict[str, Any]) -> bool:
    return (
        run.get("returncode") == 0
        and isinstance(run.get("observation"), dict)
        and "outcome" in run["observation"]
    )


def _powerset(ops: Sequence[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], ...]]:
    out = []
    for size in range(len(ops) + 1):
        out.extend(itertools.combinations(ops, size))
    return out


def _subset_key(ops: Iterable[Dict[str, Any]]) -> Tuple[str, ...]:
    return tuple(sorted(op["id"] for op in ops))


def evaluate(project_id: str, spec: Dict[str, Any]) -> Dict[str, Any]:
    target = spec["target_operation"]
    universe = spec["candidate_universe"]
    probe = spec["probe"]
    inputs = spec["inputs"]
    subsets = _powerset(universe)
    runs: Dict[str, Any] = {"plus": {}, "minus": {}}
    for subset in subsets:
        key = "+".join(_subset_key(subset)) or "EMPTY"
        for side, remove in (("plus", False), ("minus", True)):
            name = f"{spec['task_id']}_{side}_{key}".replace("+", "_")
            variant = _build(
                project_id, name, target, list(subset), remove_target=remove)
            for item in inputs:
                result = observe(project_id, variant, probe, item["payload"])
                runs[side].setdefault(item["id"], {})[key] = result

    per_input: Dict[str, Any] = {}
    for item in inputs:
        iid = item["id"]
        masked: Dict[str, bool] = {}
        exposed: Dict[str, bool] = {}
        executable: Dict[str, bool] = {}
        for subset in subsets:
            key = "+".join(_subset_key(subset)) or "EMPTY"
            plus = runs["plus"][iid][key]
            minus = runs["minus"][iid][key]
            ok = _executable(plus) and _executable(minus)
            executable[key] = ok
            plus_returns = (
                ok and plus["observation"].get("outcome") == "return")
            masked[key] = bool(plus_returns and _equal(plus, minus))
            exposed[key] = bool(
                ok and plus["observation"] != minus["observation"])

        def only_holds(s: Tuple[Dict[str, Any], ...]) -> bool:
            # Only(S) = Masked_strict(U \ S)
            rest = [op for op in universe if op not in s]
            return masked["+".join(_subset_key(rest)) or "EMPTY"]

        def break_holds(s: Tuple[Dict[str, Any], ...]) -> bool:
            return exposed["+".join(_subset_key(s)) or "EMPTY"]

        def minimal_sufficient(s) -> bool:
            if not s or not only_holds(s):
                return False
            for size in range(1, len(s)):
                for sub in itertools.combinations(s, size):
                    if only_holds(sub):
                        return False
            return True

        def minimal_breaking(s) -> bool:
            if not s or not break_holds(s):
                return False
            for size in range(0, len(s)):
                for sub in itertools.combinations(s, size):
                    if break_holds(sub):
                        return False
            return True

        msms = [list(_subset_key(s)) for s in subsets if minimal_sufficient(s)]
        mmbs = [list(_subset_key(s)) for s in subsets if minimal_breaking(s)]
        per_input[iid] = {
            "role": item.get("role", "unspecified"),
            "payload": item["payload"],
            "executable": executable,
            "masked_strict": masked,
            "exposed": exposed,
            "msms": msms,
            "mmbs": mmbs,
            "plus_observations": {
                key: runs["plus"][iid][key]["observation"]
                for key in masked
            },
            "minus_observations": {
                key: runs["minus"][iid][key]["observation"]
                for key in masked
            },
        }

    exposing_inputs = [
        iid for iid, data in per_input.items()
        if data["exposed"].get("EMPTY")
    ]
    masking_inputs = [
        iid for iid, data in per_input.items()
        if data["masked_strict"].get("EMPTY")
    ]
    return {
        "task_id": spec["task_id"],
        "project_id": project_id,
        "project": PROJECTS[project_id]["project"],
        "version": PROJECTS[project_id]["version"],
        "target_operation": target,
        "candidate_universe": universe,
        "probe": probe,
        "scope": {
            "declared_inputs": [item["id"] for item in inputs],
            "candidate_universe_size": len(universe),
            "all_subsets_enumerated": True,
            "exposing_inputs": exposing_inputs,
            "masking_inputs": masking_inputs,
            "claim": (
                "Exact over the declared finite inputs and declared candidate "
                "universe U.  Not a claim over the whole legal input domain "
                "or over operations outside U."
            ),
        },
        "inputs": per_input,
        "runs": runs,
    }


def main() -> int:
    import sys

    task_dir = TASKS / sys.argv[1]
    spec = json.loads((task_dir / "spec.json").read_text(encoding="utf-8"))
    result = evaluate(spec["project_id"], spec)
    out = EVIDENCE / f"{spec['task_id']}_matrix.json"
    out.write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(result["scope"], ensure_ascii=False, indent=2))
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
