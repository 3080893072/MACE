"""Private sources for the three controlled masking tasks.

The ``# OP_X`` comments mark the operations whose enable/disable combinations
the *evaluator* enumerates.  They are stripped before the source is written to
``tasks.json``: the solver sees the program and the target A, never the role or
location of the other operations.

Each source is written in the MACE program subset (plain assignments, ``if``,
``return``, integer arithmetic) so the existing paired executor can produce
P+ and P- and a post-A snapshot.
"""
from __future__ import annotations

CONTROLLED = {
    "ctrl_01": {
        "kind": "controlled",
        "story": "independent masking: one downstream overwrite hides A",
        "source": '''def program(mode, x):
    v = x
    v = v + 1  # TARGET_A
    if mode == 0:  # OP_B
        v = x
    return v
''',
        "ops": {"B": 4},
        "guard": "mode == 0",
    },
    "ctrl_02": {
        "kind": "controlled",
        "story": ("cooperative masking: neither rounding alone absorbs A; "
                  "the two roundings composed do"),
        "source": '''def program(x, c, d):
    v = x
    v = v + 6  # TARGET_A
    if c == 0:  # OP_C
        v = v // 6 * 6
    if d == 0:  # OP_D
        v = v // 7 * 7
    return v
''',
        "ops": {"C": 4, "D": 6},
        "guard": "c == 0 and d == 0 and x >= 1 and x <= 5",
    },
    "ctrl_03": {
        "kind": "controlled",
        "story": "fallback masking: B and E independently absorb A, C and D cooperate",
        "source": '''def program(p, q, x, c, d):
    v = x
    v = v + 4  # TARGET_A
    if p == 0:  # OP_B
        v = x
    if q == 0:  # OP_E
        v = x
    if d == 0:  # OP_D
        v = v // 3 * 3
    if c == 0:  # OP_C
        v = v // 7 * 7
    return v
''',
        "ops": {"B": 4, "E": 6, "D": 8, "C": 10},
        "guard": ("p == 0 or q == 0 or "
                  "(c == 0 and d == 0 and x <= 4)"),
    },
}
