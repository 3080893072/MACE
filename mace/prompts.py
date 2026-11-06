"""Prompt construction.

Design rules that matter scientifically:

* The model sees the program, the marked target A, the declared input domain
  and the declared function signatures.  It never sees B1/B2 labels, reference
  formulas, or any file from ``experiments/hidden``.
* The requested output is a typed contract bundle, not just a final guard.
* The repair prompt carries the individual counterexamples; it does not ask
  the model to regenerate its whole answer from scratch.
* Function names are already obfuscated in the fixtures (fn_0, fn_1, ...).
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Mapping

SYSTEM = (
    "You are a precise program-semantics analyst. A single marked assignment A "
    "is deleted in one version of a Python program. You explain, with typed "
    "relations over the program state, when the two versions still produce the "
    "same output. Derive every relation from the actual source code. Do not "
    "guess which other statements to delete, do not enumerate source-operation "
    "subsets, and never claim that something is proved: a separate bounded "
    "checker tests your relations. Respond with one JSON object and nothing else."
)

LANGUAGE_SPEC = """\
Allowed expression language (parsed by a typed checker; no Python execution):
  sorts        bool, int, list[int], dict[int,int]
  literals     3, -1, True, False, [1, 2], {0: 1}
  variables    entry arguments and the local variables right before A
               (snapshot), plus <name>_post for their values right after A
               (target_effects only)
  arithmetic   + - * // %          (int only)
  boolean      and or not          (parentheses allowed)
  comparisons  == !=               (any sort)
               < <= > >=           (int only)
  conditional  <a> if <cond> else <b>
  indexing     xs[i]  (list), d[k]  (dict)   -- i/k are int expressions
  builtins     len, min, max, sum, abs, sorted, vals, distinct, count
  calls        the program functions listed in the signature table, applied to
               expressions of the declared parameter sorts
Not allowed: assignments, lambdas, comprehensions, imports, attribute access,
slices, strings, float, helper names not listed in the signature table.
"""


def numbered(source: str) -> str:
    return "\n".join(f"{i:03}: {line}" for i, line in enumerate(source.splitlines(), 1))


def _vocabulary_text(vocabulary: Mapping[str, str] | None) -> str:
    if not vocabulary:
        return "(use the entry arguments named in the source)"
    return "\n".join(f"  {name}: {sort}" for name, sort in sorted(vocabulary.items()))


def _signatures_text(signatures: Mapping[str, Any]) -> str:
    if not signatures:
        return "(no user-defined functions)"
    lines = []
    for name, spec in signatures.items():
        params = ", ".join(spec.get("params", []))
        lines.append(f"  {name}({params}) -> {spec.get('ret', '?')}")
    return "\n".join(lines)


SCHEMA_TEXT = """\
{
  "target_effects": [
    {"id": "T1",
     "expr": "<bool expr over the state right before A, and <name>_post>",
     "source_lines": [<line numbers of A and of the code that computes the value>],
     "rationale": "<one sentence>"}
  ],
  "upstream": [
    {"id": "U1",
     "expr": "<bool expr over the entry arguments>",
     "condition": "<bool expr; when the upstream fact holds, usually True>",
     "role": "fixed_point | supporting",
     "source_lines": [<line numbers of the upstream code that establishes it>],
     "rationale": "<one sentence>"}
  ],
  "observers": [
    {"id": "O0", "channel": 0,
     "expr": "<bool or int expr that equals channel 0's value on every input>",
     "condition": "<bool expr over the entry arguments: when A cannot change channel 0>",
     "source_lines": [<line numbers of the downstream code that computes this channel>],
     "rationale": "<one sentence>"}
  ],
  "mask_guard": {"id": "G",
                 "expr": "<bool expr over the entry arguments: when the whole output is unchanged>",
                 "source_lines": [<line numbers>]},
  "uncertainty": "<what you could not establish from the source>"
}
"""


def contract_prompt(*, source: str, target_line: int, domain_text: str,
                    signatures: Mapping[str, Any], channels: int,
                    entry: str = "program",
                    vocabulary: Mapping[str, str] | None = None) -> str:
    channel_list = ", ".join(str(i) for i in range(channels))
    return f"""\
Program under analysis (line numbers are not part of the code).
Line {target_line} holds the single marked target A.

{numbered(source)}

Input domain used by the bounded checker:
{domain_text}

Variable names in scope at A, with their sorts (nothing else exists):
{_vocabulary_text(vocabulary)}

Declared types of the user-defined functions (derived from their use in this
program, not from their names):
{_signatures_text(signatures)}

Your task
---------
A is deleted in a second version of this program. Derive a typed contract that
explains, from the actual semantics of the code, when the returned value is the
same in both versions.

1. target_effects: describe precisely how A changes the local state. A name
   such as xs denotes the local value right before A; xs_post is its value
   right after A.
2. upstream: state facts that earlier code guarantees about the entry
   arguments, including facts about what the called functions return (you may
   call a listed program function on expression arguments). Each fact needs the
   input condition under which it holds and a role:
     - "fixed_point": under the condition, A provably does not change the local
       state at all (A is a no-op there);
     - "supporting": a fact that explains why a downstream observation becomes
       insensitive to A (e.g. a list is already sorted or duplicate-free), but
       does not by itself make A a no-op.
3. observers: the program returns {channels} value(s), one per channel
   ({channel_list}). For every channel give an expression that computes that
   channel's value from the state after A, and a condition under which deleting
   A cannot change that observed value. Use the real computation in the
   downstream code; do not paraphrase it.
4. mask_guard: a single Boolean condition under which the whole returned value
   is unchanged. A structurally valid guard combines the upstream conditions
   that make A a no-op with the conjunction of the observer conditions; derive
   the parts, then state the guard.
5. Cite the source lines that establish each relation. Report what you could
   not establish in "uncertainty". A separate checker will test every relation
   on a finite domain and send you concrete counterexamples; nothing you write
   is taken as proved.

{LANGUAGE_SPEC}

Return exactly this JSON shape (values are placeholders, not an answer):
{SCHEMA_TEXT}"""


def oracle_guard_prompt(*, source: str, target_line: int, domain_text: str,
                        signatures: Mapping[str, Any], channels: int,
                        contract: Mapping[str, Any],
                        vocabulary: Mapping[str, str] | None = None) -> str:
    """Cell C of the 2x2: the reviewed contract is given, only the guard is asked.

    Diagnostic only.  Putting a human-reviewed contract in the prompt is exactly
    what the automated protocol forbids, so a result from this prompt measures
    the ceiling of "correct relations -> guard", never system accuracy.
    """
    relations = {key: contract.get(key) for key in
                 ("target_effects", "upstream", "observers") if key in contract}
    return f"""\
Program under analysis (line numbers are not part of the code).
Line {target_line} holds the single marked target A.

{numbered(source)}

Input domain: {domain_text}

Variable names in scope at A, with their sorts (nothing else exists):
{_vocabulary_text(vocabulary)}

Declared function types:
{_signatures_text(signatures)}

A human reviewer has already established these relations about A and the
{channels} output channel(s). Treat them as given facts; do not restate them and
do not contradict them:
{json.dumps(relations, indent=2, ensure_ascii=False)}

Write the single Boolean condition under which deleting A leaves the whole
returned value unchanged. Build it by combining the conditions above the way the
code requires: a fixed-point condition makes A a no-op by itself, while an
observer condition only says that channel is insensitive. Reply as JSON:
{{"mask_guard": "<bool expr over the entry arguments>", "explanation": "<short>"}}

{LANGUAGE_SPEC}"""


def _diagnosis(item: Mapping[str, Any]) -> str:
    """Turn the checker's raw example into the specific thing that is wrong.

    Without this the model tends to answer "my condition is already correct"
    even when the counterexamples plainly contradict it.
    """
    kind = item.get("kind")
    examples = item.get("counterexamples") or []
    seen = {e.get("kind") for e in examples}
    if kind == "observer":
        if "faithfulness" in seen:
            return ("on these inputs the expression did not equal the value the program "
                    "actually returned for that channel, so it does not describe the real "
                    "downstream computation (rewrite it from the source)")
        if "faithfulness_minus" in seen:
            return ("on these inputs the expression matched the version with A but not the "
                    "version without it: it restates the outcome instead of describing the "
                    "downstream computation, which must hold in both versions")
        if "invariance" in seen:
            return ("on these inputs the condition was true, yet deleting A changed this "
                    "channel's value, so the condition is too weak")
        if "evaluation" in seen:
            return "the expression could not even be evaluated on these inputs"
    elif kind in ("target_effect", "upstream"):
        if item.get("role") == "fixed_point" and item.get("fixed_point_failures"):
            return ("the condition is true on inputs where deleting A still changes the local "
                    "state, so it does not make A a no-op. Either state a condition under "
                    "which the state is unchanged, or mark the relation as 'supporting' -- a "
                    "fixed_point condition is used directly in the guard")
        if item.get("role") == "fixed_point":
            return ("on these inputs the condition was true and A leaves the local state "
                    "unchanged, but the expression itself evaluates to false; the expression "
                    "is what is wrong")
        if any("expr_value" in e for e in examples):
            if item.get("role") == "supporting":
                return ("on these inputs the condition was true but the stated fact is false; "
                        "the fact or its condition is wrong")
            return ("on these inputs the condition was true but the expression is false; "
                    "either the expression is wrong or the condition is too weak")
        if "evaluation" in (seen | {"evaluation"}) and any("error" in e for e in examples):
            return "the expression could not be evaluated on these inputs"
    elif kind == "mask_guard":
        if item.get("unsound"):
            return ("the guard is true on inputs where the two versions really return "
                    "different values, so it accepts too much; the subterms below are "
                    "the ones that made it true there")
        if item.get("incomplete"):
            return ("the outputs are equal on these inputs but the guard is false, so it "
                    "rejects inputs it should accept; the subterms below are the ones "
                    "that were false there")
    return ""


def _guard_blame(item: Mapping[str, Any]) -> List[str]:
    """Name the top-level subterm of the guard that produced each wrong verdict."""
    texts = item.get("part_text") or item.get("parts") or []
    blame = item.get("blame") or {}
    accepts = blame.get("accepts_wrong") or []
    rejects = blame.get("rejects_wrong") or []
    lines = []
    for index, text in enumerate(texts):
        accepted = accepts[index] if index < len(accepts) else 0
        rejected = rejects[index] if index < len(rejects) else 0
        if not accepted and not rejected:
            continue
        if accepted and rejected:
            why = (f"true on {accepted} exposed input(s) it must reject and false on "
                   f"{rejected} masked input(s) it must accept")
        elif accepted:
            why = f"true on {accepted} exposed input(s) it must reject"
        else:
            why = f"false on {rejected} masked input(s) it must accept"
        lines.append(f'  subterm #{index} becomes {why}: {text}')
    return lines


def _guard_contrasts(item: Mapping[str, Any]) -> List[str]:
    """Show the minimal pair: two real inputs differing in one argument only."""
    lines = []
    for contrast in (item.get("contrasts") or [])[:2]:
        masked, exposed = contrast["masked"], contrast["exposed"]
        lines.append(
            "  contrast on " + str(contrast["only_differing_argument"]) + ": "
            + json.dumps(masked["args"], ensure_ascii=False) + " -> both versions return "
            + json.dumps(masked["out_plus"], ensure_ascii=False)
            + "; " + json.dumps(exposed["args"], ensure_ascii=False) + " -> "
            + json.dumps(exposed["out_plus"], ensure_ascii=False) + " vs "
            + json.dumps(exposed["out_minus"], ensure_ascii=False)
            + ". Only that one argument differs, so the guard must give different "
              "answers on these two inputs.")
    return lines


def repair_prompt(*, previous: Mapping[str, Any], failures: List[Mapping[str, Any]],
                  check_summary: str) -> str:
    blocks = []
    for item in failures:
        block = [f"RELATION {item.get('id')} ({item.get('kind')}) FAILED."]
        block.append(f"  expression: {item.get('expr')}")
        block.append(f"  condition:  {item.get('condition')}")
        if item.get("reason"):
            block.append(f"  checker note: {item['reason']}")
        diagnosis = _diagnosis(item)
        if diagnosis:
            block.append(f"  diagnosis:  {diagnosis}")
        examples = item.get("counterexamples") or []
        for example in examples[:3]:
            block.append("  counterexample: " + json.dumps(example, ensure_ascii=False))
        if item.get("kind") == "mask_guard":
            block.extend(_guard_blame(item))
            block.extend(_guard_contrasts(item))
        blocks.append("\n".join(block))
    return f"""\
The bounded checker tested your contract on {check_summary} and found the
problems below.

{chr(10).join(blocks)}

Revise only what is wrong. Reply with a patch object of this shape:
{{
  "revise": [{{"id": "<existing id>", "expr": "<new expr, optional>",
              "condition": "<new condition, optional>",
              "source_lines": [<lines>], "rationale": "<why it fixes the counterexample>"}}],
  "add_observers": [{{"id": "O9", "channel": <int>, "expr": "...", "condition": "...",
                     "source_lines": [..], "rationale": "..."}}],
  "mask_guard": {{"id": "G", "expr": "<revised guard>", "source_lines": [..]}},
  "uncertainty": "<updated>"
}}
Rules: every counterexample is a real execution of both versions. A relation
listed as failed is therefore wrong on a real input -- do not reply that it is
"already correct". Change the expression, the condition, or both. Do not
weaken a condition so that no input satisfies it. Do not enumerate operations
to delete. Do not claim any relation is proved. {LANGUAGE_SPEC}

Your previous contract was:
{json.dumps(previous, ensure_ascii=False, indent=2)}"""


# --------------------------------------------------------------------------
# Baselines
# --------------------------------------------------------------------------
def direct_prompt(*, source: str, target_line: int, domain_text: str,
                  signatures: Mapping[str, Any],
                  vocabulary: Mapping[str, str] | None = None) -> str:
    return f"""\
Program under analysis (line numbers are not part of the code).
Line {target_line} holds the single marked target A.

{numbered(source)}

Input domain: {domain_text}

Variable names in scope at A, with their sorts (nothing else exists):
{_vocabulary_text(vocabulary)}

Declared function types:
{_signatures_text(signatures)}

A is deleted in a second version. Read the whole program and directly infer
the condition under which the returned value is unchanged. Reply as JSON:
{{"mask_guard": "<bool expr>", "explanation": "<short>"}}

{LANGUAGE_SPEC}"""


def generic_summary_prompt(source: str) -> str:
    return f"""\
Summarize every user-defined function in this Python source: what it computes,
its input/output relation, loop invariants, and which information the final
returned value depends on. Do not analyse any deletion. Return JSON with one
key "functions" whose value is a list of compact per-function summaries.

{numbered(source)}"""


def generic_prompt(*, source: str, target_line: int, domain_text: str,
                   signatures: Mapping[str, Any], summary: str,
                   vocabulary: Mapping[str, str] | None = None) -> str:
    return f"""\
Program under analysis (line numbers are not part of the code).
Line {target_line} holds the single marked target A.

{numbered(source)}

Input domain: {domain_text}

Variable names in scope at A, with their sorts (nothing else exists):
{_vocabulary_text(vocabulary)}

Declared function types:
{_signatures_text(signatures)}

Generic function summaries produced without knowledge of this task:
{summary}

Using these summaries, infer the condition under which deleting A leaves the
returned value unchanged. Reply as JSON:
{{"mask_guard": "<bool expr>", "explanation": "<short>", "used_summaries": ["..."]}}

{LANGUAGE_SPEC}"""


FIXED_RELATIONS = [
    "SortedInput: xs == sorted(xs)",
    "MinAtHead: xs[0] == min(xs)",
    "MaxAtTail: xs[-1] == max(xs)",
    "AllEqual: all elements equal",
    "PermutationOnly: A only permutes the list",
    "DistinctCountPreserved: distinct(xs) unchanged by A",
    "SumPreserved: sum(xs) unchanged by A",
    "IdentityOnPre: the pre-condition makes A a no-op",
]


def fixed_relations_prompt(*, source: str, target_line: int, domain_text: str,
                           signatures: Mapping[str, Any],
                           vocabulary: Mapping[str, str] | None = None) -> str:
    menu = "\n".join(f"  - {item}" for item in FIXED_RELATIONS)
    return f"""\
Program under analysis (line numbers are not part of the code).
Line {target_line} holds the single marked target A.

{numbered(source)}

Input domain: {domain_text}

Variable names in scope at A, with their sorts (nothing else exists):
{_vocabulary_text(vocabulary)}

Declared function types:
{_signatures_text(signatures)}

A fixed menu of semantic relations is available:
{menu}

Select the relations that explain when deleting A leaves the returned value
unchanged, and build the guard from the selected relations only. Reply as JSON:
{{"selected_relations": ["<menu items>"], "mask_guard": "<bool expr>",
  "explanation": "<short>"}}

Guards may only use the variables and syntax below. {LANGUAGE_SPEC}"""
