"""Difference propagation over execution traces.

The bounded checker answers *whether* the two versions agree on an input.  This
module answers *where the difference stops*: it compares the locals recorded
line by line in P+ and P- for one input and reports

* the lines on which some variable still differs,
* the first line after which every previously differing variable agrees again
  (the statement that absorbed the difference),
* whether the two versions even executed the same lines (control divergence).

Everything here is a statement about actual executions, not a proof: a line
where a difference disappears is evidence of masking on that input, not a
guarantee on every input.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence


def _snapshots(trace: Sequence[Dict[str, Any]]) -> Dict[int, Dict[str, Any]]:
    """line -> last recorded locals at that line."""
    out: Dict[int, Dict[str, Any]] = {}
    for record in trace:
        out[int(record["line"])] = dict(record.get("locals") or {})
    return out


def diff_traces(trace_plus: Sequence[Dict[str, Any]],
                trace_minus: Sequence[Dict[str, Any]],
                outputs_equal: Optional[bool] = None) -> Dict[str, Any]:
    plus = _snapshots(trace_plus)
    minus = _snapshots(trace_minus)
    common = sorted(set(plus) & set(minus))
    only_plus = sorted(set(plus) - set(minus))
    only_minus = sorted(set(minus) - set(plus))

    diff_lines: Dict[str, List[str]] = {}
    for line in common:
        names = [name for name in sorted(set(plus[line]) & set(minus[line]))
                 if plus[line][name] != minus[line][name]]
        if names:
            diff_lines[str(line)] = names

    diff_positions = sorted(int(line) for line in diff_lines)
    equalized: List[Dict[str, Any]] = []
    for index, line in enumerate(common):
        for name in diff_lines.get(str(line), []):
            for later in common[index + 1:]:
                if name not in minus.get(later, {}):
                    continue
                if minus[later][name] == plus[later][name]:
                    equalized.append({"name": name, "differs_at": line,
                                      "equal_at": later})
                    break
    # A name that first appears on a line whose predecessor already differed was
    # computed *from* a differing value and came out equal: that statement is
    # the one that loses the difference on this input.
    absorbed: List[Dict[str, Any]] = []
    for index in range(1, len(common)):
        line, previous = common[index], common[index - 1]
        differing_names = diff_lines.get(str(previous))
        if not differing_names:
            continue
        for name in plus[line]:
            if name in minus[previous] or name not in minus[line]:
                continue
            if plus[line][name] == minus[line][name]:
                absorbed.append({"name": name, "computed_at": previous,
                                 "observed_at": line, "from_differing": differing_names})
    # The same thing can happen to an existing variable: the statement that
    # *overwrites* it recomputes from equal inputs and the difference is gone.
    # Detect that by requiring the value to have been recomputed at the line
    # where it becomes equal again.
    seen = {(a["name"], a["computed_at"]) for a in absorbed}
    for item in equalized:
        name, differs_at, equal_at = item["name"], item["differs_at"], item["equal_at"]
        if (name, equal_at) in seen:
            continue
        recomputed = (plus[equal_at].get(name) != plus[differs_at].get(name)
                      or minus[equal_at].get(name) != minus[differs_at].get(name))
        if recomputed:
            absorbed.append({"name": name, "computed_at": equal_at,
                             "observed_at": equal_at,
                             "from_differing": diff_lines.get(str(differs_at), [])})
            seen.add((name, equal_at))
    absorbed.sort(key=lambda a: a["computed_at"])
    return {
        "absorbed": absorbed,
        "diff_lines": diff_lines,
        "first_diff_line": diff_positions[0] if diff_positions else None,
        "last_diff_line": diff_positions[-1] if diff_positions else None,
        "equalized": equalized,
        "lines_only_in_plus": only_plus,
        "lines_only_in_minus": only_minus,
        "control_divergence": bool(only_plus or only_minus),
        "outputs_equal": outputs_equal,
    }
