"""Finite input domains for bounded verification.

A domain is always finite and explicitly declared.  Two kinds are supported:

* ``exhaustive`` -- the full Cartesian product of the per-argument domains.
  Checking a property on such a domain yields evidence level ``BOUNDED``:
  a finite, complete check, *not* a proof over the infinite type domain.
* ``sample`` -- a seeded pseudo-random subset, which yields ``TESTED``.
"""
from __future__ import annotations

import itertools
import random
from dataclasses import dataclass
from typing import Any, Dict, Iterator, List

from .terms import TermError, sort_of

MAX_CASES = 300_000


@dataclass
class Domain:
    cases: List[Dict[str, Any]]
    exhaustive: bool
    spec: Dict[str, Any]

    def __len__(self) -> int:
        return len(self.cases)

    @property
    def evidence_level(self) -> str:
        return "BOUNDED" if self.exhaustive else "TESTED"


def _values(spec: Dict[str, Any]) -> List[Any]:
    sort = spec.get("sort")
    if sort == "bool":
        return [False, True]
    if sort == "int":
        if "values" in spec:
            return list(spec["values"])
        lo, hi = spec.get("range", [0, 0])
        return list(range(lo, hi + 1))
    raise TermError(f"unsupported argument sort in domain: {sort}")


def _lists(spec: Dict[str, Any]) -> Iterator[List[int]]:
    if "values" not in spec or "length" not in spec:
        raise TermError("list domain needs 'values' and 'length'")
    lo, hi = spec["length"]
    for length in range(lo, hi + 1):
        for seq in itertools.product(spec["values"], repeat=length):
            yield list(seq)


def build_domain(spec: Dict[str, Any], seed: int = 0) -> Domain:
    kind = spec.get("kind", "exhaustive")
    args = spec["args"]
    per_arg: List[List[Any]] = []
    for arg in args:
        sort = arg.get("sort")
        if sort == "list[int]":
            per_arg.append(list(_lists(arg)))
        else:
            per_arg.append(_values(arg))
    total = 1
    for values in per_arg:
        total *= len(values)
    if total > MAX_CASES:
        raise TermError(f"domain has {total} cases (> {MAX_CASES}); use kind='sample' with 'n'")

    names = [a["name"] for a in args]
    if kind == "exhaustive":
        cases = [dict(zip(names, combo)) for combo in itertools.product(*per_arg)]
        return Domain(cases, True, spec)
    if kind == "sample":
        rng = random.Random(seed)
        n = int(spec.get("n", 2000))
        seen = set()
        cases = []
        attempts = 0
        while len(cases) < n and attempts < n * 50:
            attempts += 1
            combo = tuple(rng.choice(values) for values in per_arg)
            key = repr(combo)
            if key in seen:
                continue
            seen.add(key)
            case = dict(zip(names, combo))
            for name, value in case.items():
                if isinstance(value, list):
                    case[name] = list(value)
            cases.append(case)
        return Domain(cases, False, spec)
    raise TermError(f"unknown domain kind {kind!r}")


def input_sorts(spec: Dict[str, Any]) -> Dict[str, str]:
    return {a["name"]: a["sort"] for a in spec["args"]}


def check_case(case: Dict[str, Any], spec: Dict[str, Any]) -> None:
    for arg in spec["args"]:
        name, sort = arg["name"], arg["sort"]
        if name not in case:
            raise TermError(f"case is missing argument {name}")
        if sort_of(case[name]) != sort:
            raise TermError(f"argument {name} has sort {sort_of(case[name])}, expected {sort}")
