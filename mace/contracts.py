"""Structured semantic contracts proposed by the LLM.

The model never emits free-form Python that we execute.  It emits a JSON
document with a fixed shape; every ``expr``/``condition`` field is parsed by
``mace.terms`` into the typed term language and rejected otherwise.

Shape (all ids unique across the bundle)::

    {
      "target_effects": [
        {"id": "T1", "expr": "xs_post == sorted(xs)",
         "source_lines": [12], "rationale": "..."}
      ],
      "upstream": [
        {"id": "U1", "expr": "fn_0(xs) == sorted(xs)", "condition": "pre",
         "source_lines": [2, 3, 4], "rationale": "..."}
      ],
      "observers": [
        {"id": "O0", "channel": 0, "expr": "min(xs) if use_left else xs[0]",
         "condition": "use_left or xs[0] == min(xs)",
         "source_lines": [14], "rationale": "..."}
      ],
      "mask_guard": {"expr": "pre or (...)", "source_lines": [12]},
      "uncertainty": "..."
    }

Semantics
---------
* ``target_effects`` describe the state change performed by A.  Variables are
  the entry arguments; ``<name>_post`` is the value of ``<name>`` right after A.
* ``upstream`` relations are *input-only* facts established by earlier code
  (``condition => expr``).  They may call program functions that have a
  declared signature.
* ``observers`` describe what the downstream program actually observes per
  output channel.  ``expr`` must reproduce the channel's value on every input;
  ``condition`` states when that channel is *invariant* under A.
* ``mask_guard`` states when P+ and P- agree on the whole output.
"""
from __future__ import annotations

import ast
from dataclasses import dataclass, field
from typing import Any, Dict, List

KINDS = ("target_effect", "upstream", "observer")


class ContractError(Exception):
    """The bundle is structurally invalid (not necessarily semantically wrong)."""


@dataclass
class Relation:
    id: str
    kind: str
    expr: str
    condition: str = "True"
    source_lines: List[int] = field(default_factory=list)
    rationale: str = ""
    channel: int | None = None
    role: str = ""  # upstream only: "fixed_point" or "supporting"

    def to_dict(self) -> Dict[str, Any]:
        out = {"id": self.id, "kind": self.kind, "expr": self.expr,
               "condition": self.condition, "source_lines": self.source_lines,
               "rationale": self.rationale}
        if self.channel is not None:
            out["channel"] = self.channel
        if self.role:
            out["role"] = self.role
        return out


@dataclass
class Bundle:
    target_effects: List[Relation]
    upstream: List[Relation]
    observers: List[Relation]
    mask_guard: Relation
    uncertainty: str = ""

    def all_relations(self) -> List[Relation]:
        return self.target_effects + self.upstream + self.observers + [self.mask_guard]

    def to_dict(self) -> Dict[str, Any]:
        return {
            "target_effects": [r.to_dict() for r in self.target_effects],
            "upstream": [r.to_dict() for r in self.upstream],
            "observers": [r.to_dict() for r in self.observers],
            "mask_guard": self.mask_guard.to_dict(),
            "uncertainty": self.uncertainty,
        }


def _check_expr_syntax(text: Any, where: str) -> str:
    if not isinstance(text, str) or not text.strip():
        raise ContractError(f"{where} must be a non-empty string")
    try:
        ast.parse(text.strip(), mode="eval")
    except SyntaxError as exc:
        raise ContractError(f"{where} is not a parsable expression: {exc.msg}") from None
    return text.strip()


def _lines(value: Any, where: str) -> List[int]:
    if value is None:
        return []
    if not isinstance(value, list) or not all(isinstance(v, int) and v >= 1 for v in value):
        raise ContractError(f"{where}.source_lines must be a list of positive integers")
    return value


def _relation(raw: Any, kind: str, index: int, *, need_channel: bool = False) -> Relation:
    if not isinstance(raw, dict):
        raise ContractError(f"{kind}[{index}] must be an object")
    ident = raw.get("id") or f"{kind[:1].upper()}{index}"
    if not isinstance(ident, str):
        raise ContractError(f"{kind}[{index}].id must be a string")
    expr = _check_expr_syntax(raw.get("expr"), f"{ident}.expr")
    condition = _check_expr_syntax(raw.get("condition", "True"), f"{ident}.condition")
    channel = raw.get("channel")
    if need_channel:
        if not isinstance(channel, int) or channel < 0:
            raise ContractError(f"{ident}.channel must be a non-negative integer")
    elif channel is not None and (not isinstance(channel, int) or channel < 0):
        raise ContractError(f"{ident}.channel must be a non-negative integer")
    rationale = raw.get("rationale", "")
    if not isinstance(rationale, str):
        raise ContractError(f"{ident}.rationale must be a string")
    role = raw.get("role", "supporting")
    if kind == "upstream" and role not in ("fixed_point", "supporting"):
        raise ContractError(f"{ident}.role must be 'fixed_point' or 'supporting'")
    if kind != "upstream":
        role = ""
    return Relation(id=ident, kind=kind, expr=expr, condition=condition,
                    source_lines=_lines(raw.get("source_lines"), ident),
                    rationale=rationale, channel=channel, role=role)


def parse_bundle(raw: Any, *, allow_guard_only: bool = False) -> Bundle:
    if not isinstance(raw, dict):
        raise ContractError("response must be a JSON object")
    missing = [k for k in ("target_effects", "upstream", "observers", "mask_guard")
               if k not in raw]
    if missing:
        raise ContractError(f"missing required keys: {missing}")
    for key in ("target_effects", "upstream", "observers"):
        if not isinstance(raw[key], list):
            raise ContractError(f"{key} must be a list")

    target_effects = [_relation(r, "target_effect", i) for i, r in enumerate(raw["target_effects"])]
    upstream = [_relation(r, "upstream", i) for i, r in enumerate(raw["upstream"])]
    observers = [_relation(r, "observer", i, need_channel=True) for i, r in enumerate(raw["observers"])]
    guard = _relation(raw["mask_guard"], "mask_guard", 0)

    ids = [r.id for r in target_effects + upstream + observers + [guard]]
    if len(ids) != len(set(ids)):
        raise ContractError(f"relation ids must be unique, got {ids}")
    # Several observers may describe the same channel, one per case: the
    # composer ORs their (verified) conditions.  Rejecting duplicates threw
    # away correct contracts, e.g. a two-branch observer written as two
    # relations instead of a conditional expression.
    if not target_effects and not allow_guard_only:
        raise ContractError("at least one target_effect relation is required")
    uncertainty = raw.get("uncertainty", "")
    if not isinstance(uncertainty, str):
        raise ContractError("uncertainty must be a string")
    return Bundle(target_effects, upstream, observers, guard, uncertainty)
