#!/usr/bin/env python3
"""MACE semantic-core microprototype.

Purpose:
- Start from one annotated target A (not from pre-labeled masking sites).
- Build both program versions by deleting A at the AST level.
- Check Qwen-proposed masking guards against bounded paired executions.
- Distinguish soundness and completeness counterexamples.
- Demonstrate jointly necessary downstream observation guards.

No Qwen inference, formal proof, or general-purpose Python verification is claimed.
Only run the source-code fixture below; this is not a sandbox for untrusted programs.
"""
import ast
import copy
import itertools
import json
import sys
from pathlib import Path

PROGRAM_SOURCE = """
def stable_order(xs):
    result = []
    for value in xs:
        pos = len(result)
        while pos > 0 and result[pos - 1] > value:
            pos -= 1
        result.insert(pos, value)
    return result

def fold_one(xs):
    value = xs[0]
    for item in xs[1:]:
        if item < value:
            value = item
    return value

def fold_two(xs):
    value = xs[0]
    for item in xs[1:]:
        if item > value:
            value = item
    return value

def program(xs, pre, use_left, use_right):
    if pre:
        xs = stable_order(xs)

    xs = sorted(xs)  # TARGET_A

    first = fold_one(xs) if use_left else xs[0]
    last = fold_two(xs) if use_right else xs[-1]
    return first, last
"""

def make_versions(source):
    lines = source.splitlines()
    sites = [i for i, line in enumerate(lines, 1) if "# TARGET_A" in line]
    if len(sites) != 1:
        raise ValueError("Expected exactly one TARGET_A marker")
    target_line = sites[0]

    original_tree = ast.parse(source)
    deleted_tree = copy.deepcopy(original_tree)

    class DeleteA(ast.NodeTransformer):
        def visit_Assign(self, node):
            if node.lineno == target_line:
                return ast.copy_location(ast.Pass(), node)
            return self.generic_visit(node)

    deleted_tree = ast.fix_missing_locations(DeleteA().visit(deleted_tree))
    namespace_original, namespace_deleted = {}, {}
    exec(compile(original_tree, "<original>", "exec"), namespace_original)
    exec(compile(deleted_tree, "<without-A>", "exec"), namespace_deleted)
    return namespace_original["program"], namespace_deleted["program"], target_line

# An intentionally small, non-evaluating expression language for external contracts.
# Unlike eval(), this cannot execute arbitrary Qwen-supplied Python expressions.
def eval_guard(formula, values):
    expression = ast.parse(formula, mode="eval").body

    def interpret(node):
        if isinstance(node, ast.Name):
            if node.id not in values:
                raise ValueError("Unknown variable: " + node.id)
            return values[node.id]
        if isinstance(node, ast.Constant):
            if not isinstance(node.value, (int, bool)):
                raise ValueError("Unsupported literal")
            return node.value
        if isinstance(node, ast.UnaryOp):
            if isinstance(node.op, ast.Not):
                return not interpret(node.operand)
            if isinstance(node.op, ast.USub):
                return -interpret(node.operand)
        if isinstance(node, ast.BoolOp):
            children = (bool(interpret(x)) for x in node.values)
            if isinstance(node.op, ast.And):
                return all(children)
            if isinstance(node.op, ast.Or):
                return any(children)
        if isinstance(node, ast.Subscript):
            sequence = interpret(node.value)
            index = interpret(node.slice)
            if not isinstance(sequence, list) or index not in (0, -1):
                raise ValueError("Only xs[0] and xs[-1] supported")
            return sequence[index]
        if isinstance(node, ast.Call):
            if (not isinstance(node.func, ast.Name) or
                node.func.id not in ("min", "max") or
                len(node.args) != 1 or node.keywords):
                raise ValueError("Unsupported function call")
            arg = interpret(node.args[0])
            if not isinstance(arg, list) or not arg:
                raise ValueError("min/max require nonempty list")
            return min(arg) if node.func.id == "min" else max(arg)
        if isinstance(node, ast.Compare):
            if (len(node.ops) != 1 or len(node.comparators) != 1 or
                not isinstance(node.ops[0], ast.Eq)):
                raise ValueError("Only == comparisons supported")
            return interpret(node.left) == interpret(node.comparators[0])
        raise ValueError("Unsupported expression node: " + type(node).__name__)

    return bool(interpret(expression))

def finite_domain():
    for length in range(1, 6):
        for sequence in itertools.product([-1, 0, 1, 2], repeat=length):
            for pre, use_left, use_right in itertools.product([False, True], repeat=3):
                yield {
                    "xs": list(sequence),
                    "pre": pre,
                    "use_left": use_left,
                    "use_right": use_right,
                }

def check_guard(original, without_a, guard, domain):
    report = {
        "total": 0, "soundness_counterexamples": 0,
        "completeness_counterexamples": 0,
        "first_unsound": None, "first_incomplete": None,
        "local_inactive": 0, "active_masked": 0, "active_exposed": 0,
    }
    for state in domain:
        inputs = (state["xs"], state["pre"], state["use_left"], state["use_right"])
        actual_original = original(*inputs)
        actual_without_a = without_a(*inputs)
        actual_masked = actual_original == actual_without_a
        proposed_masked = eval_guard(guard, state)
        local_active = not state["pre"] and sorted(state["xs"]) != state["xs"]

        report["total"] += 1
        if not local_active:
            report["local_inactive"] += 1
        elif actual_masked:
            report["active_masked"] += 1
        else:
            report["active_exposed"] += 1

        if proposed_masked and not actual_masked:
            report["soundness_counterexamples"] += 1
            if report["first_unsound"] is None:
                report["first_unsound"] = state
        if actual_masked and not proposed_masked:
            report["completeness_counterexamples"] += 1
            if report["first_incomplete"] is None:
                report["first_incomplete"] = state
    return report

def paired_witness(original, without_a, xs, pre, use_left, use_right):
    args = (xs, pre, use_left, use_right)
    return {
        "pre": pre, "use_left": use_left, "use_right": use_right,
        "with_A": original(*args), "without_A": without_a(*args),
        "difference": original(*args) != without_a(*args),
    }

def main():
    original, without_a, target_line = make_versions(PROGRAM_SOURCE)

    # Example only. In a real run these guards are supplied by local Qwen.
    proposed = [
        ("H0_sufficient_but_incomplete", "pre or (use_left and use_right)"),
        ("H1_channel_factorization",
         "pre or ((use_left or xs[0] == min(xs)) and "
         "(use_right or xs[-1] == max(xs)))"),
    ]
    if len(sys.argv) > 1:
        candidate_text = Path(sys.argv[1]).read_text(encoding="utf-8").strip()
        if candidate_text.startswith("{"):
            candidate_text = json.loads(candidate_text)["mask_guard"]
        proposed = [("external_candidate", candidate_text)]

    print("TARGET_A_LINE:", target_line)
    for label, guard in proposed:
        print(label + ":", json.dumps(
            {"guard": guard, "result": check_guard(original, without_a, guard, finite_domain())},
            ensure_ascii=False, default=str
        ))

    xs = [2, 0, 1]
    print("JOINT_MASKING_WITNESSES:")
    for flags in [(False, True, True),
                  (False, False, True),
                  (False, True, False),
                  (True, False, False)]:
        print(json.dumps(paired_witness(original, without_a, xs, *flags)))

    request = {
        "source": PROGRAM_SOURCE,
        "target_A_line": target_line,
        "task": "Given only the marked A, infer the observable equivalence conditions between the original program and the version without A. Do not guess or enumerate source-operation subsets.",
        "required": [
            "Derive the local state relation induced by A",
            "Work backwards from output channels to derive observer-relative relations",
            "Infer missing loop properties from function bodies, not function names",
            "Supply mask_guard in the supported restricted expression language",
            "Give source spans justifying each derived relation, without pre-labeled B sites",
            "Keep unproven hypotheses distinct from verified semantic facts"
        ],
        "allowed_guard_names": ["xs", "pre", "use_left", "use_right"],
        "checker_supported_syntax": ["and", "or", "not", "==", "xs[0]", "xs[-1]", "min(xs)", "max(xs)"],
        "warning": "The checker tests a finite input domain; it does not prove arbitrary Python programs or automatically verify source provenance.",
    }
    output = Path(__file__).with_name("mace_qwen_obligation.json")
    output.write_text(json.dumps(request, ensure_ascii=False, indent=2), encoding="utf-8")
    print("QWEN_OBLIGATION:", str(output))

if __name__ == "__main__":
    main()
