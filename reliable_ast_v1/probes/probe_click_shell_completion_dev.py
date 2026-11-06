"""Dev probe: exercise click.shell_completion._resolve_context via ShellComplete.

Payload: {"args": ["get","full"], "incomplete": ""}.
The observation is the list of completion values from the public API.
"""
from __future__ import annotations
import json, sys
from click.core import Command, Group, Option
from click.shell_completion import ShellComplete

def _cli():
    return Group("cli", chain=True, commands=[
        Command("set", params=[Option(["-y"])]),
        Command("start"),
        Group("get", commands=[Command("full")]),
    ])

def main() -> int:
    payload = json.load(sys.stdin)
    try:
        comp = ShellComplete(_cli(), {}, "cli", "_CLICK_COMPLETE")
        items = comp.get_completions(list(payload.get("args", [])), payload.get("incomplete", ""))
        observation = {"outcome": "return", "values": [c.value for c in items]}
    except BaseException as exc:
        observation = {"outcome": "raise", "type": type(exc).__name__, "message": str(exc)[:300]}
    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
    return 0

if __name__ == "__main__":
    raise SystemExit(main())
