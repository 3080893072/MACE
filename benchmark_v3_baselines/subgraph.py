"""A-centered program dependence subgraph (prototype).

This module is deliberately conservative.  It builds a *candidate space* and
search hints for the causal masking search; it never decides that an
operation cannot participate in masking.  Every unresolved call, dynamic
attribute access, alias or interprocedural flow is recorded as ``MAY`` or
``UNKNOWN`` rather than used for pruning.

Graph
-----
``G_P = (V, E)`` over statement nodes in the target file.  Edges carry a
kind (``data``/``control``/``alias``/``call``), a confidence
(``MUST``/``MAY``/``UNKNOWN``) and the guards (enclosing ``if``/loop
conditions) that make the edge path-sensitive.

``G_A`` is the induced graph around the target operation A: nodes reachable
from A or from the observation anchors (the target function's ``return``
statements) through the union of edge kinds.  Candidate operations are
deletable statements in that graph, ranked by graph distance and shared
state.  The ranking is a heuristic: it changes which operations are offered
to the search under a fixed candidate budget, and it is never presented as a
correctness proof.

No hidden reference, scorer, candidate universe or witness is read here.
"""
from __future__ import annotations

import ast
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

NODE_KINDS = {
    ast.Assign: "assign",
    ast.AnnAssign: "annassign",
    ast.AugAssign: "augassign",
    ast.Expr: "expr",
    ast.Return: "return",
    ast.Raise: "raise",
    ast.Assert: "assert",
    ast.Delete: "delete",
}

CONTROL_NODES = (ast.If, ast.While, ast.For, ast.AsyncFor, ast.Try, ast.With,
                 ast.AsyncWith, ast.Match)


def _span(node: ast.AST) -> Tuple[int, int]:
    return (int(getattr(node, "lineno", 0)),
            int(getattr(node, "end_lineno", node.lineno)))


def _contains(node: ast.AST, line: int) -> bool:
    first, last = _span(node)
    return first <= line <= last


def _loaded_names(node: ast.AST) -> Set[str]:
    out: Set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name) and isinstance(child.ctx, ast.Load):
            out.add(child.id)
        elif isinstance(child, ast.Attribute) and isinstance(child.ctx, ast.Load):
            out.add(child.attr)
            base = child.value
            while isinstance(base, ast.Attribute):
                out.add(base.attr)
                base = base.value
            if isinstance(base, ast.Name):
                out.add(base.id)
        elif isinstance(child, ast.Subscript) and isinstance(child.ctx, ast.Load):
            base = child.value
            while isinstance(base, ast.Attribute):
                out.add(base.attr)
                base = base.value
            if isinstance(base, ast.Name):
                out.add(base.id)
    return out


def _stored_names(node: ast.AST) -> Tuple[Set[str], Set[str]]:
    """Return (plain assignment names, attribute names) written by a node."""
    plain: Set[str] = set()
    attrs: Set[str] = set()
    targets: List[ast.AST] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = [node.target]
    elif isinstance(node, ast.Delete):
        targets = list(node.targets)
    elif isinstance(node, ast.Expr) and isinstance(node.value, ast.Call):
        call = node.value
        if isinstance(call.func, ast.Attribute) and call.func.attr in {
                "append", "extend", "update", "add", "discard", "remove",
                "pop", "clear", "setdefault", "popitem", "insert", "sort",
                "reverse", "write", "writelines"}:
            base = call.func.value
            while isinstance(base, ast.Attribute):
                attrs.add(base.attr)
                base = base.value
            if isinstance(base, ast.Name):
                plain.add(base.id)
    for target in targets:
        for child in ast.walk(target):
            if isinstance(child, ast.Name):
                plain.add(child.id)
            elif isinstance(child, ast.Attribute):
                attrs.add(child.attr)
                base = child.value
                while isinstance(base, ast.Attribute):
                    attrs.add(base.attr)
                    base = base.value
                if isinstance(base, ast.Name):
                    plain.add(base.id)
            elif isinstance(child, ast.Subscript):
                base = child.value
                while isinstance(base, ast.Attribute):
                    attrs.add(base.attr)
                    base = base.value
                if isinstance(base, ast.Name):
                    plain.add(base.id)
    return plain, attrs


def _called(node: ast.AST) -> List[Tuple[str, Optional[str], List[str]]]:
    """Return (call name, receiver, argument names) for calls inside node."""
    out: List[Tuple[str, Optional[str], List[str]]] = []
    for child in ast.walk(node):
        if not isinstance(child, ast.Call):
            continue
        name = ""
        receiver = None
        if isinstance(child.func, ast.Name):
            name = child.func.id
        elif isinstance(child.func, ast.Attribute):
            name = child.func.attr
            base = child.func.value
            if isinstance(base, ast.Name):
                receiver = base.id
            elif isinstance(base, ast.Attribute):
                receiver = base.attr
        args: List[str] = []
        for arg in list(child.args) + [kw.value for kw in child.keywords]:
            for sub in ast.walk(arg):
                if isinstance(sub, ast.Name):
                    args.append(sub.id)
        out.append((name, receiver, sorted(set(args))))
    return out


def _function_index(tree: ast.AST) -> Dict[str, List[ast.AST]]:
    index: Dict[str, List[ast.AST]] = defaultdict(list)
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            index[node.name].append(node)
    return index


def _nearest_function(functions: Sequence[ast.AST], line: int) -> Optional[ast.AST]:
    containing = [fn for fn in functions if _contains(fn, line)]
    if not containing:
        return None
    return min(containing, key=lambda fn: _span(fn)[1] - _span(fn)[0])


def _parent_map(tree: ast.AST) -> Dict[int, ast.AST]:
    parents: Dict[int, ast.AST] = {}
    for parent in ast.walk(tree):
        for child in ast.iter_child_nodes(parent):
            parents[id(child)] = parent
    return parents


def _condition_text(source_text: str, node: ast.AST) -> str:
    if isinstance(node, ast.If):
        segment = ast.get_source_segment(source_text, node.test)
    elif isinstance(node, (ast.While, ast.For, ast.AsyncFor)):
        target = node.test if isinstance(node, ast.While) else node.iter
        segment = ast.get_source_segment(source_text, target)
    elif isinstance(node, (ast.With, ast.AsyncWith)):
        segment = ", ".join(ast.get_source_segment(source_text, item.context_expr) or ""
                            for item in node.items)
    elif isinstance(node, ast.Try):
        segment = "try"
    elif isinstance(node, ast.Match):
        segment = ast.get_source_segment(source_text, node.subject)
    else:
        segment = type(node).__name__
    return " ".join((segment or type(node).__name__).split())


def _guards(source_text: str, node: ast.AST,
            parents: Dict[int, ast.AST]) -> List[str]:
    guards: List[str] = []
    parent = parents.get(id(node))
    while parent is not None:
        if isinstance(parent, CONTROL_NODES):
            guards.append(_condition_text(source_text, parent))
        parent = parents.get(id(parent))
    return list(reversed(guards))


def _class_scopes(tree: ast.AST) -> Dict[int, Optional[str]]:
    """Map each function node to its enclosing class (None at module level).

    Method names are not unique across classes in a large module.  Matching
    callers and callees by bare name would pull unrelated ``__init__`` or
    ``get`` methods into the graph, so selection is scoped to the same
    class (plus module-level helpers, which are visible everywhere).
    """
    scopes: Dict[int, Optional[str]] = {}

    def visit(node: ast.AST, scope: Optional[str]) -> None:
        for child in ast.iter_child_nodes(node):
            if isinstance(child, (ast.FunctionDef, ast.AsyncFunctionDef)):
                scopes[id(child)] = scope
                visit(child, scope)
            elif isinstance(child, ast.ClassDef):
                visit(child, child.name)
            else:
                visit(child, scope)

    visit(tree, None)
    return scopes


def _scoped(scopes: Dict[int, Optional[str]], caller: ast.AST,
            callee: ast.AST) -> bool:
    caller_scope = scopes.get(id(caller))
    callee_scope = scopes.get(id(callee))
    return callee_scope is None or callee_scope == caller_scope


def _select_functions(tree: ast.AST, target: Dict[str, Any],
                      max_functions: int = 16) -> Tuple[List[ast.AST], List[str]]:
    index = _function_index(tree)
    scopes = _class_scopes(tree)
    root = None
    for fn in ast.walk(tree):
        if isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)) and \
                _contains(fn, int(target["line"])):
            if root is None or (_span(fn)[1] - _span(fn)[0]) < (
                    _span(root)[1] - _span(root)[0]):
                root = fn
    if root is None:
        return [], ["target line is not inside a function"]
    selected: Dict[Tuple[str, int, int], ast.AST] = {
        (root.name, *_span(root)): root}
    notes: List[str] = []

    def forward(fn: ast.AST) -> None:
        for name, _, _ in _called(fn):
            for candidate in index.get(name, []):
                key = (candidate.name, *_span(candidate))
                if key in selected:
                    continue
                if not _scoped(scopes, fn, candidate):
                    notes.append(
                        f"ambiguous call {name} from {getattr(fn, 'name', '?')} "
                        f"left as MAY/UNKNOWN (different class scope)")
                    continue
                if len(selected) >= max_functions:
                    notes.append(f"function cap reached at {name}")
                    return
                selected[key] = candidate
                forward(candidate)

    forward(root)

    # Backward callers: functions that call the root or any selected function.
    def calls_selected(fn: ast.AST) -> bool:
        called = {name for name, _, _ in _called(fn)}
        for selected_fn in selected.values():
            if selected_fn.name in called and _scoped(scopes, fn, selected_fn):
                return True
        return False

    changed = True
    depth = 0
    while changed and depth < 2 and len(selected) < max_functions:
        changed = False
        for fn in ast.walk(tree):
            if not isinstance(fn, (ast.FunctionDef, ast.AsyncFunctionDef)):
                continue
            key = (fn.name, *_span(fn))
            if key in selected:
                continue
            if calls_selected(fn):
                selected[key] = fn
                changed = True
                if len(selected) >= max_functions:
                    notes.append("backward caller cap reached")
                    break
        depth += 1

    functions = sorted(selected.values(), key=lambda fn: _span(fn))
    return functions, notes


def _node_dict(source_lines: Sequence[str], node: ast.AST, file: str,
               function: Optional[ast.AST], parents: Dict[int, ast.AST],
               source_text: str, target_line: int) -> Dict[str, Any]:
    # Compound control nodes must not inherit the defs/uses of their bodies:
    # doing so would make every body statement look adjacent to A and would
    # collapse the path structure the subgraph is supposed to expose.  A
    # control node owns only its test/iterator expressions.
    if isinstance(node, CONTROL_NODES):
        plain: Set[str] = set()
        attrs: Set[str] = set()
        if isinstance(node, (ast.If, ast.While)):
            expr: Optional[ast.AST] = node.test
        elif isinstance(node, (ast.For, ast.AsyncFor)):
            expr = node.iter
        elif isinstance(node, (ast.With, ast.AsyncWith)):
            expr = node.items[0].context_expr if node.items else None
        elif isinstance(node, ast.Match):
            expr = node.subject
        else:
            expr = None
        uses = sorted(_loaded_names(expr)) if expr is not None else []
        calls = _called(expr) if expr is not None else []
    else:
        plain, attrs = _stored_names(node)
        calls = _called(node)
        uses = sorted(_loaded_names(node) - plain)
    first, last = _span(node)
    kind = NODE_KINDS.get(type(node), type(node).__name__)
    contains_target = first <= target_line <= last
    deletable = (kind in NODE_KINDS.values() and not contains_target)
    if isinstance(node, ast.Expr) and isinstance(node.value, ast.Constant):
        deletable = False  # docstring / bare literal
    if isinstance(node, ast.Pass):
        deletable = False
    return {
        "id": f"{file}:{first}-{last}",
        "file": file,
        "first_line": first,
        "last_line": last,
        "kind": kind,
        "code": "\n".join(source_lines[first - 1:last]),
        "function": function.name if function is not None else "<module>",
        "contains_target": contains_target,
        "deletable": deletable,
        "defs": sorted(plain),
        "attr_defs": sorted(attrs),
        "uses": uses,
        "calls": [name for name, _, _ in calls if name],
        "guards": _guards(source_text, node, parents),
        "in_loop": any(isinstance(anc, (ast.For, ast.AsyncFor, ast.While))
                       for anc in _ancestors(node, parents)),
    }


def _ancestors(node: ast.AST, parents: Dict[int, ast.AST]) -> List[ast.AST]:
    out: List[ast.AST] = []
    parent = parents.get(id(node))
    while parent is not None:
        out.append(parent)
        parent = parents.get(id(parent))
    return out


def _add_edge(edges: List[Dict[str, Any]], src: str, dst: str, kind: str,
              confidence: str, evidence: str, guard: str = "") -> None:
    if src == dst:
        return
    edges.append({"src": src, "dst": dst, "kind": kind,
                  "confidence": confidence, "evidence": evidence,
                  "guard": guard})


def _usable_builtin(name: str) -> bool:
    return name in {
        "len", "str", "int", "float", "bool", "list", "dict", "set", "tuple",
        "repr", "sorted", "min", "max", "sum", "any", "all", "filter", "map",
        "f", "isinstance", "getattr", "setattr", "hasattr", "print", "open",
        "range", "enumerate", "zip", "iter", "next", "super", "type", "bytes",
    }


def build(task: Dict[str, Any], source_text: str,
          max_functions: int = 16) -> Dict[str, Any]:
    """Build the A-centered dependence subgraph for one task."""
    file = task.get("file") or task["target_operation"]["file"]
    target_line = int(task["target_operation"]["line"])
    source_lines = source_text.splitlines()
    tree = ast.parse(source_text)
    parents = _parent_map(tree)
    functions, notes = _select_functions(tree, task["target_operation"],
                                         max_functions=max_functions)
    selected_ids = {id(fn) for fn in functions}
    function_by_node: Dict[int, ast.AST] = {}
    for fn in functions:
        for node in ast.walk(fn):
            if isinstance(node, ast.stmt):
                function_by_node[id(node)] = _nearest_function(functions, _span(node)[0]) or fn

    nodes: Dict[str, Dict[str, Any]] = {}
    ast_by_id: Dict[str, ast.AST] = {}
    for fn in functions:
        for node in ast.walk(fn):
            if not isinstance(node, ast.stmt):
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                continue
            first, last = _span(node)
            if first <= 0:
                continue
            # Nested functions are represented through their own statements,
            # which are already reached by ast.walk.
            info = _node_dict(source_lines, node, file,
                              function_by_node.get(id(node)), parents,
                              source_text, target_line)
            nodes.setdefault(info["id"], info)
            ast_by_id.setdefault(info["id"], node)

    # The target statement may not be in `nodes` if it lives outside the
    # selected functions; add it explicitly as a non-deletable anchor.
    target_node = _target_stmt(ast_by_id, target_line)
    if target_node is not None:
        info = _node_dict(source_lines, target_node, file,
                          function_by_node.get(id(target_node)), parents,
                          source_text, target_line)
        nodes.setdefault(info["id"], info)
        target_id = info["id"]
    else:
        # Fall back to a synthetic anchor so the graph is still usable.
        target_id = f"{file}:{target_line}-{target_line}"
        nodes[target_id] = {
            "id": target_id, "file": file, "first_line": target_line,
            "last_line": target_line, "kind": "target", "code": "",
            "function": task["target_operation"].get("function", ""),
            "contains_target": True, "deletable": False, "defs": [],
            "attr_defs": [], "uses": [], "calls": [], "guards": [],
            "in_loop": False}
        ast_by_id[target_id] = ast.parse("pass").body[0]

    edges: List[Dict[str, Any]] = []

    # ---- data dependences inside a function ------------------------------
    by_function: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for info in nodes.values():
        by_function[info["function"]].append(info)
    for fname, items in by_function.items():
        # Only simple statements own data/alias facts; control nodes own
        # control edges (added below) and must not duplicate body facts.
        items = sorted((item for item in items
                        if item["kind"] in NODE_KINDS.values()),
                       key=lambda x: (x["first_line"], x["last_line"]))
        for name in sorted({n for item in items for n in item["defs"]}):
            defs = [item for item in items if name in item["defs"]]
            uses = [item for item in items if name in item["uses"]]
            for d in defs:
                for u in uses:
                    if u["id"] == d["id"]:
                        continue
                    if (u["first_line"], u["last_line"]) > (d["first_line"], d["last_line"]):
                        _add_edge(edges, d["id"], u["id"], "data", "MUST",
                                  f"def-use:{name}")
                    elif any(item["in_loop"] for item in items):
                        _add_edge(edges, d["id"], u["id"], "data", "MAY",
                                  f"loop-carried def-use:{name}")
            # Every definition of a name competes with every later one; a
            # pairwise edge is what lets the graph see a fallback assignment
            # that is not the immediately preceding definition of the same
            # variable.
            for index, a in enumerate(defs):
                for b in defs[index + 1:]:
                    _add_edge(edges, a["id"], b["id"], "data", "MUST",
                              f"redefinition:{name}")
        for attr in sorted({a for item in items for a in item["attr_defs"]}):
            defs = [item for item in items if attr in item["attr_defs"]]
            uses = [item for item in items
                    if attr in item["uses"] or attr in item["attr_defs"]]
            for d in defs:
                for u in uses:
                    if u["id"] != d["id"]:
                        _add_edge(edges, d["id"], u["id"], "alias", "MAY",
                                  f"attribute alias:.{attr}")

    # ---- control dependences --------------------------------------------
    control_nodes = [node for node in ast.walk(tree)
                     if isinstance(node, CONTROL_NODES)
                     and id(node) in function_by_node]
    for control in control_nodes:
        cid = f"{file}:{_span(control)[0]}-{_span(control)[1]}"
        if cid not in nodes:
            continue
        for node in ast.walk(control):
            if node is control or not isinstance(node, ast.stmt):
                continue
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef,
                                 ast.ClassDef)):
                continue
            nid = f"{file}:{_span(node)[0]}-{_span(node)[1]}"
            if nid in nodes:
                _add_edge(edges, cid, nid, "control", "MUST",
                          "control-dependence",
                          _condition_text(source_text, control))

    # ---- aliases from simple assignments and mutating calls ---------------
    for info in nodes.values():
        if info["kind"] not in NODE_KINDS.values():
            continue
        node = ast_by_id.get(info["id"])
        if node is None:
            continue
        if isinstance(node, ast.Assign) and len(node.targets) == 1 and \
                isinstance(node.targets[0], ast.Name):
            rhs_names = _loaded_names(node.value)
            for other in nodes.values():
                if other["function"] != info["function"]:
                    continue
                if other["id"] == info["id"]:
                    continue
                if rhs_names & set(other["defs"]) or rhs_names & set(other["uses"]):
                    _add_edge(edges, info["id"], other["id"], "alias", "MAY",
                              "assignment alias")
        for name, receiver, args in _called(node):
            if receiver is None and not name:
                continue
            touched = set(args)
            if receiver:
                touched.add(receiver)
            for other in nodes.values():
                if other["id"] == info["id"]:
                    continue
                if touched & (set(other["defs"]) | set(other["uses"])):
                    _add_edge(edges, info["id"], other["id"], "alias", "MAY",
                              f"call may mutate:{name}")

    # ---- interprocedural call edges -------------------------------------
    call_index = _function_index(tree)
    for info in nodes.values():
        if info["kind"] not in NODE_KINDS.values():
            continue
        node = ast_by_id.get(info["id"])
        if node is None:
            continue
        for name, receiver, args in _called(node):
            if not name:
                continue
            callees = [fn for fn in call_index.get(name, [])
                       if id(fn) in selected_ids]
            if not callees:
                if not _usable_builtin(name):
                    _add_edge(edges, info["id"], f"UNKNOWN:{name}", "call",
                              "UNKNOWN", f"unresolved call:{name}")
                continue
            for callee in callees:
                first, last = _span(callee)
                for child in ast.walk(callee):
                    if not isinstance(child, ast.stmt):
                        continue
                    cid = f"{file}:{_span(child)[0]}-{_span(child)[1]}"
                    if cid in nodes:
                        _add_edge(edges, info["id"], cid, "call", "MAY",
                                  f"call:{name}")
                ret_id = None
                for child in ast.walk(callee):
                    if isinstance(child, ast.Return):
                        rid = f"{file}:{_span(child)[0]}-{_span(child)[1]}"
                        if rid in nodes:
                            _add_edge(edges, rid, info["id"], "call", "MAY",
                                      f"return-from:{name}")
                _ = ret_id

    # ---- anchors, distances and candidate ranking ------------------------
    anchors = {target_id}
    for info in nodes.values():
        if info["kind"] == "return" and info["function"] == \
                nodes.get(target_id, {}).get("function"):
            anchors.add(info["id"])
    dist_a = _dijkstra(nodes, edges, {target_id})
    dist_o = _dijkstra(nodes, edges, anchors)
    target_vars = set()
    target_attrs = set()
    target_defs: Set[str] = set()
    if target_id in nodes:
        target_vars = set(nodes[target_id]["defs"]) | set(nodes[target_id]["uses"])
        target_attrs = set(nodes[target_id]["attr_defs"])
        target_defs = set(nodes[target_id]["defs"])

    candidates: List[Dict[str, Any]] = []
    for info in nodes.values():
        if not info["deletable"]:
            continue
        da = dist_a.get(info["id"], float("inf"))
        do = dist_o.get(info["id"], float("inf"))
        shared = len((set(info["defs"]) | set(info["uses"])) & target_vars)
        shared += len(set(info["attr_defs"]) & target_attrs)
        writes_target = len(set(info["defs"]) & target_defs)
        same_function = int(info["function"] == nodes[target_id]["function"])
        unknown_calls = sum(1 for name in info["calls"]
                            if name and name not in call_index)
        score = 0.0
        if da != float("inf"):
            score += 1.0 / (1.0 + da)
        if do != float("inf"):
            score += 0.5 / (1.0 + do)
        score += 0.25 * min(shared, 3)
        # Direct redefinition of the variable A writes is the strongest
        # single data edge available; prefer it over other shared reads.
        score += 0.25 * min(writes_target, 1)
        score += 0.10 * same_function
        score -= 0.05 * min(unknown_calls, 2)
        path = _shortest_path(nodes, edges, target_id, info["id"])
        candidates.append({
            **{k: info[k] for k in ("id", "file", "first_line", "last_line",
                                    "kind", "code", "function", "defs",
                                    "attr_defs", "uses", "calls", "guards")},
            "score": round(score, 6),
            "distance_to_A": None if da == float("inf") else da,
            "distance_to_observation": None if do == float("inf") else do,
            "shared_state": shared,
            "writes_target": writes_target,
            "same_function": bool(same_function),
            "path": path,
        })
    candidates.sort(key=lambda x: (-x["score"], x["first_line"],
                                   x["last_line"]))

    by_kind: Dict[str, int] = defaultdict(int)
    by_conf: Dict[str, int] = defaultdict(int)
    for edge in edges:
        by_kind[edge["kind"]] += 1
        by_conf[edge["confidence"]] += 1
    unresolved = sorted({edge["dst"] for edge in edges
                         if edge["confidence"] == "UNKNOWN"})
    return {
        "schema": "mace-a-centered-subgraph-0.1",
        "file": file,
        "target": {
            "id": target_id,
            "line": target_line,
            "function": nodes.get(target_id, {}).get("function", ""),
            "defs": nodes.get(target_id, {}).get("defs", []),
            "uses": nodes.get(target_id, {}).get("uses", []),
            "attr_defs": nodes.get(target_id, {}).get("attr_defs", []),
        },
        "functions": [{"name": fn.name, "first_line": _span(fn)[0],
                       "last_line": _span(fn)[1]} for fn in functions],
        "nodes": sorted(nodes.values(), key=lambda x: (x["first_line"],
                                                       x["last_line"])),
        "edges": edges,
        "candidates": candidates,
        "stats": {
            "nodes": len(nodes),
            "edges": len(edges),
            "edge_kinds": dict(sorted(by_kind.items())),
            "edge_confidence": dict(sorted(by_conf.items())),
            "deletable": sum(1 for info in nodes.values() if info["deletable"]),
            "unresolved_calls": unresolved,
        },
        "unknowns": notes + [
            f"unresolved call: {name}" for name in unresolved],
        "discovery_rule": (
            "target file functions reachable forward from A's function "
            "(same-name calls, bounded), plus up to two levels of backward "
            "callers; statement nodes; data/control/alias/call edges; "
            "unresolved flows retained as MAY/UNKNOWN; candidates ranked by "
            "graph distance to A and to return anchors, shared state and "
            "same-function membership; top-k selection is a heuristic"),
    }


def _target_stmt(ast_by_id: Dict[str, ast.AST], line: int) -> Optional[ast.AST]:
    best = None
    for node in ast_by_id.values():
        if isinstance(node, ast.stmt) and int(getattr(node, "lineno", -1)) == line:
            if best is None or _span(node)[1] < _span(best)[1]:
                best = node
    return best


def _edge_weights() -> Dict[str, float]:
    return {"data": 1.0, "control": 0.7, "alias": 1.2, "call": 1.5}


def _dijkstra(nodes: Dict[str, Dict[str, Any]], edges: Sequence[Dict[str, Any]],
              sources: Set[str]) -> Dict[str, float]:
    adjacency: Dict[str, List[Tuple[str, float]]] = defaultdict(list)
    weights = _edge_weights()
    for edge in edges:
        src, dst = edge["src"], edge["dst"]
        if src not in nodes or dst not in nodes:
            continue
        weight = weights.get(edge["kind"], 2.0)
        if edge["confidence"] == "MAY":
            weight *= 1.2
        elif edge["confidence"] == "UNKNOWN":
            weight *= 1.5
        adjacency[src].append((dst, weight))
        adjacency[dst].append((src, weight))
    dist: Dict[str, float] = {}
    frontier: List[Tuple[float, str]] = []
    for source in sources:
        if source in nodes:
            dist[source] = 0.0
            frontier.append((0.0, source))
    import heapq

    heapq.heapify(frontier)
    while frontier:
        cost, node = heapq.heappop(frontier)
        if cost > dist.get(node, float("inf")):
            continue
        for nxt, weight in adjacency.get(node, []):
            candidate = cost + weight
            if candidate < dist.get(nxt, float("inf")):
                dist[nxt] = candidate
                heapq.heappush(frontier, (candidate, nxt))
    return dist


def _shortest_path(nodes: Dict[str, Dict[str, Any]],
                   edges: Sequence[Dict[str, Any]], source: str,
                   destination: str) -> List[Dict[str, Any]]:
    if source == destination:
        return []
    adjacency: Dict[str, List[Tuple[str, Dict[str, Any], float]]] = defaultdict(list)
    weights = _edge_weights()
    for edge in edges:
        if edge["src"] not in nodes or edge["dst"] not in nodes:
            continue
        weight = weights.get(edge["kind"], 2.0)
        adjacency[edge["src"]].append((edge["dst"], edge, weight))
        adjacency[edge["dst"]].append((edge["src"], edge, weight))
    import heapq

    dist = {source: 0.0}
    parent: Dict[str, Tuple[str, Dict[str, Any]]] = {}
    frontier = [(0.0, source)]
    while frontier:
        cost, node = heapq.heappop(frontier)
        if node == destination:
            break
        if cost > dist.get(node, float("inf")):
            continue
        for nxt, edge, weight in adjacency.get(node, []):
            candidate = cost + weight
            if candidate < dist.get(nxt, float("inf")):
                dist[nxt] = candidate
                parent[nxt] = (node, edge)
                heapq.heappush(frontier, (candidate, nxt))
    if destination not in parent:
        return []
    path: List[Dict[str, Any]] = []
    current = destination
    while current != source:
        previous, edge = parent[current]
        path.append({"from": previous, "to": current,
                     "kind": edge["kind"],
                     "confidence": edge["confidence"],
                     "evidence": edge["evidence"],
                     "guard": edge.get("guard", "")})
        current = previous
    return list(reversed(path))


def candidate_selection(graph: Dict[str, Any], max_ops: int,
                        min_score: float = 0.0) -> Dict[str, Any]:
    """Select candidates and expose any budget truncation.

    Truncation is a resource limit, not an evidence-based prune: omitted
    nodes stay in ``graph["candidates"]`` and are reported, so a later run
    with a larger budget can recover them.
    """
    eligible = [item for item in graph.get("candidates", [])
                if item["score"] >= min_score]
    selected = eligible[:max_ops]
    omitted = eligible[max_ops:]
    return {
        "ops": [{
            "id": item["id"], "file": item["file"],
            "first_line": item["first_line"], "last_line": item["last_line"],
            "kind": item["kind"], "code": item["code"],
            "graph_score": item["score"],
            "graph_path": item["path"],
            "graph_function": item["function"],
        } for item in selected],
        "eligible": len(eligible),
        "selected": len(selected),
        "truncated": bool(omitted),
        "omitted": [{
            "id": item["id"], "first_line": item["first_line"],
            "score": item["score"],
        } for item in omitted],
    }


def candidate_ops(graph: Dict[str, Any], max_ops: int,
                  min_score: float = 0.0) -> List[Dict[str, Any]]:
    """Select at most ``max_ops`` candidates; never a completeness claim."""
    return candidate_selection(graph, max_ops, min_score)["ops"]
