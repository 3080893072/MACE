"""Baseline C: deterministic AST candidate discovery.

The rule is fixed and public-source only:

1. Locate the target function that contains the published target line.
2. Follow same-file calls from that function (including ``self.method``) to
   get a bounded reachable function set.
3. Collect every assignment and every ``if`` block inside those functions.
4. Keep operations that touch a variable named on either side of the target
   operation (a bounded dataflow filter), or blocks that contain such a
   write.
5. Rank them by how often an intervention actually changes an observation on
   the public input grid, and keep at most ``max_ops``.

No hidden candidate universe, reference relation or witness is consulted.
"""
from __future__ import annotations

import ast
from typing import Any, Dict, Iterable, List, Sequence, Set, Tuple


def _function_index(tree: ast.AST) -> Dict[str, List[ast.AST]]:
    index: Dict[str, List[ast.AST]] = {}
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            index.setdefault(node.name, []).append(node)
    return index


def _span(node: ast.AST) -> Tuple[int, int]:
    return (int(node.lineno), int(getattr(node, "end_lineno", node.lineno)))


def _contains(node: ast.AST, line: int) -> bool:
    first, last = _span(node)
    return first <= line <= last


def _names(node: ast.AST) -> Set[str]:
    out: Set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Name):
            out.add(child.id)
        elif isinstance(child, ast.alias):
            out.add(child.asname or child.name.split(".")[0])
    return out


def _lhs_names(node: ast.AST) -> Set[str]:
    out: Set[str] = set()
    targets: List[ast.AST] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = [node.target]
    for target in targets:
        for child in ast.walk(target):
            if isinstance(child, ast.Name):
                out.add(child.id)
            elif isinstance(child, ast.Attribute):
                out.add(child.attr)
    return out


def _rhs_names(node: ast.AST) -> Set[str]:
    if isinstance(node, ast.Assign):
        value = node.value
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        value = node.value
    else:
        return set()
    if value is None:
        return set()
    return _names(value)


def _target_node(source_text: str, target: Dict[str, Any]) -> ast.AST | None:
    tree = ast.parse(source_text)
    for node in ast.walk(tree):
        if isinstance(node, ast.stmt) and int(node.lineno) == int(target["line"]):
            return node
    return None


def target_variables(source_text: str, target: Dict[str, Any]) -> Set[str]:
    node = _target_node(source_text, target)
    if node is None:
        return set()
    return _lhs_names(node) | _rhs_names(node) | _names(node)


def target_lhs_variables(source_text: str, target: Dict[str, Any]) -> Set[str]:
    node = _target_node(source_text, target)
    if node is None:
        return set()
    return _plain_lhs_names(node)


def _called_names(node: ast.AST) -> Set[str]:
    out: Set[str] = set()
    for child in ast.walk(node):
        if isinstance(child, ast.Call):
            func = child.func
            if isinstance(func, ast.Name):
                out.add(func.id)
            elif isinstance(func, ast.Attribute):
                out.add(func.attr)
    return out


def reachable_functions(tree: ast.AST, target: Dict[str, Any]) -> List[ast.AST]:
    index = _function_index(tree)
    root = None
    for node in ast.walk(tree):
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            if _contains(node, int(target["line"])):
                root = node
                break
    if root is None:
        return []
    seen = {id(root)}
    queue = [root]
    result = [root]
    while queue:
        current = queue.pop(0)
        for name in _called_names(current):
            for candidate in index.get(name, []):
                if id(candidate) in seen:
                    continue
                seen.add(id(candidate))
                queue.append(candidate)
                result.append(candidate)
    return result


def _plain_lhs_names(node: ast.AST) -> Set[str]:
    """Names assigned directly (``x = ...``), not attributes (``x.y = ...``)."""
    targets: List[ast.AST] = []
    if isinstance(node, ast.Assign):
        targets = list(node.targets)
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        targets = [node.target]
    out: Set[str] = set()
    for target in targets:
        for child in ast.walk(target):
            if isinstance(child, ast.Name):
                out.add(child.id)
    return out


def _statement_ops(source_lines: Sequence[str], file: str,
                   root: ast.AST, functions: Iterable[ast.AST],
                   target_variables_lhs: Set[str],
                   target_line: int) -> List[Dict[str, Any]]:
    """Assignments that write the same plain variable as A.

    A masking operation must be another definition of the variable A writes.
    Reads of that variable, assignments to other names, and attribute stores
    are prerequisites or downstream consumers, not competing definitions.

    Within A's own function only statements *after* A can compete with it;
    assignments before A are initialisation that A overwrites.  Reachable
    helper functions are included at any position because they may run after
    A (``bind_to_environ`` calls ``bind``).
    """
    assignments: List[ast.AST] = []
    blocks: List[ast.AST] = []
    root_id = id(root)
    for function in functions:
        same_function = id(function) == root_id
        for node in ast.walk(function):
            if not isinstance(node, ast.stmt):
                continue
            first, last = _span(node)
            if first <= target_line <= last:
                # Deleting this statement would also delete A itself.
                continue
            if same_function and first <= target_line:
                continue
            if isinstance(node, (ast.Assign, ast.AnnAssign, ast.AugAssign)):
                if _plain_lhs_names(node) & target_variables_lhs:
                    assignments.append(node)
            elif isinstance(node, ast.If):
                if any(
                    _plain_lhs_names(child) & target_variables_lhs
                    for child in ast.walk(node)
                    if isinstance(child, (ast.Assign, ast.AnnAssign,
                                          ast.AugAssign))
                ):
                    blocks.append(node)

    # A block is only a separate candidate when no other candidate
    # statement lies strictly inside it.  Otherwise deleting the block would
    # also delete that statement, and the two operations would overlap --
    # subset enumeration would no longer describe independent interventions.
    assignment_spans = {_span(node) for node in assignments}
    selected: List[Tuple[ast.AST, str]] = [(node, "assignment")
                                           for node in assignments]
    for block in blocks:
        b_first, b_last = _span(block)
        contains_other = any(
            b_first <= a_first and a_last <= b_last
            and (a_first, a_last) != (b_first, b_last)
            for a_first, a_last in assignment_spans)
        if not contains_other:
            selected.append((block, "block"))

    ops: List[Dict[str, Any]] = []
    seen: Set[Tuple[int, int]] = set()
    for node, kind in selected:
        first, last = _span(node)
        if (first, last) in seen:
            continue
        seen.add((first, last))
        code = "\n".join(source_lines[first - 1:last])
        ops.append({
            "id": f"{file}:{first}-{last}",
            "file": file,
            "first_line": first,
            "last_line": last,
            "kind": kind,
            "code": code,
        })
    return sorted(ops, key=lambda op: (op["first_line"], op["last_line"]))


def discover(task: Dict[str, Any], source_text: str) -> Dict[str, Any]:
    target = task["target_operation"]
    source_lines = source_text.splitlines()
    tree = ast.parse(source_text)
    variables = target_variables(source_text, target)
    lhs_variables = target_lhs_variables(source_text, target)
    functions = reachable_functions(tree, target)
    ops = (_statement_ops(source_lines, target["file"], functions[0],
                          functions, lhs_variables, int(target["line"]))
           if functions else [])
    return {
        "target_variables": sorted(variables),
        "target_lhs_variables": sorted(lhs_variables),
        "reachable_functions": [f.name for f in functions],
        "candidate_ops": ops,
        "discovery_rule": (
            "same-file call-reachable functions; assignment to the same "
            "plain variable A writes; after A in A's own function; "
            "if-blocks containing such an assignment and no other candidate"),
    }


def _signature(executor: Any, op: Dict[str, Any],
               inputs: Sequence[Dict[str, Any]]) -> Tuple[str, int, int]:
    """Behavioural signature of deleting one operation on the input grid.

    The signature stores a digest of the *resulting observation*, not just a
    differ/did-not-differ bit.  Two operations are collapsed only when
    deleting either produces the same observations on every grid cell; a
    coarse bit would wrongly merge unrelated crashes.
    """
    import json as _json

    changed = 0
    pieces: List[str] = []
    for payload in inputs:
        for side in ("plus", "minus"):
            base = executor.observation([], side, payload)
            after = executor.observation([op["id"]], side, payload)
            if base != after:
                changed += 1
            text = _json.dumps(after, ensure_ascii=False, sort_keys=True)
            pieces.append(text)
    return "\u0001".join(pieces), changed, len(pieces)


def rank_and_prune(executor: Any, discovered: Dict[str, Any],
                   inputs: Sequence[Dict[str, Any]], max_ops: int) -> Dict[str, Any]:
    """Keep operations whose deletion actually changes something.

    Operations with an identical behavioural signature are collapsed to the
    one with the smaller source span (a statement is preferred over a block
    that contains it).  Ties are broken deterministically by span size, then
    line number.
    """
    rows = []
    for op in discovered["candidate_ops"]:
        signature, changed, total = _signature(executor, op, inputs)
        rows.append({
            "op": op,
            "signature": signature,
            "changed": changed,
            "signature_length": total,
            "span": op["last_line"] - op["first_line"] + 1,
        })
    by_signature: Dict[str, Dict[str, Any]] = {}
    collapsed: List[Dict[str, Any]] = []
    for row in rows:
        if row["changed"] == 0:
            continue
        current = by_signature.get(row["signature"])
        if current is None or (row["span"], row["op"]["first_line"]) < (
                current["span"], current["op"]["first_line"]):
            if current is not None:
                collapsed.append(current)
            by_signature[row["signature"]] = row
        else:
            collapsed.append(row)
    kept = sorted(by_signature.values(),
                  key=lambda r: (-r["changed"], r["span"],
                                 r["op"]["first_line"]))[:max_ops]
    universe = [row["op"] for row in kept]
    return {
        "universe": universe,
        "ranking": [
            {"id": row["op"]["id"], "changed_cells": row["changed"],
             "cells": row["signature_length"], "span": row["span"]}
            for row in kept
        ],
        "considered": len(rows),
        "dropped_no_effect": sum(1 for row in rows if row["changed"] == 0),
        "dropped_duplicate_effect": len(collapsed),
        "truncated": max(0, len(by_signature) - max_ops),
    }
