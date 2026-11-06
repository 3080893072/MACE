"""Observation probe (generated)."""
import json

import tabulate as _tabulate
def render(rows):
    return {"out": _tabulate.tabulate(rows, tablefmt="plain", colalign=("right",))}

def observe(value):
    try:
        return render(value)
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}

print(json.dumps({
    "nc_space_padded": observe([['  a  '], ['b']]),
    "nc_tab_padded": observe([['\ta\t'], ['b']]),
    "nc_mixed_padded": observe([[' \ta\t '], ['b']]),
}, ensure_ascii=False))
