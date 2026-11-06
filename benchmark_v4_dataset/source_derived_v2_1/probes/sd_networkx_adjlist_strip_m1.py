"""Observation probe (generated)."""
import json

import networkx as nx
from networkx.readwrite.adjlist import parse_adjlist

def observe(value):
    try:
        graph = parse_adjlist([value])
        return {"nodes": sorted(map(str, graph.nodes())),
                "edges": sorted(map(str, graph.edges()))}
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}

print(json.dumps({
    "mask_space_padding": observe('  a b'),
    "expose_tab_padding": observe('\ta b'),
    "control_plain": observe('a b'),
}, ensure_ascii=False))
