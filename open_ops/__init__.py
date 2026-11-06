"""Minimal operation-level masking discovery.

This package is intentionally separate from ``mace`` and from the benchmark
scorer.  It is a deterministic baseline: candidate operations come from a
backward slice of the target function, interventions are executed on P+/P-,
and relations are read off the resulting subset matrix.  It does not consume
private operation labels and it does not use an LLM.
"""
from .discover import (
    DiscoveryResult,
    Operation,
    Relation,
    discover,
    discover_expanded,
    find_candidates,
    find_candidates_expanded,
    synthesize_condition,
    to_submission,
)

__all__ = [
    "DiscoveryResult",
    "Operation",
    "Relation",
    "discover",
    "discover_expanded",
    "find_candidates",
    "find_candidates_expanded",
    "synthesize_condition",
    "to_submission",
]
