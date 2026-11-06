"""Oracle adapter from the pilot Verifier to the MACE search interface.

The pilot Verifier (``scripts/check_open_interface.py``) already executes the
paired P+/P- variants for an operation subset and caches the result matrix.
This adapter exposes exactly that evidence as the three-valued ``EvalRecord``
the role-separated search consumes, so the pilot tasks and the frozen v3 tasks
share one search implementation.

Only operations the Verifier can actually disable (the declared downstream
``if`` statements) are executable.  A model-proposed line that maps to another
statement is returned as ``INVALID`` -- never silently treated as False.
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Tuple

from benchmark_v3_baselines.graph_search import EvalRecord, subset_key


class PilotOracle:
    """Evaluate disabled operation sets on one frozen pilot input case."""

    def __init__(self, verifier: Any, case_id: str,
                 line_by_op: Mapping[str, int]):
        self.verifier = verifier
        self.case_id = case_id
        self.line_by_op = dict(line_by_op)
        self.calls = 0

    def _op_name(self, op_id: str) -> Optional[str]:
        line = self.line_by_op.get(op_id)
        if line is None:
            return None
        return self.verifier.op_for_line(int(line))

    def evaluate(self, disabled: Sequence[str]) -> EvalRecord:
        disabled = tuple(sorted(disabled))
        self.calls += 1
        op_names = []
        for op_id in disabled:
            name = self._op_name(op_id)
            if name is None:
                return EvalRecord(
                    disabled, "INVALID",
                    reason=f"operation {op_id!r} is not executable in the pilot")
            op_names.append(name)
        try:
            row = self.verifier.matrix(frozenset(op_names))
        except Exception as exc:  # noqa: BLE001 - evidence, never hidden
            return EvalRecord(disabled, "UNKNOWN",
                              reason=f"{type(exc).__name__}: {exc}")
        plus = row["plus"][self.case_id]["observation"]
        minus = row["minus"][self.case_id]["observation"]
        equal = plus == minus
        # Same masked predicate as the v3 executor oracle: an exception is an
        # observation, but only an equal *return* counts as masking.
        masked = bool(equal and plus and plus[0] == "return")
        exposed = not equal
        return EvalRecord(disabled, "OK", masked=masked, exposed=exposed,
                          plus=plus, minus=minus)


def searchable_cases(verifier: Any) -> list[Tuple[str, Dict[str, Any]]]:
    """Cases where A has a local effect and the original program masks it."""
    return [(cid, args) for cid, args in verifier.cases
            if verifier.base_equal[cid] and verifier.local_effect[cid]]
