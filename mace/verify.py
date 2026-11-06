"""Bounded verification of semantic contracts.

Every check here is *bounded*: it quantifies over the declared finite domain
(the collected paired executions).  A relation that survives the domain is
reported as ``BOUNDED`` (exhaustive domain) or ``TESTED`` (sampled domain).
Nothing in this module can produce ``PROVEN``.

Two obligations are kept separate, as required by the MACE design:

Observer soundness
    If the observation abstraction cannot distinguish two states, the real
    downstream program cannot distinguish their outputs either.

Target invariance (observer-relative)
    Under the stated condition, A does not change the observed value of a
    channel (and, composed over all channels, does not change the output).

The guard is checked against the actual paired executions as well, so an
LLM guard is never trusted on its own.
"""
from __future__ import annotations

import ast
from typing import Any, Callable, Dict, List, Mapping, Sequence

from . import terms
from .compose import compose_guard
from .contracts import Bundle, Relation
from .terms import Checked, Signature, TermError

MAX_EXAMPLES = 3

# Each contract field is evaluated in its own vocabulary.  When a name is not
# in scope, say which vocabulary that field has -- otherwise the model only sees
# "unknown variable" and has no way to know that, say, an upstream fact may not
# mention a local variable.
_SCOPE_HINTS = {
    "target_effect": ("target_effects see the entry arguments, the state just before A "
                      "under its plain names, and the state just after A under <name>_post"),
    "upstream": ("upstream relations are evaluated on the entry arguments only; local "
                 "variables computed before A are not in scope there"),
    "observer": ("observers see the entry arguments and the state after A under its plain "
                 "names; <name>_post belongs to target_effects only"),
    "mask_guard": ("mask_guard is evaluated on the entry arguments only; <name>_post exists "
                   "only inside target_effects"),
}


def _scope_note(kind: str, error: str) -> str:
    if "unknown variable" not in error:
        return error
    return f"{error}. {_SCOPE_HINTS.get(kind, '')}".rstrip()


def _channel_value(out: Any, channels: int, index: int) -> Any:
    if channels == 1:
        return out
    if isinstance(out, list) and index < len(out):
        return out[index]
    raise TermError(f"output channel {index} is missing")


def _snap_sorts(rows: Sequence[Dict[str, Any]],
                key: str) -> tuple[Dict[str, str], str | None]:
    """Infer the sorts of local variables in one snapshot; must be consistent."""
    found: Dict[str, str] = {}
    for row in rows:
        snap = row.get(key) or {}
        for name, value in snap.items():
            sort = terms.sort_of(value)
            if sort is None:
                return {}, f"unsupported sort for {key} variable {name}"
            if name in found and found[name] != sort:
                return {}, f"{key} variable {name} changes sort ({found[name]} vs {sort})"
            found[name] = sort
    return found, None


def _post_sorts(rows: Sequence[Dict[str, Any]]) -> tuple[Dict[str, str], str | None]:
    return _snap_sorts(rows, "snap_plus")


def _compile(rel: Relation, env_sorts: Mapping[str, str],
             functions: Mapping[str, Signature] | None,
             expr_sort: str | None = "bool",
             condition_sorts: Mapping[str, str] | None = None
             ) -> tuple[Checked | None, Checked | None, str | None]:
    # The observer expression lives in the post-A vocabulary, but its
    # *condition* is a predicate over the entry arguments.  Compiling both in
    # the post-A vocabulary let a condition mention an A-local name that the
    # evaluator could never supply.  The repaired path keeps the two
    # vocabularies separate; the legacy path remains available for replay.
    try:
        expr = Checked.build(rel.expr, env_sorts, functions)
        cond = Checked.build(rel.condition,
                             condition_sorts if condition_sorts is not None else env_sorts,
                             functions)
    except TermError as exc:
        return None, None, str(exc)
    if expr_sort is not None and expr.sort != expr_sort:
        return None, None, f"relation expression has sort {expr.sort}, expected {expr_sort}"
    if cond.sort != "bool":
        return None, None, f"condition has sort {cond.sort}, expected bool"
    return expr, cond, None


def _eval(checked: Checked, env: Mapping[str, Any],
          functions: Mapping[str, Signature],
          callables: Mapping[str, Callable[..., Any]]) -> Any:
    return terms.evaluate_checked(checked, env, functions, callables)


def _eval_part(node: Any, env: Mapping[str, Any],
               functions: Mapping[str, Signature],
               callables: Mapping[str, Callable[..., Any]]) -> Any:
    """Evaluate one top-level subterm of an already type-checked guard."""
    return terms.eval_node(node, env, functions, callables, 0)


def _example(row: Dict[str, Any], **extra: Any) -> Dict[str, Any]:
    # Checker-only facts live under "diagnostic": a flat "a_has_local_effect"
    # field was read back by one model as a program variable and copied into a
    # guard, so nothing that is not a program variable appears at top level.
    out = {
        "args": row["args"],
        "out_plus": row["out_plus"],
        "out_minus": row["out_minus"],
        "snap_plus": row.get("snap_plus"),
        "snap_minus": row.get("snap_minus"),
        "diagnostic": {"A_changed_local_state": row["a_has_local_effect"]},
    }
    out.update(extra)
    return out


def _ordered(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Counterexamples with a real local effect of A come first."""
    return sorted(rows, key=lambda r: (not r.get("a_has_local_effect"),))


def _guard_parts(tree: Any) -> tuple[List[Any], str | None]:
    """Top-level structure of the guard: its disjuncts, else conjuncts, else itself.

    Used to localize a guard failure to the subterm that caused it, instead of
    telling the model only "the guard is wrong".
    """
    if isinstance(tree, ast.BoolOp) and isinstance(tree.op, ast.Or):
        return list(tree.values), "or"
    if isinstance(tree, ast.BoolOp) and isinstance(tree.op, ast.And):
        return list(tree.values), "and"
    return [tree], None


def _check_relation(rel: Relation, rows: Sequence[Dict[str, Any]],
                    env_sorts: Mapping[str, str], value_env,
                    functions: Mapping[str, Signature],
                    callables: Mapping[str, Callable[..., Any]],
                    level: str) -> Dict[str, Any]:
    expr, cond, error = _compile(rel, env_sorts, functions)
    base = {"id": rel.id, "kind": rel.kind, "expr": rel.expr,
            "condition": rel.condition, "source_lines": rel.source_lines,
            "rationale": rel.rationale}
    if rel.channel is not None:
        base["channel"] = rel.channel
    if rel.role:
        base["role"] = rel.role
    if error:
        return {**base, "status": "INVALID", "reason": _scope_note(rel.kind, error),
                "checked": 0, "failures": 0, "counterexamples": []}

    checked = failures = skipped = 0
    counterexamples: List[Dict[str, Any]] = []
    for row in rows:
        try:
            values = value_env(row)
            condition_value = _eval(cond, values, functions, callables)
            if not condition_value:
                skipped += 1
                continue
            expr_value = _eval(expr, values, functions, callables)
            checked += 1
            if expr_value is not True:
                failures += 1
                if len(counterexamples) < MAX_EXAMPLES:
                    counterexamples.append(_example(row, expr_value=expr_value))
        except TermError as exc:
            failures += 1
            if len(counterexamples) < MAX_EXAMPLES:
                counterexamples.append(_example(row, error=str(exc)))
    status = level if failures == 0 else "REFUTED"
    return {**base, "status": status, "checked": checked,
            "condition_false": skipped, "failures": failures,
            "counterexamples": counterexamples}


def _fixed_point_of(rel: Relation, rows: Sequence[Dict[str, Any]],
                    input_sorts: Mapping[str, str],
                    functions: Mapping[str, Signature],
                    callables: Mapping[str, Callable[..., Any]]
                    ) -> tuple[int, int, List[Dict[str, Any]]]:
    """Does ``rel.condition`` really make A a no-op on the local state?"""
    try:
        cond = Checked.build(rel.condition, input_sorts, functions)
    except TermError:
        return 0, 1, []
    checked = failures = 0
    examples: List[Dict[str, Any]] = []
    for row in rows:
        try:
            if not _eval(cond, dict(row["args"]), functions, callables):
                continue
        except TermError:
            failures += 1
            continue
        checked += 1
        if row["snap_plus"] != row["snap_minus"]:
            failures += 1
            if len(examples) < MAX_EXAMPLES:
                examples.append(_example(row))
    return checked, failures, examples


def verify_bundle(rows: Sequence[Dict[str, Any]], bundle: Bundle, *,
                  input_sorts: Mapping[str, str],
                  functions: Mapping[str, Signature] | None = None,
                  callables: Mapping[str, Callable[..., Any]] | None = None,
                  level: str = "BOUNDED",
                  channels: int = 2,
                  core_logic: bool | str = False) -> Dict[str, Any]:
    # ``True`` keeps the original test-facing meaning: the full repaired path.
    core_level = ("full" if core_logic is True else
                  core_logic if core_logic in ("bugs", "candidates", "full")
                  else "legacy")
    core_enabled = core_level != "legacy"
    # Only the full level gates the composer on witness evidence.  Levels B/C
    # repair implementation defects without changing the composition policy.
    require_witness = core_level == "full"
    functions = functions or {}
    callables = callables or {}
    usable = [r for r in rows if r.get("err_plus") is None and r.get("err_minus") is None
              and isinstance(r.get("snap_plus"), dict) and isinstance(r.get("snap_minus"), dict)]
    post, post_error = _post_sorts(usable)
    pre_sorts, pre_error = _snap_sorts(usable, "snap_minus")
    post_env_sorts = dict(input_sorts)
    for name, sort in post.items():
        post_env_sorts[name] = sort

    def input_values(row):
        return dict(row["args"])

    def post_values(row, tag):
        env = dict(row["args"])
        env.update(row.get(f"snap_{tag}") or {})
        return env

    def effect_values(row):
        # ``x`` refers to the local state right before A (the P- snapshot),
        # ``x_post`` to the state right after A (the P+ snapshot).
        env = dict(row["args"])
        env.update(row.get("snap_minus") or {})
        for name, value in (row.get("snap_plus") or {}).items():
            env[name + "_post"] = value
        return env

    results: List[Dict[str, Any]] = []
    for rel in bundle.target_effects:
        env_sorts = dict(input_sorts)
        env_sorts.update(pre_sorts)
        env_sorts.update({k + "_post": v for k, v in post.items()})
        results.append(_check_relation(rel, usable, env_sorts, effect_values,
                                       functions, callables, level))
    for rel in bundle.upstream:
        row = _check_relation(rel, usable, dict(input_sorts), input_values,
                              functions, callables, level)
        if rel.role == "fixed_point" and row["status"] in ("BOUNDED", "TESTED"):
            # A relation being true is not enough: the *claim* is that its
            # condition makes A a no-op.  That implication is the only thing
            # that licenses putting the condition in the guard's OR, so it is
            # checked per relation and a failure demotes the relation.
            checked_fp, failed_fp, examples_fp = _fixed_point_of(
                rel, usable, input_sorts, functions, callables)
            row["fixed_point_checked"] = checked_fp
            row["fixed_point_failures"] = failed_fp
            if failed_fp:
                row["status"] = "REFUTED"
                row["reason"] = (f"the condition holds on {failed_fp} input(s) where A still "
                                 "changes the local state, so it is not a fixed point")
                row["counterexamples"] = _ordered(examples_fp)
        results.append(row)

    # An observer must reproduce the channel value in *both* versions, not just
    # in P+.  Checking only P+ let a model satisfy faithfulness by restating the
    # plus-side answer from the inputs (e.g. `fn_0(xs) if keep else 0`, which is
    # the P+ value but not the P- value), after which a condition of `True` would
    # compose into a guard `True`.  Two-sided faithfulness is a property of the
    # downstream computation and cannot be satisfied by ignoring A.
    observer_results: List[Dict[str, Any]] = []
    for rel in bundle.observers:
        expr, cond, error = _compile(
            rel, post_env_sorts, functions, expr_sort=None,
            condition_sorts=dict(input_sorts) if core_enabled else None)
        base = {"id": rel.id, "kind": rel.kind, "expr": rel.expr,
                "condition": rel.condition, "source_lines": rel.source_lines,
                "rationale": rel.rationale, "channel": rel.channel}
        if error:
            observer_results.append({**base, "status": "INVALID",
                                     "reason": _scope_note("observer", error),
                                     "checked": 0, "faithful_failures": 0,
                                     "faithful_minus_failures": 0,
                                     "invariance_checked": 0,
                                     "invariance_failures": 0,
                                     "evaluation_errors": 0,
                                     "counterexamples": []})
            continue
        faithful_fail = faithful_minus_fail = invariance_fail = 0
        invariance_checked = eval_errors = 0
        examples: List[Dict[str, Any]] = []
        for row in usable:
            try:
                if rel.channel is not None and rel.channel >= channels:
                    raise TermError(f"channel {rel.channel} out of range")
                index = int(rel.channel or 0)
                observed_plus = _eval(expr, post_values(row, "plus"), functions, callables)
                observed_minus = _eval(expr, post_values(row, "minus"), functions, callables)
                actual_plus = _channel_value(row["out_plus"], channels, index)
                actual_minus = _channel_value(row["out_minus"], channels, index)
                if observed_plus != actual_plus:
                    faithful_fail += 1
                    if len(examples) < MAX_EXAMPLES:
                        examples.append(_example(row, observed=observed_plus,
                                                 actual=actual_plus,
                                                 kind="faithfulness"))
                if observed_minus != actual_minus:
                    faithful_minus_fail += 1
                    if len(examples) < MAX_EXAMPLES:
                        examples.append(_example(row, observed=observed_minus,
                                                 actual=actual_minus,
                                                 kind="faithfulness_minus"))
                condition_value = _eval(cond, input_values(row), functions, callables)
                if condition_value:
                    invariance_checked += 1
                    if observed_plus != observed_minus:
                        invariance_fail += 1
                        if len(examples) < MAX_EXAMPLES:
                            examples.append(_example(row, observed_plus=observed_plus,
                                                     observed_minus=observed_minus,
                                                     kind="invariance"))
            except TermError as exc:
                eval_errors += 1
                if len(examples) < MAX_EXAMPLES:
                    examples.append(_example(row, error=str(exc), kind="evaluation"))
        ok = (faithful_fail == 0 and faithful_minus_fail == 0
              and invariance_fail == 0 and eval_errors == 0)
        observer_results.append({
            **base, "status": level if ok else "REFUTED",
            "checked": len(usable), "faithful_failures": faithful_fail,
            "faithful_minus_failures": faithful_minus_fail,
            "invariance_checked": invariance_checked,
            "invariance_failures": invariance_fail,
            "evaluation_errors": eval_errors,
            "counterexamples": _ordered(examples),
        })
    results.extend(observer_results)

    # ---- guard ---------------------------------------------------------
    guard_expr, guard_cond, guard_error = _compile(bundle.mask_guard, input_sorts, functions)
    guard_report: Dict[str, Any] = {
        "id": bundle.mask_guard.id, "expr": bundle.mask_guard.expr,
        "source_lines": bundle.mask_guard.source_lines,
    }
    if guard_error:
        reason = _scope_note("mask_guard", guard_error)
        guard_report.update({"status": "INVALID", "reason": reason,
                             "unsound": 0, "incomplete": 0, "checked": 0,
                             "evaluation_errors": 0, "exact": False,
                             "counterexamples": []})
    else:
        parts, shape = _guard_parts(guard_expr.tree)
        part_text = [ast.unparse(part) for part in parts]
        # How often each top-level subterm is responsible for a wrong verdict:
        # for a false accept, the subterm that made the guard true; for a false
        # reject, the subterm that made it false.
        blame = {"accepts_wrong": [0] * len(parts), "rejects_wrong": [0] * len(parts)}
        unsound = incomplete = checked = evaluation_errors = 0
        examples = []
        for row in usable:
            env = input_values(row)
            try:
                predicted = _eval(guard_expr, env, functions, callables)
            except TermError as exc:
                # Keep "could not evaluate" separate from "evaluated to false".
                # The legacy path folds it into `incomplete`; the repaired path
                # reports it as EVALUATION_ERROR and still fails the guard.
                evaluation_errors += 1
                if not core_enabled:
                    incomplete += 1
                if len(examples) < MAX_EXAMPLES:
                    examples.append(_example(row, error=str(exc)))
                continue
            checked += 1
            try:
                values = [_eval_part(part, env, functions, callables) for part in parts]
            except TermError:
                values = None
            real = bool(row["outputs_equal"])
            if predicted and not real:
                unsound += 1
                if values is not None:
                    for index, value in enumerate(values):
                        if value:
                            blame["accepts_wrong"][index] += 1
                if len(examples) < MAX_EXAMPLES:
                    examples.append(_example(row, kind="unsound", predicted=True,
                                             parts=values, part_text=part_text))
            elif real and not predicted:
                incomplete += 1
                if values is not None:
                    for index, value in enumerate(values):
                        if not value:
                            blame["rejects_wrong"][index] += 1
                if len(examples) < MAX_EXAMPLES:
                    examples.append(_example(row, kind="incomplete", predicted=False,
                                             parts=values, part_text=part_text))
        status = (level if (unsound == 0 and incomplete == 0
                            and evaluation_errors == 0) else "REFUTED")
        guard_report.update({"status": status, "checked": checked,
                             "unsound": unsound, "incomplete": incomplete,
                             "evaluation_errors": evaluation_errors,
                             "exact": (status in ("BOUNDED", "TESTED") and checked > 0
                                       and unsound == 0 and incomplete == 0
                                       and evaluation_errors == 0),
                             "shape": shape, "parts": part_text, "blame": blame,
                             "counterexamples": _ordered(examples)})
        if status == "REFUTED":
            guard_report["contrasts"] = _unexplained_contrasts(
                usable, list(input_sorts), guard_expr, functions, callables)

    # ---- observer soundness -------------------------------------------
    def _soundness(compiled: Sequence[Checked], used: Sequence[str]) -> Dict[str, Any]:
        groups: Dict[tuple, Any] = {}
        collisions = 0
        classes = 0
        for row in usable:
            try:
                env = post_values(row, "minus")
                key = tuple(_eval(c, env, functions, callables) for c in compiled)
                value = row["out_minus"]
            except TermError:
                collisions += 1
                continue
            key = tuple(repr(k) for k in key)
            if key not in groups:
                groups[key] = value
                classes += 1
            elif groups[key] != value:
                collisions += 1
        return {
            "status": level if collisions == 0 else "REFUTED",
            "classes": classes, "collisions": collisions,
            "checked": len(usable), "observers_used": list(used),
            "reason": "observation determines the real output" if collisions == 0
                      else "two states with equal observation differ in output",
        }

    soundness: Dict[str, Any] = {"status": "UNKNOWN", "reason": "no complete observer set"}
    if post_error:
        soundness = {"status": "UNKNOWN", "reason": post_error}
    elif core_enabled:
        # Several observers may describe one channel.  The legal contract shape
        # is "at least one verified observer per channel", not "exactly one
        # relation per channel".  Use one verified observer per channel for the
        # soundness check; all of them stay available to the composer's OR.
        result_by_id = {r["id"]: r for r in observer_results}
        missing_observers = [
            ch for ch in range(channels)
            if not any(rel.channel == ch
                       and result_by_id.get(rel.id, {}).get("status") in ("BOUNDED", "TESTED")
                       for rel in bundle.observers)
        ]
        if missing_observers:
            soundness = {"status": "UNKNOWN",
                         "reason": f"no verified observer for channels {missing_observers}"}
        else:
            compiled = []
            used = []
            try:
                for ch in range(channels):
                    rel = next(rel for rel in bundle.observers
                               if rel.channel == ch
                               and result_by_id.get(rel.id, {}).get("status") in ("BOUNDED", "TESTED"))
                    compiled.append(Checked.build(rel.expr, post_env_sorts, functions))
                    used.append(rel.id)
            except (TermError, StopIteration) as exc:
                soundness = {"status": "UNKNOWN", "reason": str(exc)}
            else:
                soundness = _soundness(compiled, used)
    elif observer_results and all(r["status"] in ("BOUNDED", "TESTED") for r in observer_results)             and sorted(r["channel"] for r in observer_results) == list(range(channels)):
        compiled = []
        try:
            for ch in range(channels):
                rel = next(r for r in bundle.observers if r.channel == ch)
                compiled.append(Checked.build(rel.expr, post_env_sorts, functions))
        except TermError as exc:
            soundness = {"status": "UNKNOWN", "reason": str(exc)}
        else:
            soundness = _soundness(compiled, [r.id for r in bundle.observers
                                              if r.channel is not None])

    # ---- composition ----------------------------------------------------
    upstream_ok = [r for r in results if r["kind"] == "upstream" and r["status"] in ("BOUNDED", "TESTED")]
    fixed_all = [r for r in results
                 if r["kind"] == "upstream" and r.get("role") == "fixed_point"]
    fixed_ok = [r for r in fixed_all if r["status"] in ("BOUNDED", "TESTED")]
    if not fixed_all:
        fixed_point: Dict[str, Any] = {
            "status": "UNKNOWN",
            "reason": "no upstream relation with role='fixed_point' was verified"}
    else:
        failures = sum(r.get("fixed_point_failures") or 0 for r in fixed_all)
        checked_fp = sum(r.get("fixed_point_checked") or 0 for r in fixed_all)
        examples = [c for r in fixed_all for c in (r.get("counterexamples") or [])]
        if core_enabled:
            bad_members = [r["id"] for r in fixed_all
                           if r.get("status") not in ("BOUNDED", "TESTED")]
            if failures:
                fp_status = "REFUTED"
                fp_reason = ("a fixed-point condition holds where A still changes "
                             "the state")
            elif checked_fp == 0 or bad_members:
                fp_status = "UNKNOWN"
                fp_reason = ("no fixed-point witness: the aggregate would have "
                             "checked=0 (unverified members: "
                             f"{bad_members or [r['id'] for r in fixed_all]})")
            else:
                fp_status = level
                fp_reason = ("every fixed-point condition implies A is a no-op on "
                             "the local state")
        else:
            fp_status = level if failures == 0 else "REFUTED"
            fp_reason = ("every fixed-point condition implies A is a no-op on the "
                         "local state" if failures == 0 else
                         "a fixed-point condition holds where A still changes the state")
        fixed_point = {"status": fp_status,
                       "checked": checked_fp, "failures": failures,
                       "counterexamples": _ordered(examples[:MAX_EXAMPLES]),
                       "reason": fp_reason}

    # The deterministic composer only ever rearranges conditions the checker
    # accepted, so it cannot add information the contract did not already
    # contain -- that is exactly the point of measuring it separately from the
    # model's own free-form guard.
    composed = compose_guard(bundle, {"relations": results}, channels,
                             require_witness=require_witness)
    # A composed result that exists but lacks a channel is INCOMPLETE, not
    # UNKNOWN: the composer knows exactly what is missing.  Keep the historical
    # label when the repaired path is off.
    no_expr_status = ("INCOMPLETE"
                      if core_enabled and composed["status"] == "INCOMPLETE"
                      else "UNKNOWN")
    derived: Dict[str, Any] = {
        **{k: v for k, v in composed.items() if k != "status"},
        "compose_status": composed["status"],
        "status": no_expr_status,
        "reason": composed.get("reason"),
    }
    if composed["expr"]:
        try:
            composed_expr = Checked.build(composed["expr"], input_sorts, functions)
        except TermError as exc:
            derived.update({"status": "INVALID", "reason": str(exc),
                            "unsound": 0, "incomplete": 0, "counterexamples": []})
        else:
            unsound = incomplete = 0
            examples = []
            for row in usable:
                try:
                    predicted = bool(_eval(composed_expr, input_values(row), functions, callables))
                except TermError as exc:
                    incomplete += 1
                    if len(examples) < MAX_EXAMPLES:
                        examples.append(_example(row, error=str(exc)))
                    continue
                real = bool(row["outputs_equal"])
                if predicted and not real:
                    unsound += 1
                    if len(examples) < MAX_EXAMPLES:
                        examples.append(_example(row, kind="unsound", predicted=True))
                elif real and not predicted:
                    incomplete += 1
                    if len(examples) < MAX_EXAMPLES:
                        examples.append(_example(row, kind="incomplete", predicted=False))
            agrees = None
            if guard_error is None:
                try:
                    agrees = all(
                        bool(_eval(composed_expr, input_values(row), functions, callables))
                        == bool(_eval(guard_expr, input_values(row), functions, callables))
                        for row in usable)
                except TermError:
                    agrees = None
            derived.update({
                "status": level if (unsound == 0 and incomplete == 0) else "REFUTED",
                "unsound": unsound, "incomplete": incomplete,
                "counterexamples": _ordered(examples),
                "same_as_guard": (composed["expr"].replace("(", " ").replace(")", " ").split()
                                  == bundle.mask_guard.expr.replace("(", " ").replace(")", " ").split()),
                "equivalent_to_declared_guard_on_domain": agrees,
            })

    # ---- behaviour classes ---------------------------------------------
    local_inactive = active_masked = active_exposed = 0
    witnesses: List[Dict[str, Any]] = []
    for row in usable:
        if not row["a_has_local_effect"]:
            local_inactive += 1
        elif row["outputs_equal"]:
            active_masked += 1
        else:
            active_exposed += 1
            if len(witnesses) < MAX_EXAMPLES:
                witnesses.append({"args": row["args"], "out_plus": row["out_plus"],
                                  "out_minus": row["out_minus"],
                                  "snap_plus": row["snap_plus"],
                                  "snap_minus": row["snap_minus"]})

    # ---- attribution ----------------------------------------------------
    contrast = _contrast(usable, list(input_sorts))
    dag = proof_dag(bundle, fixed_ok, guard_report)

    guard_ok = guard_report.get("status") in ("BOUNDED", "TESTED") and len(usable) > 0
    all_pass = all(r["status"] in ("BOUNDED", "TESTED") for r in results) \
        and guard_ok and soundness.get("status") in ("BOUNDED", "TESTED")
    return {
        "guard_ok": guard_ok,
        "evidence_level": level,
        "domain_size": len(rows),
        "usable_rows": len(usable),
        "execution_errors": len(rows) - len(usable),
        "post_sorts": post,
        "relations": results,
        "guard": guard_report,
        "observer_soundness": soundness,
        "composition": {"upstream_fixed_point": fixed_point, "derived_guard": derived},
        "behaviour": {"local_inactive": local_inactive, "active_masked": active_masked,
                      "active_exposed": active_exposed},
        "witnesses": witnesses,
        "attribution": {"contrast": contrast, "proof_dag": dag},
        "all_relations_pass": all_pass,
    }


def proof_dag(bundle: Bundle, fixed_ok: Sequence[Dict[str, Any]],
              guard_report: Mapping[str, Any]) -> Dict[str, Any]:
    """Structural record of how the guard is composed from the relations.

    This is the shared-structure form the design calls for: the guard node is
    an OR over fixed-point conditions and an AND over observer conditions, so
    relations are *composed*, never enumerated as source-operation subsets.
    """
    def field(rel: Any, name: str, default: Any = None) -> Any:
        if hasattr(rel, name):
            return getattr(rel, name)
        return rel.get(name, default) if isinstance(rel, dict) else default

    def node(rel: Any, kind: str, **extra: Any) -> Dict[str, Any]:
        return {"id": field(rel, "id"), "kind": kind,
                "source_lines": list(field(rel, "source_lines") or []), **extra}

    nodes = [node(r, "target_effect") for r in bundle.target_effects]
    nodes += [node(r, "upstream", role=r.role) for r in bundle.upstream]
    nodes += [node(r, "observer", channel=r.channel) for r in bundle.observers]
    nodes.append(node(bundle.mask_guard, "mask_guard",
                      status=guard_report.get("status")))
    edges = []
    for rel in fixed_ok:
        edges.append({"from": rel["id"], "to": bundle.mask_guard.id, "op": "or"})
    for rel in bundle.observers:
        edges.append({"from": rel.id, "to": bundle.mask_guard.id, "op": "and"})
    supported = {e["from"] for e in edges}
    return {
        "nodes": nodes,
        "edges": edges,
        "unsupported": [r.id for r in bundle.upstream if r.id not in supported],
        "shape": "guard = (OR fixed_point conditions) OR (AND observer conditions)",
    }


def _unexplained_contrasts(rows: Sequence[Dict[str, Any]], arg_names: Sequence[str],
                           guard: Checked, functions: Mapping[str, Signature],
                           callables: Mapping[str, Callable[..., Any]],
                           limit: int = 3) -> List[Dict[str, Any]]:
    """Contrasts that the current guard still gets wrong, with both real outputs.

    Two inputs that differ in exactly one argument, one masked and one exposed,
    are the smallest possible evidence that that argument matters here.  Feeding
    back one of them is far more useful to the model than a count of failures,
    and it is still a record of real executions, not a hint at the answer.
    """
    found: List[Dict[str, Any]] = []
    for arg in arg_names:
        groups: Dict[tuple, List[Dict[str, Any]]] = {}
        for row in rows:
            key = tuple((k, repr(v)) for k, v in sorted(row["args"].items()) if k != arg)
            groups.setdefault(key, []).append(row)
        for members in groups.values():
            masked = next((r for r in members if r["outputs_equal"]), None)
            exposed = next((r for r in members if not r["outputs_equal"]), None)
            if masked is None or exposed is None:
                continue
            try:
                predicted_masked = bool(_eval(guard, masked["args"], functions, callables))
                predicted_exposed = bool(_eval(guard, exposed["args"], functions, callables))
            except TermError:
                continue
            if predicted_masked and not predicted_exposed:
                continue          # the guard already separates them correctly
            found.append({
                "only_differing_argument": arg,
                "masked": {"args": masked["args"], "out_plus": masked["out_plus"],
                           "out_minus": masked["out_minus"], "guard_says": predicted_masked},
                "exposed": {"args": exposed["args"], "out_plus": exposed["out_plus"],
                            "out_minus": exposed["out_minus"], "guard_says": predicted_exposed},
            })
            # one contrast per argument, so the feedback covers different causes
            # instead of three variations of the same one
            break
        if len(found) >= limit:
            return found
    return found


def _contrast(rows: Sequence[Dict[str, Any]], arg_names: Sequence[str]) -> Dict[str, Any]:
    """Level-3 attribution: which input component is causally necessary.

    For every argument we group the domain by the *other* arguments and ask
    whether the masked/unmasked verdict ever differs inside one group.  A group
    where it does is a contrast condition: everything is held fixed except that
    one argument, and the verdict flips -- so that component is necessary for
    masking in that context, on real executions.
    """
    if not rows or not arg_names:
        return {"status": "UNKNOWN", "reason": "no usable inputs"}
    per_arg: Dict[str, Any] = {}
    for arg in arg_names:
        groups: Dict[tuple, List[Dict[str, Any]]] = {}
        for row in rows:
            key = tuple((k, repr(v)) for k, v in sorted(row["args"].items()) if k != arg)
            groups.setdefault(key, []).append(row)
        flip_groups = 0
        example = None
        for key, members in groups.items():
            verdicts = {bool(r["outputs_equal"]) for r in members}
            if len(verdicts) < 2:
                continue
            flip_groups += 1
            if example is None:
                masked = next((r for r in members if r["outputs_equal"]), None)
                exposed = next((r for r in members if not r["outputs_equal"]), None)
                if masked is not None and exposed is not None:
                    example = {
                        "same_args_except": arg,
                        "args": {k: v for k, v in masked["args"].items() if k != arg},
                        "masked": {"value": masked["args"][arg],
                                   "out_plus": masked["out_plus"],
                                   "out_minus": masked["out_minus"]},
                        "exposed": {"value": exposed["args"][arg],
                                    "out_plus": exposed["out_plus"],
                                    "out_minus": exposed["out_minus"]},
                    }
        per_arg[arg] = {"contexts": len(groups), "contexts_with_flip": flip_groups,
                        "causally_relevant": flip_groups > 0, "example": example}
    return {"status": "TESTED", "arguments": per_arg,
            "causally_relevant": [a for a, v in per_arg.items() if v["causally_relevant"]]}


def derived_text(bundle: Bundle, upstream_ok: Sequence[Dict[str, Any]]) -> str:
    parts = [r["condition"] for r in upstream_ok]
    downstream = " and ".join(f"({r.condition})" for r in bundle.observers)
    if parts:
        return " ".join(("(" + " or ".join(parts) + ") or (" + downstream + ")").split())
    return " ".join(downstream.split())


def failing_relations(report: Mapping[str, Any]) -> List[Dict[str, Any]]:
    out = []
    for rel in report.get("relations", []):
        if rel["status"] not in ("BOUNDED", "TESTED"):
            out.append(rel)
    guard = report.get("guard", {})
    if guard.get("status") not in ("BOUNDED", "TESTED"):
        out.append({"id": guard.get("id", "G"), "kind": "mask_guard", **guard})
    return out
