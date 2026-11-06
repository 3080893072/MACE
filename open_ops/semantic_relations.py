"""Qwen semantic relation discovery over real AST operations.

This module is the bridge between a language model's *semantic* claims and the
executable operation universe:

1. a model proposal is a ``{file, line, text}`` triple (or a direct operation
   id).  It is accepted only if it resolves to a real AST statement with a
   source span -- no free-floating strings;
2. accepted proposals are split into ``U_graph`` (already known from static
   discovery) and ``U_qwen`` (new operations the graph did not propose).
   ``U_union`` is the union the causal search may execute;
3. the model's relations (independent / cooperative / fallback / coexisting
   masking) are translated into role-specific hypotheses: MSMS receives
   *kept* sets, MMBS receives *disabled* sets.  Nothing is confirmed here:
   every relation starts as ``HYPOTHESIS`` and only the causal verifier can
   promote it.

No model call and no hidden scorer is used in this module.
"""
from __future__ import annotations

import ast
import json
import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

SCHEMA_VERSION = "mace-semantic-relations-v1"

RELATION_KINDS = ("independent", "cooperative", "fallback", "coexisting")
_MASKING_KINDS = ("independent", "cooperative", "fallback")
_EXPOSURE_KINDS = ("coexisting", "joint_exposure")

_STATUS_HYPOTHESIS = "HYPOTHESIS"
_STATUS_UNEXECUTABLE = "HYPOTHESIS_UNEXECUTABLE"


# ---------------------------------------------------------------------------
# Source index: file + line -> real AST statement
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class StatementSpan:
    node_type: str
    kind: str
    first_line: int
    last_line: int
    col: int
    end_col: Optional[int]
    text: str

    def node_key(self) -> Tuple[str, int, int, Optional[int], Optional[int]]:
        return (self.node_type, self.first_line, self.col,
                self.last_line, self.end_col)


def _normalise(text: str) -> str:
    return " ".join(text.split())


def _first_line_text(source: str, line: int) -> str:
    lines = source.splitlines()
    if 1 <= line <= len(lines):
        return _normalise(lines[line - 1])
    return ""


@dataclass
class SourceIndex:
    """Resolve proposals against one source file using AST identities."""

    file: str
    source: str
    statements: Tuple[StatementSpan, ...]

    @classmethod
    def from_source(cls, file: str, source: str) -> "SourceIndex":
        tree = ast.parse(source)
        spans: List[StatementSpan] = []
        for node in ast.walk(tree):
            if not isinstance(node, ast.stmt):
                continue
            first = int(getattr(node, "lineno", -1))
            if first < 0:
                continue
            last = int(getattr(node, "end_lineno", first) or first)
            text = ast.get_source_segment(source, node) or ""
            spans.append(StatementSpan(
                node_type=type(node).__name__,
                kind=type(node).__name__.lower(),
                first_line=first,
                last_line=last,
                col=int(getattr(node, "col_offset", -1)),
                end_col=getattr(node, "end_col_offset", None),
                text=text,
            ))
        spans.sort(key=lambda s: (s.first_line, s.col, s.last_line))
        return cls(file=file, source=source, statements=tuple(spans))

    @classmethod
    def from_path(cls, file: str, root: Path) -> "SourceIndex":
        path = Path(root) / file
        return cls.from_source(file, path.read_text(encoding="utf-8"))

    # -- resolution --------------------------------------------------------
    def _exact(self, line: int) -> List[StatementSpan]:
        return [s for s in self.statements if s.first_line == line]

    def _containing(self, line: int) -> List[StatementSpan]:
        return [s for s in self.statements
                if s.first_line <= line <= s.last_line]

    def resolve(self, line: int, text: Optional[str] = None,
                exclude_lines: Iterable[int] = ()) -> Dict[str, Any]:
        """Resolve one 1-based line to a statement span.

        ``text`` is checked when supplied.  A one-line shift in either
        direction is accepted and reported; anything larger is rejected so a
        model cannot silently name a different statement.
        """
        excluded = set(int(x) for x in exclude_lines)
        if not isinstance(line, int) or isinstance(line, bool):
            return {"status": "rejected", "reason": "line_not_int"}
        if line in excluded:
            return {"status": "rejected", "reason": "target_line"}
        want = _normalise(text) if isinstance(text, str) else None

        for shift in (0, -1, 1, -2, 2):
            candidate_line = line + shift
            if candidate_line in excluded and shift != 0:
                continue
            exact = self._exact(candidate_line)
            if not exact:
                continue
            if want is None:
                chosen = exact[0]
                return self._accept(chosen, shift, want, matched="line")
            matching = [s for s in exact
                        if _normalise(s.text) == want
                        or _first_line_text(self.source, candidate_line) == want
                        or _normalise(s.text).startswith(want)]
            if matching:
                chosen = min(matching, key=lambda s: (s.last_line, s.col))
                return self._accept(chosen, shift, want, matched="text")
        if want is not None:
            return {"status": "rejected", "reason": "text_mismatch",
                    "line": line, "text": text}
        return {"status": "rejected", "reason": "no_statement_at_line",
                "line": line}

    @staticmethod
    def _accept(span: StatementSpan, shift: int, want: Optional[str],
                matched: str) -> Dict[str, Any]:
        return {
            "status": "mapped",
            "span": span,
            "line_shift": shift,
            "match": matched,
        }

    def describe(self, span: StatementSpan) -> str:
        return f"{span.node_type} L{span.first_line}-{span.last_line}"


# ---------------------------------------------------------------------------
# Operation ids and proposal mapping
# ---------------------------------------------------------------------------

def operation_id(file: str, span: StatementSpan, style: str = "v3") -> str:
    if style == "pilot":
        return f"op_L{span.first_line}_C{span.col}_{span.kind}"
    if style == "v3":
        return f"{file}:{span.first_line}-{span.last_line}"
    raise ValueError(f"unknown id style {style!r}")


def _op_dict(file: str, span: StatementSpan, style: str) -> Dict[str, Any]:
    return {
        "id": operation_id(file, span, style),
        "key": operation_id(file, span, style),
        "file": file,
        "first_line": span.first_line,
        "last_line": span.last_line,
        "line": span.first_line,
        "end_line": span.last_line,
        "col": span.col,
        "end_col": span.end_col,
        "kind": span.kind,
        "node_type": span.node_type,
        "code": span.text,
        "text": span.text,
        "node_key": list(span.node_key()),
    }


def _proposal_fields(proposal: Any, default_file: str) -> Dict[str, Any]:
    if isinstance(proposal, int) and not isinstance(proposal, bool):
        return {"file": default_file, "line": proposal, "text": None}
    if isinstance(proposal, str):
        return {"id": proposal}
    if not isinstance(proposal, dict):
        raise ValueError("operation must be an object, an id or an int line")
    return {
        "id": proposal.get("id") or proposal.get("op") or proposal.get("key"),
        "file": proposal.get("file") or default_file,
        "line": proposal.get("line"),
        "text": proposal.get("text"),
    }


def map_proposal(proposal: Any, index: SourceIndex,
                 graph_ops: Optional[Sequence[Dict[str, Any]]] = None,
                 style: str = "v3",
                 exclude_lines: Iterable[int] = ()) -> Dict[str, Any]:
    """Map one model proposal to a real operation or reject it."""
    default_file = index.file
    try:
        fields = _proposal_fields(proposal, default_file)
    except ValueError as exc:
        return {"status": "rejected", "reason": "format_error",
                "detail": str(exc), "proposal": proposal}

    known = {op["id"]: op for op in (graph_ops or [])}
    if fields.get("id"):
        op_id = str(fields["id"])
        if op_id in known:
            return {"status": "mapped", "op": dict(known[op_id]),
                    "in_graph": True, "match": "id", "line_shift": 0}
        if fields.get("line") is None:
            return {"status": "rejected", "reason": "unknown_id",
                    "proposal": proposal, "id": op_id}
        fields["line"] = fields["line"]

    line = fields.get("line")
    if line is None:
        return {"status": "rejected", "reason": "missing_line",
                "proposal": proposal}
    if fields.get("file") not in (index.file, None):
        return {"status": "rejected", "reason": "wrong_file",
                "proposal": proposal, "expected": index.file,
                "got": fields.get("file")}

    resolved = index.resolve(int(line), fields.get("text"),
                             exclude_lines=exclude_lines)
    if resolved["status"] != "mapped":
        resolved["proposal"] = proposal
        return resolved

    span: StatementSpan = resolved["span"]
    op = _op_dict(index.file, span, style)
    if op["id"] in known:
        return {"status": "mapped", "op": dict(known[op["id"]]),
                "in_graph": True, "match": resolved["match"],
                "line_shift": resolved["line_shift"]}
    # A line inside a multi-line graph operation names that operation, not a
    # second operation: the pilot graph treats an ``if`` block as one unit.
    for known_op in (graph_ops or []):
        first = int(known_op.get("first_line", known_op.get("line")))
        last = int(known_op.get("last_line", first))
        if (known_op.get("file") in (index.file, None)
                and first <= span.first_line <= last and last > first):
            return {"status": "mapped", "op": dict(known_op),
                    "in_graph": True, "match": "contained_in_graph_span",
                    "line_shift": resolved["line_shift"]}
    return {"status": "mapped", "op": op, "in_graph": False,
            "match": resolved["match"],
            "line_shift": resolved["line_shift"]}


def build_universes(graph_ops: Sequence[Dict[str, Any]],
                    proposals: Iterable[Any], index: SourceIndex,
                    style: str = "v3",
                    exclude_lines: Iterable[int] = ()) -> Dict[str, Any]:
    """Split mapped proposals into ``U_graph`` / ``U_qwen`` / ``U_union``."""
    graph = [dict(op) for op in graph_ops]
    graph_ids = {op["id"] for op in graph}
    qwen: List[Dict[str, Any]] = []
    seen_new = set()
    mapped: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    duplicates: List[str] = []

    for proposal in proposals:
        result = map_proposal(proposal, index, graph, style=style,
                              exclude_lines=exclude_lines)
        if result["status"] != "mapped":
            rejected.append(result)
            continue
        op = result["op"]
        mapped.append({"proposal": proposal, "id": op["id"],
                       "in_graph": result["in_graph"],
                       "match": result.get("match"),
                       "line_shift": result.get("line_shift", 0)})
        if result["in_graph"]:
            continue
        if op["id"] in seen_new:
            duplicates.append(op["id"])
            continue
        seen_new.add(op["id"])
        qwen.append(op)

    return {
        "U_graph": graph,
        "U_qwen": qwen,
        "U_union": graph + qwen,
        "mapped": mapped,
        "rejected": rejected,
        "duplicates": duplicates,
    }


# ---------------------------------------------------------------------------
# Semantic hypothesis protocol
# ---------------------------------------------------------------------------

def extract_json(content: str) -> Optional[Any]:
    """Extract the first JSON object from a model response."""
    if not isinstance(content, str):
        return None
    text = content.strip()
    fenced = re.search(r"```(?:json)?\s*\n(.*?)```", text, re.S)
    if fenced:
        text = fenced.group(1).strip()
    try:
        return json.loads(text)
    except Exception:  # noqa: BLE001
        pass
    start = text.find("{")
    end = text.rfind("}")
    if start < 0 or end <= start:
        return None
    try:
        return json.loads(text[start:end + 1])
    except Exception:  # noqa: BLE001
        return None


def _normalise_kind(value: Any) -> Optional[str]:
    if not isinstance(value, str):
        return None
    kind = value.strip().lower()
    aliases = {
        "independent_masking": "independent",
        "independent": "independent",
        "cooperative": "cooperative",
        "cooperative_masking": "cooperative",
        "fallback": "fallback",
        "alternative": "fallback",
        "alternative_path": "fallback",
        "fallback_path": "fallback",
        "coexisting": "coexisting",
        "joint_exposure": "coexisting",
        "joint": "coexisting",
    }
    return aliases.get(kind)


def _relations_from_payload(payload: Any) -> List[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, dict):
        return []
    if isinstance(payload.get("relations"), list):
        return payload["relations"]
    # Tolerate role-shaped output: each entry is still a relation object.
    out: List[Any] = []
    for key, kind in (("independent_operations", "independent"),
                      ("cooperative_operations", "cooperative"),
                      ("fallback_paths", "fallback"),
                      ("coexisting_operations", "coexisting")):
        value = payload.get(key)
        if not isinstance(value, list):
            continue
        for item in value:
            if isinstance(item, dict):
                out.append({"kind": kind, **item})
            elif isinstance(item, list):
                out.append({"kind": kind, "operations": item})
    return out


def parse_semantic_hypotheses(content: str, index: SourceIndex,
                              graph_ops: Sequence[Dict[str, Any]],
                              style: str = "v3",
                              exclude_lines: Iterable[int] = (),
                              max_relations: int = 16) -> Dict[str, Any]:
    """Parse a model response into mapped, still-hypothetical relations."""
    payload = extract_json(content)
    if payload is None:
        return {"format": "unparseable", "relations": [], "rejected": [],
                "operations": []}
    raw_relations = _relations_from_payload(payload)
    if not raw_relations:
        return {"format": "empty", "relations": [], "rejected": [],
                "operations": []}

    known = {op["id"]: op for op in graph_ops}
    relations: List[Dict[str, Any]] = []
    rejected: List[Dict[str, Any]] = []
    new_ops: Dict[str, Dict[str, Any]] = {}
    seen: set = set()

    for position, raw in enumerate(raw_relations[:max_relations]):
        if not isinstance(raw, dict):
            rejected.append({"reason": "relation_not_object",
                             "relation_index": position})
            continue
        kind = _normalise_kind(raw.get("kind"))
        if kind is None:
            rejected.append({"reason": "unknown_kind",
                             "relation_index": position,
                             "kind": raw.get("kind")})
            continue
        raw_ops = raw.get("operations")
        if not isinstance(raw_ops, list) or not raw_ops:
            rejected.append({"reason": "missing_operations",
                             "relation_index": position})
            continue
        mapped_ops: List[Dict[str, Any]] = []
        mapping_errors: List[Dict[str, Any]] = []
        for item in raw_ops:
            result = map_proposal(item, index, graph_ops, style=style,
                                  exclude_lines=exclude_lines)
            if result["status"] != "mapped":
                mapping_errors.append(result)
                continue
            op = result["op"]
            mapped_ops.append(op)
            if not result["in_graph"]:
                new_ops.setdefault(op["id"], op)
        if mapping_errors:
            rejected.append({"reason": "operation_mapping_failed",
                             "relation_index": position,
                             "kind": kind,
                             "errors": mapping_errors})
            continue
        op_ids = tuple(sorted({op["id"] for op in mapped_ops}))
        key = (kind, op_ids)
        if key in seen:
            rejected.append({"reason": "duplicate_relation",
                             "relation_index": position,
                             "kind": kind, "ops": list(op_ids)})
            continue
        seen.add(key)
        condition = raw.get("condition")
        relations.append({
            "relation_index": position,
            "kind": kind,
            "ops": list(op_ids),
            "operations": [op["id"] for op in mapped_ops],
            "proposals": raw_ops,
            "in_graph": all(op["id"] in known for op in mapped_ops),
            "condition": condition if isinstance(condition, str) else None,
            "data_dependence": raw.get("data_dependence"),
            "control_dependence": raw.get("control_dependence"),
            "source_evidence": raw.get("source_evidence"),
            "rationale": raw.get("rationale"),
            "status": _STATUS_HYPOTHESIS,
            "role_sets": {},
        })

    return {
        "format": "structured",
        "schema": SCHEMA_VERSION,
        "relations": relations,
        "rejected": rejected,
        "operations": sorted(new_ops.values(), key=lambda op: op["id"]),
        "notes": payload.get("notes") if isinstance(payload, dict) else None,
    }


def relations_to_role_hypotheses(
        relations: Sequence[Dict[str, Any]],
        executable_ops: Optional[Iterable[str]] = None) -> Dict[str, Any]:
    """Translate masking relations into MSMS kept sets and MMBS disabled sets.

    * masking relation R  -> MSMS kept ``R`` and MMBS disabled ``R``;
    * coexisting relation -> MMBS disabled ``R`` only.

    The same set can mean different things to the two roles, so each role gets
    its own list.  Relations naming an operation that cannot be executed are
    kept in the report as ``HYPOTHESIS_UNEXECUTABLE`` and are not handed to
    the search.
    """
    allowed = set(executable_ops) if executable_ops is not None else None
    msms: List[Dict[str, Any]] = []
    mmbs: List[Dict[str, Any]] = []
    skipped: List[Dict[str, Any]] = []

    for relation in relations:
        ops = tuple(sorted(set(relation.get("ops") or [])))
        if not ops:
            continue
        entry = {
            "ops": ops,
            "relation_index": relation.get("relation_index"),
            "kind": relation.get("kind"),
            "condition": relation.get("condition"),
            "status": _STATUS_HYPOTHESIS,
        }
        if allowed is not None and any(op not in allowed for op in ops):
            entry["status"] = _STATUS_UNEXECUTABLE
            skipped.append(entry)
            relation["role_sets"] = {"status": _STATUS_UNEXECUTABLE,
                                     "ops": list(ops)}
            continue
        kind = relation.get("kind")
        roles: List[str] = []
        if kind in _MASKING_KINDS:
            msms.append(dict(entry))
            mmbs.append(dict(entry))
            roles = ["msms", "mmbs"]
        elif kind in _EXPOSURE_KINDS:
            mmbs.append(dict(entry))
            roles = ["mmbs"]
        else:
            skipped.append(dict(entry, status="UNKNOWN_KIND"))
            continue
        relation["role_sets"] = {"roles": roles, "ops": list(ops),
                                 "status": _STATUS_HYPOTHESIS}

    return {"msms": msms, "mmbs": mmbs, "skipped": skipped}


def role_tuples(hypotheses: Dict[str, Any], role: str) -> List[Tuple[str, ...]]:
    return [tuple(item["ops"]) for item in hypotheses.get(role, [])
            if item.get("status") == _STATUS_HYPOTHESIS]


# ---------------------------------------------------------------------------
# Prompt
# ---------------------------------------------------------------------------

def numbered_source(source: str, line_offset: int = 0) -> str:
    return "\n".join(f"{i + line_offset:>4} | {line}"
                     for i, line in enumerate(source.splitlines(), 1))


def build_prompt(task_id: str, source: str, target: Dict[str, Any],
                 files: Sequence[str], input_domain: Dict[str, Any],
                 graph_ops: Sequence[Dict[str, Any]],
                 observable: Optional[str] = None,
                 max_relations: int = 12,
                 line_offset: int = 0) -> str:
    """The semantic-relation prompt (no operation roles are leaked)."""
    candidate_lines = []
    for op in graph_ops:
        candidate_lines.append(
            f"- id={op['id']}  line={op.get('line', op.get('first_line'))}"
            f"  kind={op.get('kind')}  `{str(op.get('code') or '').splitlines()[0]} `")
    candidates = "\n".join(candidate_lines) or "(none)"
    file_list = ", ".join(f"`{f}`" for f in files)
    args = json.dumps(input_domain.get("args"), ensure_ascii=False)
    cases = json.dumps(input_domain.get("cases"), ensure_ascii=False)
    note = input_domain.get("note")
    note_block = f"\nLegal constraints: {note}" if note else ""
    return f"""You are analysing a proposed deletion in a Python function. Use only
the public information below. A Python exception is an observation. The best
evidence level is BOUNDED: execution on the declared finite domain, never a proof.

## Task
{task_id}

## Files
{file_list}

## Program with source line numbers
```text
{numbered_source(source, line_offset)}
```

## Target A
Line {target['line']}: `{str(target.get('text', '')).strip()}`
Deletion rule: replace exactly this line with `pass` at the same indentation.

## Legal inputs
Arguments: {args}
Frozen legal cases: {cases}{note_block}

## Observable
{observable or 'the function return value (and raised exception type/message)'}

## Operations already proposed by the static graph
{candidates}

You may propose operations that are NOT in this list. Every operation you
report must be a real, complete statement in the file above: give its exact
1-based starting line and its source text. Do not invent lines.

## What to analyse
1. Operations that may **independently mask A**: one operation alone is enough
   to make the deletion unobservable.
2. Operations that may **cooperatively mask A**: two or more operations are
   jointly sufficient, and no proper non-empty subset is.
3. **Alternative / fallback masking paths**: different sets of operations that
   each mask A, so more than one path has to fail before A is exposed.
4. The **input conditions** under which each relation holds. Use only the
   argument names, int/bool constants, comparisons, arithmetic, `and`, `or`,
   `not`. If the relation holds for every legal input, write `true`.
5. Source locations, and whether the relation is **data-dependent** (it reads
   or overwrites the value A writes) or **control-dependent** (it changes
   whether A's statement executes).

## Required JSON
{{
  "relations": [
    {{
      "kind": "independent | cooperative | fallback | coexisting",
      "operations": [
        {{"file": "<path from Files>", "line": <int>, "text": "<source text>"}}
      ],
      "condition": "<restricted boolean expression or null>",
      "data_dependence": true,
      "control_dependence": false,
      "source_evidence": "<line numbers and why>",
      "rationale": "<one sentence>"
    }}
  ],
  "notes": "<optional>"
}}

`coexisting` means: disabling the named operations together exposes A, while
no proper non-empty subset does. Return at most {max_relations} different
relations. Return one JSON object and no prose outside it.
"""
