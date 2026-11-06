"""The 2x2 diagnostic table, computed from stored runs.

    cell A  Qwen contract  + Qwen guard          (the system as shipped)
    cell B  Qwen contract  + deterministic guard (same contract, recomposed)
    cell C  reviewed contract + Qwen guard       (diagnostic ceiling only)
    cell D  reviewed contract + deterministic    (diagnostic ceiling only)

A and B share a contract, so B is obtained by re-verifying the stored bundle
with the composer's guard in place of the model's: no extra model calls and no
confound from a different repair trajectory.  C reuses the reviewed relations
from ``experiments/hidden``; D is pure CPU.

Every guard here is re-checked under the *current* checker, so old and new runs
are compared on the same obligation set (two-sided observer faithfulness).
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Iterable, List, Mapping

from .fixture import EXPERIMENT_DIR, load_fixture
from .loop import verify

GOOD = ("BOUNDED", "TESTED")


def _reference(fixture_id: str) -> Dict[str, Any]:
    path = EXPERIMENT_DIR / "hidden" / f"{fixture_id}_reference.json"
    return json.loads(path.read_text(encoding="utf-8"))["bundle"]


def _with_guard(bundle: Mapping[str, Any], expr: str) -> Dict[str, Any]:
    out = json.loads(json.dumps(bundle))
    out.setdefault("mask_guard", {"id": "G"})["expr"] = expr
    return out


def _blank_guard(status: str = "UNKNOWN", expr: str | None = None) -> Dict[str, Any]:
    return {"status": status, "parse_ok": False, "typecheck_ok": False, "sound": False,
            "complete": False, "exact": False, "expr": expr}


def _guard_row(report: Mapping[str, Any]) -> Dict[str, Any]:
    if "guard" not in report:
        return _blank_guard(report.get("status") or "ERROR", report.get("expr"))
    guard = report.get("guard") or {}
    usable = guard.get("status") != "INVALID"
    ok = guard.get("status") in GOOD
    return {
        "status": guard.get("status"),
        "parse_ok": usable,
        "typecheck_ok": usable,
        # A REFUTED guard can still be one-sided: zero unsound rows means it
        # never accepts an exposed input, which is the safety property.  Report
        # soundness independently of the BOUNDED/REFUTED verdict.
        "sound": usable and not guard.get("unsound"),
        "complete": usable and not guard.get("incomplete"),
        "exact": ok and not guard.get("unsound") and not guard.get("incomplete"),
        "expr": guard.get("expr"),
    }


def _contract_row(report: Mapping[str, Any]) -> Dict[str, Any]:
    rels = [r for r in report.get("relations") or [] if r.get("kind") != "mask_guard"]
    good = [r for r in rels if r.get("status") in GOOD]
    return {
        "relations_total": len(rels),
        "relations_good": len(good),
        "verified": bool(rels) and len(good) == len(rels),
        "statuses": {r["id"]: r["status"] for r in rels},
    }


def _attribution(report: Mapping[str, Any], reference: Mapping[str, Any]) -> Dict[str, Any]:
    """Do the cited lines overlap the reviewed contract's cited lines?

    This is a coarse check of source grounding: it cannot prove a cited line
    supports a relation, only that the model pointed at the same regions the
    reviewer did.
    """
    ref_lines = set()
    for key in ("target_effects", "upstream", "observers", "mask_guard"):
        value = reference.get(key)
        items = value if isinstance(value, list) else [value or {}]
        for item in items:
            ref_lines.update(int(x) for x in item.get("source_lines") or [])
    covered = cited = 0
    for rel in report.get("relations") or []:
        lines = set(int(x) for x in rel.get("source_lines") or [])
        if not lines:
            continue
        cited += 1
        if lines & ref_lines:
            covered += 1
    guard_lines = set(int(x) for x in (report.get("guard") or {}).get("source_lines") or [])
    return {
        "relations_cited": cited,
        "relations_on_reference_lines": covered,
        "guard_on_reference_lines": bool(guard_lines & ref_lines),
        "reference_lines": sorted(ref_lines),
    }


def _case(run_path: Path, data: Mapping[str, Any]) -> Dict[str, Any]:
    fixture_id = data.get("fixture")
    fixture = load_fixture(f"{fixture_id}.json")
    bundle = data.get("final_bundle")
    usage = data.get("usage") or {}
    base = {
        "run": run_path.parent.name,
        "run_file": run_path.name,
        "fixture": fixture_id,
        "model": data.get("model"),
        "mode": data.get("mode"),
        "tokens": usage.get("prompt_tokens"),
        "completion_tokens": usage.get("completion_tokens"),
        "wall_seconds": usage.get("wall_seconds"),
        "rounds": data.get("rounds_used"),
    }
    if not bundle:
        # Guard-only baselines store no bundle; their final report already holds
        # the checked guard, so they can sit in the same table.
        report = data.get("final_report") or {}
        if not report:
            return {**base, "cell": None, "note": "no report"}
        return {
            **base,
            "cell": data.get("mode"),
            "contract_source": "none",
            "contract": {"relations_total": 0, "relations_good": 0,
                         "verified": False, "statuses": {}},
            "guard_qwen": _guard_row(report),
            "guard_derived": _blank_guard("ABSENT"),
            "derived_compose_status": None,
            "equivalent_to_reference_guard": None,
            "attribution": _attribution(report, _reference(fixture_id)),
            "diagnostic_only": bool(data.get("diagnostic_only")),
        }
    report = verify(fixture, bundle, timeout=180)
    derived = (report.get("composition") or {}).get("derived_guard") or {}
    derived_report = None
    if derived.get("expr"):
        try:
            derived_report = verify(fixture, _with_guard(bundle, derived["expr"]), timeout=180)
        except Exception as exc:            # noqa: BLE001 - recorded, not swallowed
            derived_report = {"error": f"{type(exc).__name__}: {exc}"}
    reference = _reference(fixture_id)
    return {
        **base,
        "cell": "A" if data.get("mode") == "mace" else ("C" if data.get("mode") == "oracle" else data.get("mode")),
        "contract_source": "reviewed" if data.get("mode") == "oracle" else "qwen",
        "contract": _contract_row(report),
        "guard_qwen": _guard_row(report),
        "guard_derived": (_guard_row(derived_report) if derived_report else
                          _blank_guard(derived.get("compose_status") or "UNKNOWN",
                                       derived.get("expr"))),
        "derived_compose_status": derived.get("compose_status"),
        "equivalent_to_reference_guard": derived.get("equivalent_to_declared_guard_on_domain"),
        "attribution": _attribution(report, reference),
        "diagnostic_only": bool(data.get("diagnostic_only")),
    }


def collect(runs: Iterable[Path]) -> List[Dict[str, Any]]:
    rows = []
    for run in runs:
        if run.is_file() and run.suffix == ".json":
            files = [run]
        elif run.is_dir() and any(run.glob("*_seed*.json")):
            files = sorted(run.glob("*_seed*.json"))
        else:
            files = sorted(p for d in run.glob("*") if d.is_dir()
                           for p in d.glob("*_seed*.json")) if run.is_dir() else []
        for path in files:
            try:
                data = json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            rows.append(_case(path, data))
    return rows


def markdown(rows: List[Dict[str, Any]]) -> str:
    head = ("| fixture | cell | contract | typed | sound | complete | exact | "
            "contract verified | attn | tokens | s |")
    lines = [head, "|" + "---|" * 11]
    for r in rows:
        if r.get("cell") is None:
            continue
        for source in ("qwen", "derived"):
            g = r[f"guard_{source}"]
            cell = r["cell"]
            if source == "derived" and cell not in ("A", "C"):
                continue
            label = cell
            if cell == "A" and source == "derived":
                label = "B"
            if cell == "C" and source == "derived":
                label = "D"
            attn = r["attribution"]
            lines.append(
                f"| {r['fixture']} | {label} | {r['contract_source']} | "
                f"{'y' if g['typecheck_ok'] else 'n'} | {'y' if g['sound'] else 'n'} | "
                f"{'y' if g['complete'] else 'n'} | {'y' if g['exact'] else 'n'} | "
                f"{'y' if r['contract']['verified'] else 'n'} "
                f"({r['contract']['relations_good']}/{r['contract']['relations_total']}) | "
                f"{attn['relations_on_reference_lines']}/{attn['relations_cited']} | "
                f"{r['tokens']} | {round(r['wall_seconds'] or 0, 1)} |")
    return "\n".join(lines)
