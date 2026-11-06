"""MACE semantic-contract hints for operation candidates.

This module reuses ``mace.contracts.parse_bundle`` to read an *existing* MACE
bundle.  It does not run MACE, does not call a model, and does not invent a new
algorithm.  A contract is treated only as a proposal source:

* ``target_effects`` / ``observers`` / ``upstream`` / ``mask_guard`` contribute
  their ``source_lines`` as candidate locations;
* execution by the independent verifier decides whether a relation is real;
* line citations alone never confirm a masking operation.

The prior Full MACE bundles are used only for the old controlled fixtures.
For real-source tasks with no recorded bundle, contract assistance is marked
unavailable rather than fabricated.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence

from mace.contracts import Bundle, ContractError, parse_bundle


@dataclass
class ContractHint:
    path: str
    available: bool
    status: str = "UNAVAILABLE"
    reason: str = ""
    line_refs: Dict[int, List[str]] = field(default_factory=dict)
    relation_statuses: Dict[str, str] = field(default_factory=dict)
    relation_counts: Dict[str, int] = field(default_factory=dict)
    uncertainty: str = ""

    @property
    def lines(self) -> List[int]:
        return sorted(self.line_refs)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "path": self.path,
            "available": self.available,
            "status": self.status,
            "reason": self.reason,
            "line_refs": {str(k): v for k, v in sorted(self.line_refs.items())},
            "cited_lines": self.lines,
            "relation_statuses": dict(sorted(self.relation_statuses.items())),
            "relation_counts": dict(sorted(self.relation_counts.items())),
            "uncertainty": self.uncertainty,
            "semantic_fields_used": [
                "target_effects", "upstream", "observers", "mask_guard",
            ],
            "confirmation": "not_by_contract; execution_verifier_only",
        }


def _bundle_sections(bundle: Bundle):
    return [
        ("target_effects", bundle.target_effects),
        ("upstream", bundle.upstream),
        ("observers", bundle.observers),
        ("mask_guard", [bundle.mask_guard]),
    ]


def load_contract(path: str | Path) -> ContractHint:
    """Load one recorded MACE bundle as candidate-line hints.

    Missing files are a normal, reported state: no contract was recorded for
    that task.  Malformed bundles are ``INVALID`` and contribute no lines.
    """
    p = Path(path)
    display = str(p)
    if not p.exists():
        return ContractHint(display, False, reason="contract file not found")
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        return ContractHint(display, False, status="INVALID",
                            reason=f"{type(exc).__name__}: {exc}")
    candidate = raw.get("final_bundle") if isinstance(raw, dict) else None
    if candidate is None:
        candidate = raw
    try:
        bundle = parse_bundle(candidate, allow_guard_only=True)
    except ContractError as exc:
        return ContractHint(display, False, status="INVALID",
                            reason=f"ContractError: {exc}")

    line_refs: Dict[int, List[str]] = {}
    counts: Dict[str, int] = {}
    for section, relations in _bundle_sections(bundle):
        counts[section] = len(relations)
        for rel in relations:
            for line in rel.source_lines:
                line_refs.setdefault(int(line), []).append(f"{rel.id}:{section}")

    statuses: Dict[str, str] = {}
    report = raw.get("final_report") if isinstance(raw, dict) else None
    if isinstance(report, dict):
        for rel in report.get("relations") or []:
            if isinstance(rel, dict) and rel.get("id"):
                statuses[str(rel["id"])] = str(rel.get("status", "UNKNOWN"))

    return ContractHint(
        path=display,
        available=True,
        status=str(raw.get("status", "UNKNOWN")) if isinstance(raw, dict) else "UNKNOWN",
        reason="parsed",
        line_refs=line_refs,
        relation_statuses=statuses,
        relation_counts=counts,
        uncertainty=str(bundle.uncertainty),
    )


def contract_meta(hint: ContractHint) -> Dict[str, Any]:
    data = hint.to_dict()
    data["line_refs"] = {str(k): v for k, v in hint.line_refs.items()}
    return data


def default_contract_path(task_id: str, root: str | Path) -> Optional[Path]:
    """Path of the existing Full MACE normalized run for an old fixture."""
    root = Path(root)
    path = (root / "benchmark_open_v1" / "interface" / "runs" / task_id
            / "full_mace_norm" / "mace_seed42.json")
    return path if path.exists() else None


def load_default_contract(task_id: str, root: str | Path) -> ContractHint:
    path = default_contract_path(task_id, root)
    if path is None:
        return ContractHint(
            f"benchmark_open_v1/interface/runs/{task_id}/full_mace_norm/mace_seed42.json",
            False, reason="no recorded MACE contract for this task")
    return load_contract(path)
