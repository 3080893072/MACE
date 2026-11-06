"""Observation probe for networkx/readwrite/gexf.py:448 (edge slices)."""
import io
import json
import xml.etree.ElementTree as ET

import networkx as nx


def write(directed, with_slices):
    G = nx.DiGraph() if directed else nx.Graph()
    if with_slices:
        G.add_edge(1, 2, slices=[(1, 2), (3, 4)])
    else:
        G.add_edge(1, 2, weight=1.5)
    buf = io.BytesIO()
    try:
        nx.write_gexf(G, buf, version="1.1draft")
    except Exception as exc:  # noqa: BLE001 - observation, not failure
        return {"error": type(exc).__name__ + ": " + str(exc)}
    root = ET.fromstring(buf.getvalue().decode())
    edge = next((e for e in root.iter()
                 if e.tag.split("}")[-1] == "edge"), None)
    if edge is None:
        return {"edge": None}
    return {"children": [[c.tag.split("}")[-1], dict(c.attrib)]
                         for c in edge]}


print(json.dumps({
    "mask_undirected_slices": write(False, True),
    "expose_directed_slices": write(True, True),
    "control_undirected_no_slices": write(False, False),
    "control_directed_no_slices": write(True, False),
}, ensure_ascii=False))
