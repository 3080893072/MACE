"""Run a legal-input probe against P+, P- and U-subset variants.

The witness spec is a small JSON file written by the researcher:

    {
      "candidate_id": "...",
      "project_id": "...",
      "target": {"file": "...", "line": 10, "code": "..."},
      "universe": [{"id": "L20", "file": "...", "line": 20}, ...],
      "observation": {"probe": "probe_x.py", "payloads": [{...}, ...]},
      "declared_tests": ["tests/test_x.py::test_y", ...],
      "exposing_payloads": [0],
      "masked_payloads": [1]
    }

For every payload the probe runs on the unmodified variant (P+), on the
variant with A deleted (P-), and on every variant with A plus a subset of U
deleted.  A payload is exposing when P+ and P- observations differ; it is
masked when they agree and some nonempty U subset restores agreement.  This
mirrors :mod:`benchmark_real_v4.qualify`, but the observation comes from a
public-API probe instead of an original test.

Usage::

    python -m benchmark_real_v4.witness <spec.json>
    python -m benchmark_real_v4.witness --all
"""
from __future__ import annotations

import argparse
import itertools
import json
import sys
from pathlib import Path
from typing import Any, Dict, List, Sequence

from benchmark_real_v3 import variant_lab
from benchmark_real_v4.config import EVIDENCE, PROJECTS, V4, WORK_ROOT

variant_lab.PROJECTS = PROJECTS
variant_lab.WORK_ROOT = WORK_ROOT
variant_lab.VARIANT_ROOT = WORK_ROOT / "witness_variants"
variant_lab.PROBES = V4 / "probes"

SPEC_DIR = V4 / "witnesses"
OUT_DIR = EVIDENCE / "witnesses"


def _slug(candidate_id: str) -> str:
    return (candidate_id.replace(":", "_").replace("/", "_")
            .replace("\\", "_").replace(".", "_"))[:120]


def _canon(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _name(spec: Dict[str, Any], kind: str, key: str = "") -> str:
    base = f"v4w_{_slug(spec['candidate_id'])}_{kind}"
    return base + ("_" + key.replace("+", "_") if key else "")


def _plus(spec: Dict[str, Any]) -> Dict[str, Any]:
    return variant_lab.build_variant(
        spec["project_id"], _name(spec, "plus"))


def _minus(spec: Dict[str, Any], disabled: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    statements = [(spec["target"]["file"], int(spec["target"]["line"]))]
    for op in disabled:
        statements.append((op["file"], int(op["line"])))
    key = "+".join(op["id"] for op in disabled) or "EMPTY"
    return variant_lab.build_variant(
        spec["project_id"], _name(spec, "minus", key),
        statement_deletions=statements)


def _observe(spec: Dict[str, Any], variant: Dict[str, Any],
             payload: Dict[str, Any]) -> Dict[str, Any]:
    probe = spec["observation"]["probe"]
    return variant_lab.run_probe(
        spec["project_id"], Path(variant["root"]), probe, payload,
        timeout=int(spec.get("timeout", 180)))


def evaluate(spec: Dict[str, Any]) -> Dict[str, Any]:
    payloads = list(spec["observation"]["payloads"])
    universe = list(spec["universe"])
    variants: Dict[str, Dict[str, Any]] = {"plus": _plus(spec)}
    for size in range(len(universe) + 1):
        for subset in itertools.combinations(universe, size):
            key = "+".join(op["id"] for op in subset) or "EMPTY"
            variants[key] = _minus(spec, subset)
    observations: Dict[str, List[Dict[str, Any]]] = {}
    for key, variant in variants.items():
        observations[key] = [_observe(spec, variant, payload)
                             for payload in payloads]
    plus = [row["observation"] for row in observations["plus"]]
    minus = [row["observation"] for row in observations["EMPTY"]]
    by_key = {key: [row["observation"] for row in rows]
              for key, rows in observations.items() if key != "plus"}

    def same_key(key: str, index: int) -> bool:
        return _canon(by_key[key][index]) == _canon(plus[index])

    def subset_key(ids: set) -> str:
        return "+".join(sorted(ids)) or "EMPTY"

    rows = []
    for index, payload in enumerate(payloads):
        exposing = _canon(plus[index]) != _canon(minus[index])
        masked = not exposing and same_key("EMPTY", index)
        msms: List[List[str]] = []
        mmbs: List[List[str]] = []
        if masked:
            ids = [op["id"] for op in universe]
            valid: List[List[str]] = []

            def sufficient(kept: set) -> bool:
                # ``kept`` is the part of U left in place; the rest is
                # deleted together with A.  Keeping all of U reduces to the
                # empty-complement run, which is accepted only when deleting
                # some U subset also exposes (checked via mmbs below).
                if not kept:
                    return False
                return same_key(subset_key(set(ids) - kept), index)

            def breaking(deleted: set) -> bool:
                return not same_key(subset_key(deleted), index)

            for size in range(1, len(ids) + 1):
                for combo in itertools.combinations(ids, size):
                    kept = set(combo)
                    if sufficient(kept) and not any(
                            set(existing) < kept for existing in valid):
                        valid.append(list(combo))
            msms = [sorted(item) for item in valid]
            valid = []
            for size in range(1, len(ids) + 1):
                for combo in itertools.combinations(ids, size):
                    deleted = set(combo)
                    if breaking(deleted) and not any(
                            set(existing) < deleted for existing in valid):
                        valid.append(list(combo))
            mmbs = [sorted(item) for item in valid]
            # Without an exposing U deletion the agreement is supplied by
            # something outside U and no masking relation is established.
            if not mmbs:
                msms = []
        rows.append({
            "index": index,
            "payload": payload,
            "plus": plus[index],
            "minus_A": minus[index],
            "exposing": exposing,
            "masked_at_empty": masked,
            "msms": msms,
            "mmbs": mmbs,
            "runs": {
                key: observations[key][index] for key in sorted(observations)
            },
        })
    return {
        "candidate_id": spec["candidate_id"],
        "project_id": spec["project_id"],
        "target": spec["target"],
        "universe": universe,
        "declared_tests": spec.get("declared_tests", []),
        "probe": spec["observation"]["probe"],
        "payloads": rows,
        "summary": {
            "payloads": len(rows),
            "exposing": [row["index"] for row in rows if row["exposing"]],
            "masked": [row["index"] for row in rows
                       if row["masked_at_empty"]],
            "legal_exposing_payload": any(row["exposing"] for row in rows),
            "verified_msms": any(row["msms"] for row in rows),
            "verified_mmbs": any(row["mmbs"] for row in rows),
        },
        "exit": {key: observed[0]["returncode"]
                 for key, observed in observations.items()},
    }


def run_spec(path: Path) -> Dict[str, Any]:
    spec = json.loads(path.read_text(encoding="utf-8"))
    result = evaluate(spec)
    OUT_DIR.mkdir(parents=True, exist_ok=True)
    out = OUT_DIR / f"{_slug(spec['candidate_id'])}.json"
    out.write_text(json.dumps(result, ensure_ascii=False, indent=2,
                             sort_keys=True) + "\n", encoding="utf-8")
    return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("spec", nargs="?")
    parser.add_argument("--all", action="store_true")
    args = parser.parse_args()
    paths: List[Path]
    if args.all:
        paths = sorted(SPEC_DIR.glob("*.json"))
    elif args.spec:
        paths = [Path(args.spec)]
    else:
        parser.print_help()
        return 2
    for path in paths:
        result = run_spec(path)
        print(json.dumps({
            "candidate": result["candidate_id"],
            "summary": result["summary"],
        }, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
