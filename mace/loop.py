"""Counterexample-guided experiment driver.

Modes
-----
mace     typed contract bundle -> bounded verification -> targeted repair patch
direct   one-shot guard prediction from the whole program
generic  function summaries (produced without the deletion task) -> guard
fixed    guard composed from a fixed menu of semantic relations
"""
from __future__ import annotations

import copy
import datetime as dt
import json
import time
from pathlib import Path
from typing import Any, Dict, List, Mapping

from . import prompts, sandbox
from .contracts import ContractError, parse_bundle
from .core_logic import (CandidatePool, GOOD, classify_guard_report,
                         guard_exact)
from .evidence_gate import (WITNESS_VERIFIED, compose_gated, gate_report)
from .fixture import Fixture
from .qwen import ModelError, QwenClient, extract_json

OK_STATES = ("BOUNDED", "TESTED")


def _now() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _tokens(stats: Mapping[str, Any]) -> tuple[int, int]:
    if "prompt_tokens" in stats or "completion_tokens" in stats:
        return int(stats.get("prompt_tokens") or 0), int(stats.get("completion_tokens") or 0)
    usage = stats.get("usage") or {}
    return int(usage.get("prompt_tokens") or 0), int(usage.get("completion_tokens") or 0)


class EventLog:
    def __init__(self, path: Path):
        self.path = path
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: Dict[str, Any]) -> None:
        with self.path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps({"ts": _now(), **event}, ensure_ascii=False) + "\n")


def _guard_only_bundle(guard: str) -> Dict[str, Any]:
    return {"target_effects": [], "upstream": [], "observers": [],
            "mask_guard": {"id": "G", "expr": guard, "source_lines": []},
            "uncertainty": ""}


def verify(fixture: Fixture, bundle: Dict[str, Any], timeout: float = 300.0,
           core_logic: bool = False) -> Dict[str, Any]:
    return sandbox.analyze(
        fixture.source, fixture.domain.cases, bundle,
        arg_sorts=fixture.arg_sorts, functions=fixture.functions,
        channels=fixture.channels, level=fixture.domain.evidence_level,
        entry=fixture.entry, timeout=timeout, core_logic=core_logic,
    )


def _evaluate_guard(fixture: Fixture, expr: str, timeout: float = 300.0) -> Dict[str, Any]:
    """Re-check one guard expression on the current domain, with no relations."""
    bundle = parse_bundle(_guard_only_bundle(expr), allow_guard_only=True)
    return verify(fixture, bundle.to_dict(), timeout=timeout, core_logic="full")


def _with_guard(bundle: Dict[str, Any], expr: str) -> Dict[str, Any]:
    out = copy.deepcopy(dict(bundle))
    guard = dict(out.get("mask_guard") or {"id": "G"})
    guard["expr"] = expr
    out["mask_guard"] = guard
    return out


def _derived_expr(report: Mapping[str, Any]) -> str | None:
    return ((report.get("composition") or {}).get("derived_guard") or {}).get("expr")


def apply_patch(previous: Mapping[str, Any], patch: Mapping[str, Any]) -> tuple[Dict[str, Any], List[str]]:
    """Apply a model repair patch; returns (bundle_dict, audit notes)."""
    out = copy.deepcopy(dict(previous))
    notes: List[str] = []
    by_id: Dict[str, Dict[str, Any]] = {}
    for group in ("target_effects", "upstream", "observers"):
        for rel in out.setdefault(group, []):
            by_id[rel.get("id")] = rel
    by_id[out.setdefault("mask_guard", {}).get("id", "G")] = out["mask_guard"]
    for item in patch.get("revise") or []:
        if not isinstance(item, dict):
            notes.append("ignored non-object revise item")
            continue
        ident = item.get("id")
        if ident not in by_id:
            notes.append(f"ignored revise for unknown id {ident!r}")
            continue
        before = (by_id[ident].get("expr"), by_id[ident].get("condition"))
        for key in ("expr", "condition", "source_lines", "rationale"):
            if key in item:
                by_id[ident][key] = item[key]
        after = (by_id[ident].get("expr"), by_id[ident].get("condition"))
        notes.append(f"revised {ident}" if after != before else f"unchanged {ident}")
    for item in patch.get("add_observers") or []:
        if isinstance(item, dict):
            out.setdefault("observers", []).append(item)
            notes.append(f"added observer {item.get('id')}")
    guard_patch = patch.get("mask_guard")
    if isinstance(guard_patch, dict):
        if isinstance(guard_patch.get("expr"), str) and guard_patch["expr"].strip():
            merged = dict(out.get("mask_guard") or {})
            merged.update({k: v for k, v in guard_patch.items() if v is not None})
            merged.setdefault("id", "G")
            out["mask_guard"] = merged
            notes.append("replaced mask_guard")
        else:
            notes.append("ignored mask_guard patch without an expr; previous guard kept")
    if "uncertainty" in patch:
        out["uncertainty"] = patch["uncertainty"]
    return out, notes


def _same_relations(a: Mapping[str, Any], b: Mapping[str, Any]) -> bool:
    """True when two contracts claim exactly the same relations.

    ``role`` and ``channel`` are part of the claim: a patch that only flips a
    relation from ``supporting`` to ``fixed_point`` (or moves it to another
    channel) changes the composed guard and must not be reported as unchanged.
    """
    def sig(bundle: Mapping[str, Any]):
        out = []
        for group in ("target_effects", "upstream", "observers"):
            for rel in bundle.get(group) or []:
                out.append((group, rel.get("id"), rel.get("expr"),
                            rel.get("condition"), rel.get("role"),
                            rel.get("channel")))
        guard = bundle.get("mask_guard") or {}
        out.append(("mask_guard", None, guard.get("expr"), None, None, None))
        return out
    return sig(a) == sig(b)


def _failures(report: Mapping[str, Any], evidence_gate: bool = False) -> List[Dict[str, Any]]:
    out = []
    for rel in report.get("relations", []):
        if evidence_gate and rel.get("evidence_status") not in (None, WITNESS_VERIFIED):
            out.append(rel)
            continue
        if rel.get("status") not in OK_STATES:
            out.append(rel)
    guard = report.get("guard", {})
    if guard.get("status") not in OK_STATES:
        out.append({**guard, "kind": "mask_guard", "id": guard.get("id", "G")})
    return out


def _guard_feedback(guard: str | None, report: Mapping[str, Any], invalid: str = "") -> str:
    if invalid:
        return (f"Your previous response could not be used: {invalid}\n"
                "Return valid JSON with a non-empty 'mask_guard' string.\n" + prompts.LANGUAGE_SPEC)
    guard_report = report.get("guard", {})
    lines = [f"Your guard was: {guard}",
             f"The bounded checker ran {report.get('usable_rows')} paired executions."]
    if guard_report.get("unsound"):
        lines.append(f"UNSOUND in {guard_report['unsound']} cases: the guard accepts an input "
                     "where the two versions differ. First counterexample: "
                     + json.dumps((guard_report.get('counterexamples') or [{}])[0], ensure_ascii=False))
    if guard_report.get("incomplete"):
        lines.append(f"INCOMPLETE in {guard_report['incomplete']} cases: outputs are equal but the "
                     "guard rejects the input. First counterexample: "
                     + json.dumps((guard_report.get('counterexamples') or [{}])[0], ensure_ascii=False))
    if guard_report.get("reason"):
        lines.append(f"Checker note: {guard_report['reason']}")
    lines.append("Revise the guard. Do not enumerate operations to delete; reason from the source. "
                 "The checker only tested a finite domain. Reply with JSON containing 'mask_guard'.")
    return "\n".join(lines)


CORE_LEVELS = ("legacy", "bugs", "candidates", "full")


def run_mode(fixture: Fixture, client: QwenClient, mode: str, *, rounds: int,
             seed: int, out_dir: Path, timeout: float = 300.0,
             guard_source: str = "qwen",
             evidence_gate: bool = False,
             contract_override: Dict[str, Any] | None = None,
             core_logic: str = "legacy") -> Dict[str, Any]:
    """One experimental cell.

    ``guard_source`` selects who writes the final guard:

    * ``qwen``     -- the model writes ``mask_guard`` (cells A and C),
    * ``derived``  -- the deterministic composer writes it from the relations
      that the checker accepted (cells B and D).  The model's own guard is still
      verified and stored under ``qwen_guard`` for comparison.

    ``evidence_gate`` only annotates relation evidence (see
    ``mace.evidence_gate``); with ``guard_source="derived"`` it restricts the
    composer to ``WITNESS_VERIFIED`` relations and refuses to emit a guard when
    no gated composition covers every channel.  The default is off, so stored
    results and historical behaviour are unchanged.

    ``mode="oracle"`` supplies a human-reviewed contract through
    ``contract_override`` and asks only for the guard.  It is a diagnostic of
    the ceiling (cells C/D), never an automated result.
    """
    if core_logic not in CORE_LEVELS:
        raise ValueError(
            f"unknown core_logic {core_logic!r}; expected one of {CORE_LEVELS}")
    if guard_source not in ("qwen", "derived"):
        raise ValueError(f"unknown guard_source {guard_source}")
    if mode == "oracle" and contract_override is None:
        raise ValueError("oracle mode needs a contract_override")
    out_dir.mkdir(parents=True, exist_ok=True)
    events = EventLog(out_dir / "events.jsonl")
    started = time.perf_counter()
    calls_before = len(client.calls)
    exchanges: List[Dict[str, Any]] = []
    system = {"role": "system", "content": prompts.SYSTEM}
    status = "NO_RESULT"
    final_guard: str | None = None
    final_report: Dict[str, Any] | None = None
    final_bundle: Dict[str, Any] | None = None
    rounds_used = 0
    candidate_rounds: List[Dict[str, Any]] = []
    pool: CandidatePool | None = None

    try:
        vocabulary = _vocabulary(fixture, timeout)
        if mode == "oracle":
            # Cell D: nothing to ask.  Verify the reviewed contract, compose the
            # guard deterministically, and record both.
            if guard_source == "derived":
                rounds_used = 0
                report = verify(fixture, contract_override, timeout=timeout)
                derived = _derived_expr(report)
                if derived:
                    bundle = parse_bundle(_with_guard(contract_override, derived))
                    report2 = verify(fixture, bundle.to_dict(), timeout=timeout)
                    report2["derived_from"] = "oracle contract"
                    report = report2
                    final_guard = derived
                    final_bundle = bundle.to_dict()
                final_report = report
                exchanges.append({"round": 0, "bundle": contract_override,
                                  "report": report, "guard_source": "derived"})
                status = "GUARD_VERIFIED" if report.get("guard_ok") else "GUARD_REFUTED"
                events.write({"kind": "verification", "mode": mode, "round": 0,
                              "guard_source": "derived",
                              "guard_ok": report.get("guard_ok")})
            else:
                # Cell C: reviewed relations in, model writes only the guard.
                user = prompts.oracle_guard_prompt(
                    source=fixture.source, target_line=_target_line(fixture.source),
                    domain_text=fixture.domain_text(), signatures=fixture.functions,
                    channels=fixture.channels, contract=contract_override,
                    vocabulary=vocabulary)
                messages = [system, {"role": "user", "content": user}]
                for round_id in range(1, rounds + 1):
                    rounds_used = round_id
                    response = client.chat(messages, purpose=f"oracle/round{round_id}")
                    raw_text = response.content
                    guard = None
                    report = None
                    invalid = ""
                    try:
                        raw = extract_json(raw_text)
                        guard = raw.get("mask_guard")
                        if not isinstance(guard, str) or not guard.strip():
                            raise ValueError("missing 'mask_guard' string")
                        bundle_dict = _with_guard(contract_override, guard)
                        report = verify(fixture, bundle_dict, timeout=timeout)
                    except (ValueError, ContractError) as exc:
                        invalid = str(exc)
                    exchanges.append({"round": round_id, "stats": response.stats,
                                      "raw_response": raw_text, "guard": guard,
                                      "report": report, "error": invalid or None,
                                      "request": messages})
                    if guard is not None:
                        final_guard = guard
                        final_bundle = _with_guard(contract_override, guard)
                    if report is not None:
                        final_report = report
                    if report is not None and report.get("guard_ok"):
                        status = "GUARD_VERIFIED"
                        break
                    if round_id < rounds:
                        messages = messages + [
                            {"role": "assistant", "content": raw_text},
                            {"role": "user", "content":
                             _guard_feedback(guard, report or {}, invalid)}]
                if status == "NO_RESULT" and final_report is not None:
                    status = "ROUNDS_EXHAUSTED"
        elif mode == "mace":
            user = prompts.contract_prompt(
                source=fixture.source, target_line=_target_line(fixture.source),
                domain_text=fixture.domain_text(), signatures=fixture.functions,
                channels=fixture.channels, entry=fixture.entry,
                vocabulary=vocabulary)
            messages = [system, {"role": "user", "content": user}]
            previous_bundle: Dict[str, Any] | None = None
            core_verify = core_logic != "legacy"
            verify_level: bool | str = core_logic if core_verify else False
            pool = (CandidatePool(prefer="qwen")
                    if core_logic in ("candidates", "full") else None)
            for round_id in range(1, rounds + 1):
                rounds_used = round_id
                response = client.chat(messages, purpose=f"mace/round{round_id}")
                raw_text = response.content
                patch_notes: List[str] = []
                try:
                    raw = extract_json(raw_text)
                    if previous_bundle is not None and (
                            "revise" in raw or "add_observers" in raw):
                        raw, patch_notes = apply_patch(previous_bundle, raw)
                    elif previous_bundle is not None and "target_effects" not in raw:
                        raise ContractError(
                            "expected a repair patch with 'revise'/'add_observers' "
                            "or a full contract with 'target_effects'")
                    bundle = parse_bundle(raw)
                except (ValueError, ContractError) as exc:
                    exchanges.append({"round": round_id, "stats": response.stats,
                                      "raw_response": raw_text, "error": f"parse: {exc}",
                                      "request": messages})
                    events.write({"kind": "parse_error", "mode": mode, "round": round_id,
                                  "error": str(exc), "response": raw_text})
                    messages = messages + [
                        {"role": "assistant", "content": raw_text},
                        {"role": "user", "content":
                         f"Your previous reply was not a valid MACE contract: {exc}\n"
                         "Return the complete JSON contract again, in exactly the shape "
                         "requested, using only ids that already exist plus the new ones "
                         "you introduce."}]
                    continue
                bundle_dict = bundle.to_dict()
                qwen_report = verify(fixture, bundle_dict, timeout=timeout,
                                     core_logic=verify_level)
                qwen_guard = bundle.mask_guard.expr
                if evidence_gate:
                    # Annotate, do not overwrite: the original statuses stay in
                    # the record, and only the gated set may be composed.
                    qwen_report = gate_report(qwen_report)
                report = qwen_report
                derived_expr: str | None = None
                derived_report: Dict[str, Any] | None = None
                derived_bundle: Dict[str, Any] | None = None
                selected: Dict[str, Any] | None = None
                if core_verify:
                    derived_expr = _derived_expr(qwen_report)
                    if derived_expr:
                        derived_bundle = _with_guard(bundle_dict, derived_expr)
                        derived_report = verify(fixture, derived_bundle,
                                                timeout=timeout, core_logic="full")
                        derived_report["guard_source"] = "derived"
                        derived_report["qwen_guard"] = {
                            "expr": qwen_guard,
                            "status": qwen_report["guard"]["status"],
                            "unsound": qwen_report["guard"].get("unsound"),
                            "incomplete": qwen_report["guard"].get("incomplete"),
                        }
                    if core_logic == "bugs":
                        # Only verifier/control-flow defects are repaired here:
                        # stop once the guard itself is exact, even when an
                        # auxiliary relation is still failing.  No candidate
                        # retention is applied at this level.
                        report = qwen_report
                        final_bundle = bundle_dict
                        final_guard = qwen_guard
                        final_report = qwen_report
                    else:
                        assert pool is not None
                        pool.offer({"expr": qwen_guard, "source": "qwen",
                                    "round": round_id, "guard": qwen_report.get("guard"),
                                    "bundle": bundle_dict, "report": qwen_report})
                        if derived_expr:
                            pool.offer({"expr": derived_expr, "source": "derived",
                                        "round": round_id,
                                        "guard": (derived_report or {}).get("guard"),
                                        "bundle": derived_bundle,
                                        "report": derived_report})
                        # Every stored candidate is re-checked on the *current*
                        # domain.  A later round cannot silently overwrite an
                        # earlier exact guard, while a new counterexample can
                        # still revoke one.
                        pool.recheck(lambda expr: _evaluate_guard(
                            fixture, expr, timeout=timeout))
                        selected = pool.select()
                        if selected is None:
                            report = qwen_report
                            final_bundle = bundle_dict
                            final_guard = qwen_guard
                            final_report = qwen_report
                        else:
                            final_bundle = (selected.get("bundle")
                                            or _with_guard(bundle_dict, selected["expr"]))
                            selected_report = verify(fixture, final_bundle,
                                                     timeout=timeout, core_logic="full")
                            selected_report["candidate_source"] = selected.get("source")
                            selected_report["candidate_round"] = selected.get("round")
                            if selected.get("source") == "derived":
                                selected_report["guard_source"] = "derived"
                                selected_report["qwen_guard"] = {
                                    "expr": qwen_guard,
                                    "status": qwen_report["guard"]["status"],
                                    "unsound": qwen_report["guard"].get("unsound"),
                                    "incomplete": qwen_report["guard"].get("incomplete"),
                                }
                            report = selected_report
                            final_guard = selected["expr"]
                            final_report = selected_report
                elif guard_source == "derived":
                    if evidence_gate:
                        composed = compose_gated(bundle, report, fixture.channels)
                        derived_expr = composed.get("expr")
                    else:
                        derived_expr = _derived_expr(report)
                    if derived_expr:
                        bundle_dict = _with_guard(bundle_dict, derived_expr)
                        report = verify(fixture, bundle_dict, timeout=timeout)
                        report["guard_source"] = "derived"
                        if evidence_gate:
                            report["evidence_gate"] = qwen_report.get("evidence_gate")
                        report["qwen_guard"] = {
                            "expr": qwen_guard,
                            "status": qwen_report["guard"]["status"],
                            "unsound": qwen_report["guard"].get("unsound"),
                            "incomplete": qwen_report["guard"].get("incomplete"),
                        }
                    elif evidence_gate:
                        # No WITNESS_VERIFIED relation set can cover every
                        # channel, so there is no guard claim to make.
                        status = "NO_VERIFIED_COMPOSITION"
                        final_report = report
                        final_bundle = bundle_dict
                        final_guard = None
                        rounds_used = round_id
                        exchanges.append({"round": round_id, "stats": response.stats,
                                          "raw_response": raw_text, "bundle": bundle_dict,
                                          "patch_notes": patch_notes,
                                          "report": report, "request": messages})
                        events.write({"kind": "verification", "mode": mode,
                                      "round": round_id, "bundle": bundle_dict,
                                      "status": report.get("status"),
                                      "all_pass": report.get("all_relations_pass"),
                                      "guard_ok": report.get("guard_ok"),
                                      "evidence_gate": True,
                                      "no_verified_composition": True})
                        break
                else:
                    report = qwen_report
                if not core_verify:
                    final_bundle = bundle_dict
                    final_guard = (bundle_dict.get("mask_guard") or {}).get("expr")
                    final_report = report

                round_record = {
                    "round": round_id,
                    "domain_size": report.get("usable_rows"),
                    "domain_level": report.get("evidence_level"),
                    "qwen_guard": qwen_guard,
                    "qwen_status": qwen_report["guard"].get("status"),
                    "qwen_classification": classify_guard_report(qwen_report),
                    "false_accepts": qwen_report["guard"].get("unsound"),
                    "false_rejects": qwen_report["guard"].get("incomplete"),
                    "evaluation_errors": qwen_report["guard"].get("evaluation_errors"),
                    "invalid_relations": [r["id"] for r in qwen_report.get("relations", [])
                                          if r.get("status") == "INVALID"],
                    "unknown_relations": [r["id"] for r in qwen_report.get("relations", [])
                                          if r.get("status") not in GOOD],
                    "derived_guard": derived_expr,
                    "derived_status": ((derived_report or {}).get("guard") or {}).get("status"),
                    "derived_classification": (classify_guard_report(derived_report)
                                               if derived_report else None),
                    "selected_guard": final_guard,
                    "selection_reason": (selected or {}).get("selection_reason"),
                    "all_relations_pass": report.get("all_relations_pass"),
                }
                candidate_rounds.append(round_record)
                exchanges.append({"round": round_id, "stats": response.stats,
                                  "raw_response": raw_text, "bundle": bundle_dict,
                                  "patch_notes": patch_notes,
                                  "report": report, "request": messages,
                                  "candidate_round": round_record})
                events.write({"kind": "verification", "mode": mode, "round": round_id,
                              "bundle": bundle_dict,
                              "status": report.get("status"),
                              "all_pass": report.get("all_relations_pass"),
                              "guard_ok": report.get("guard_ok"),
                              "evidence_gate": evidence_gate,
                              "core_logic": core_logic,
                              "failures": [r.get("id") for r in
                                           _failures(report, evidence_gate)]})

                if core_verify:
                    if core_logic == "bugs":
                        if guard_exact(qwen_report.get("guard") or {}):
                            status = ("ALL_VERIFIED"
                                      if qwen_report.get("all_relations_pass")
                                      else "GUARD_VERIFIED")
                            break
                    elif (selected or {}).get("exact"):
                        status = ("ALL_VERIFIED"
                                  if report.get("all_relations_pass")
                                  else "GUARD_VERIFIED")
                        break
                if report.get("status") != "OK":
                    status = report.get("status", "UNKNOWN")
                    break
                if report.get("all_relations_pass"):
                    status = "ALL_VERIFIED"
                    break
                prior, previous_bundle = previous_bundle, bundle_dict
                # The model repairs its own contract.  In the repaired modes an
                # exact guard is judged on its own, not coupled to whether some
                # auxiliary relation also passed.
                if core_verify:
                    failures = _failures(qwen_report, evidence_gate)
                elif guard_source == "derived":
                    failures = [f for f in _failures(qwen_report, evidence_gate)
                                if f.get("kind") != "mask_guard"]
                else:
                    failures = _failures(report, evidence_gate)
                feedback = prompts.repair_prompt(
                    previous=previous_bundle, failures=failures,
                    check_summary=f"{report.get('usable_rows')} paired executions "
                                  f"({report.get('evidence_level')} domain)")
                if prior is not None and _same_relations(prior, bundle_dict):
                    feedback = ("Your previous patch left every expression and condition "
                                "unchanged, so exactly the same counterexamples still hold. "
                                "You must change them.\n\n" + feedback)
                messages = messages + [
                    {"role": "assistant", "content": raw_text},
                    {"role": "user", "content": feedback}]
                events.write({"kind": "feedback", "mode": mode, "round": round_id,
                              "failed": [f.get("id") for f in failures]})
            if status == "NO_RESULT" and final_report is not None:
                status = "ROUNDS_EXHAUSTED"
        else:
            messages = [system, {"role": "user", "content": _baseline_prompt(
                fixture, mode, client, vocabulary)}]
            for round_id in range(1, rounds + 1):
                rounds_used = round_id
                response = client.chat(messages, purpose=f"{mode}/round{round_id}")
                raw_text = response.content
                invalid = ""
                guard = None
                report = None
                try:
                    raw = extract_json(raw_text)
                    guard = raw.get("mask_guard")
                    if not isinstance(guard, str) or not guard.strip():
                        raise ValueError("missing 'mask_guard' string")
                    bundle = parse_bundle(_guard_only_bundle(guard), allow_guard_only=True)
                    report = verify(fixture, bundle.to_dict(), timeout=timeout)
                except (ValueError, ContractError) as exc:
                    invalid = str(exc)
                exchanges.append({"round": round_id, "stats": response.stats,
                                  "raw_response": raw_text, "guard": guard,
                                  "report": report, "error": invalid or None,
                                  "request": messages})
                events.write({"kind": "verification", "mode": mode, "round": round_id,
                              "guard": guard, "invalid": invalid,
                              "guard_status": (report or {}).get("guard", {}).get("status"),
                              "guard_ok": (report or {}).get("guard_ok")})
                if guard is not None:
                    final_guard = guard
                if report is not None:
                    final_report = report
                if report is not None and report.get("guard_ok"):
                    status = "GUARD_VERIFIED"
                    break
                if round_id < rounds:
                    messages = messages + [
                        {"role": "assistant", "content": raw_text},
                        {"role": "user", "content":
                         _guard_feedback(guard, report or {}, invalid)}]
            if status == "NO_RESULT" and final_report is not None:
                status = "ROUNDS_EXHAUSTED"
    except ModelError as exc:
        status = "MODEL_ERROR"
        exchanges.append({"error": f"model: {exc}"})
        events.write({"kind": "model_error", "mode": mode, "error": str(exc)})

    calls = client.calls[calls_before:]
    prompt_tokens = completion_tokens = 0
    wall = 0.0
    for call in calls:
        p, c = _tokens(call["stats"])
        prompt_tokens += p
        completion_tokens += c
        wall += float(call["stats"].get("wall_seconds") or 0.0)

    result = {
        "fixture": fixture.id, "mode": mode, "provider": client.provider,
        "guard_source": guard_source, "evidence_gate": evidence_gate,
        "diagnostic_only": mode == "oracle",
        "model": client.model, "seed": seed, "rounds_allowed": rounds,
        "rounds_used": rounds_used, "status": status,
        "final_guard": final_guard, "final_bundle": final_bundle,
        "final_report": final_report, "exchanges": exchanges,
        "usage": {"calls": len(calls), "prompt_tokens": prompt_tokens,
                  "completion_tokens": completion_tokens, "decode_seconds": round(wall, 3),
                  "wall_seconds": round(time.perf_counter() - started, 3)},
        "domain": {"size": len(fixture.domain), "exhaustive": fixture.domain.exhaustive},
        "core_logic": core_logic,
        "candidate_rounds": candidate_rounds if mode == "mace" else [],
        "candidate_history": (pool.history()
                              if mode == "mace" and pool is not None else []),
        "candidate_selection": (pool.select()
                                if mode == "mace" and pool is not None else None),
        "generated_utc": _now(),
    }
    path = out_dir / f"{mode}_seed{seed}.json"
    path.write_text(json.dumps(result, indent=2, ensure_ascii=False), encoding="utf-8")
    return result


def _target_line(source: str) -> int:
    for index, line in enumerate(source.splitlines(), 1):
        if "# TARGET_A" in line:
            return index
    raise ValueError("no TARGET_A marker")


def _vocabulary(fixture: Fixture, timeout: float) -> Dict[str, str]:
    """Variable names/sorts at A, probed in the sandbox on a single input."""
    try:
        probe = sandbox.probe_vocabulary(
            fixture.source, fixture.domain.cases[0], arg_sorts=fixture.arg_sorts,
            entry=fixture.entry, timeout=min(timeout, 120.0))
    except (sandbox.SandboxError, IndexError):
        return dict(fixture.arg_sorts)
    return probe.get("vocabulary") or dict(fixture.arg_sorts)


def _baseline_prompt(fixture: Fixture, mode: str, client: QwenClient,
                     vocabulary: Mapping[str, str] | None = None) -> str:
    if mode == "direct":
        return prompts.direct_prompt(source=fixture.source, target_line=_target_line(fixture.source),
                                     domain_text=fixture.domain_text(),
                                     signatures=fixture.functions,
                                     vocabulary=vocabulary)
    if mode == "fixed":
        return prompts.fixed_relations_prompt(
            source=fixture.source, target_line=_target_line(fixture.source),
            domain_text=fixture.domain_text(), signatures=fixture.functions,
            vocabulary=vocabulary)
    if mode == "generic":
        summary_resp = client.chat(
            [{"role": "system", "content": "Return concise JSON."},
             {"role": "user", "content": prompts.generic_summary_prompt(fixture.source)}],
            purpose="generic/summary")
        try:
            summary = json.dumps(extract_json(summary_resp.content), ensure_ascii=False)
        except ValueError:
            summary = summary_resp.content[:4000]
        return prompts.generic_prompt(
            source=fixture.source, target_line=_target_line(fixture.source),
            domain_text=fixture.domain_text(), signatures=fixture.functions,
            summary=summary, vocabulary=vocabulary)
    raise ValueError(f"unknown mode {mode}")
