"""Command line entry point.

    python -m mace.cli smoke
    python -m mace.cli analyze --fixture experiments/sort_channel.json --bundle my.json
    python -m mace.cli run --fixture experiments/sort_channel.json \
        --provider ollama --model qwen2.5-coder:7b --mode all --rounds 3
    python -m mace.cli report --dir runs/<run>
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import sys
from pathlib import Path

from . import sandbox
from .fixture import EXPERIMENT_DIR, PROJECT_ROOT, load_fixture
from .loop import CORE_LEVELS, run_mode, verify
from .qwen import QwenClient
from .sandbox import SandboxError


def _load_bundle_file(path: Path) -> dict:
    data = json.loads(path.read_text(encoding="utf-8"))
    if "bundle" in data and isinstance(data["bundle"], dict):
        return data["bundle"]
    return data


def _summarise(report: dict) -> dict:
    return {
        "status": report.get("status"),
        "evidence_level": report.get("evidence_level"),
        "guard_ok": report.get("guard_ok"),
        "all_relations_pass": report.get("all_relations_pass"),
        "guard": report.get("guard", {}).get("expr"),
        "guard_status": report.get("guard", {}).get("status"),
        "unsound": report.get("guard", {}).get("unsound"),
        "incomplete": report.get("guard", {}).get("incomplete"),
        "relations": {r["id"]: r["status"] for r in report.get("relations", [])},
        "observer_soundness": report.get("observer_soundness", {}).get("status"),
        "behaviour": report.get("behaviour"),
        "witnesses": report.get("witnesses"),
    }


def cmd_smoke(args) -> int:
    fixture = load_fixture(args.fixture)
    bundle_path = (Path(args.bundle) if args.bundle else
                   EXPERIMENT_DIR / "hidden" / f"{fixture.id}_reference.json")
    bundle = _load_bundle_file(bundle_path)
    try:
        report = verify(fixture, bundle, timeout=args.timeout,
                        core_logic=getattr(args, "core_logic", "legacy"))
    except SandboxError as exc:
        print("SANDBOX ERROR:", exc, file=sys.stderr)
        return 2
    print(json.dumps(_summarise(report), indent=2, ensure_ascii=False))
    ok = report.get("all_relations_pass") and report.get("guard_ok")
    print("SMOKE:", "PASS" if ok else "FAIL")
    return 0 if ok else 1


def cmd_run(args) -> int:
    fixture = load_fixture(args.fixture, seed=args.seed)
    client = QwenClient(provider=args.provider, model=args.model,
                        endpoint=args.endpoint, num_ctx=args.num_ctx,
                        temperature=args.temperature, seed=args.seed,
                        timeout=args.timeout)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    safe_model = re.sub(r"[^A-Za-z0-9.]+", "_", args.model)
    out_dir = Path(args.out) if args.out else (
        PROJECT_ROOT / "runs" / f"{fixture.id}_{safe_model}_{stamp}")
    out_dir.mkdir(parents=True, exist_ok=True)
    config = {
        "fixture": fixture.config,
        "fixture_path": str(Path(args.fixture)),
        "model_info": client.model_info(),
        "runtime": _runtime(client),
        "seed": args.seed, "rounds": args.rounds, "modes": args.modes,
        "num_ctx": args.num_ctx, "temperature": args.temperature,
        "core_logic": args.core_logic,
        "domain_size": len(fixture.domain), "domain_exhaustive": fixture.domain.exhaustive,
        "started_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
    }
    (out_dir / "config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False),
                                         encoding="utf-8")
    contract = None
    if "oracle" in args.modes:
        contract_path = (Path(args.contract) if args.contract else
                         EXPERIMENT_DIR / "hidden" / f"{fixture.id}_reference.json")
        contract = _load_bundle_file(contract_path)
        config["oracle_contract"] = str(contract_path)
        config["diagnostic_only"] = True
        (out_dir / "config.json").write_text(
            json.dumps(config, indent=2, ensure_ascii=False), encoding="utf-8")
    summary = []
    for mode in args.modes:
        print(f"== mode {mode} ==", flush=True)
        try:
            result = run_mode(fixture, client, mode, rounds=args.rounds,
                              seed=args.seed, out_dir=out_dir, timeout=args.timeout * 3,
                              guard_source=args.guard_source,
                              evidence_gate=args.evidence_gate,
                              contract_override=contract,
                              core_logic=args.core_logic)
        except SandboxError as exc:
            print("SANDBOX ERROR:", exc, file=sys.stderr)
            return 2
        item = {
            "mode": mode, "guard_source": args.guard_source,
            "core_logic": args.core_logic,
            "status": result["status"], "rounds_used": result["rounds_used"],
            "guard": result["final_guard"],
            "guard_status": (result.get("final_report") or {}).get("guard", {}).get("status"),
            "guard_ok": (result.get("final_report") or {}).get("guard_ok"),
            "usage": result["usage"],
        }
        summary.append(item)
        print(json.dumps(item, ensure_ascii=False), flush=True)
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False),
                                          encoding="utf-8")
    print("RESULTS:", out_dir.resolve())
    return 0


def _runtime(client: QwenClient):
    return {"ps": client.runtime_ps()}


def cmd_report(args) -> int:
    directory = Path(args.dir)
    rows = []
    for path in sorted(directory.glob("*_seed*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        report = data.get("final_report") or {}
        rows.append({
            "mode": data["mode"],
            "status": data["status"],
            "rounds_used": data["rounds_used"],
            "guard": data.get("final_guard"),
            "guard_status": report.get("guard", {}).get("status"),
            "relations": {r["id"]: r["status"] for r in report.get("relations", [])},
            "observer_soundness": report.get("observer_soundness", {}).get("status"),
            "behaviour": report.get("behaviour"),
            "prompt_tokens": data["usage"]["prompt_tokens"],
            "completion_tokens": data["usage"]["completion_tokens"],
            "wall_seconds": data["usage"]["wall_seconds"],
        })
    print(json.dumps(rows, indent=2, ensure_ascii=False))
    return 0


def cmd_analyze(args) -> int:
    return cmd_smoke(args)


def _expand_runs(items) -> list:
    roots = []
    for item in items:
        path = Path(item)
        if path.is_dir() and not any(path.glob("*_seed*.json")):
            roots.extend(sorted(p for p in path.iterdir() if p.is_dir()))
        else:
            roots.append(path)
    return roots


def cmd_summarize(args) -> int:
    from . import summarize

    rows = summarize.collect(_expand_runs(args.runs))
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
    print(summarize.markdown(rows))
    return 0


def cmd_diagnose(args) -> int:
    """Per-case stage decomposition: where did each run first go wrong?"""
    from . import diagnose

    rows = diagnose.collect(_expand_runs(args.runs))
    if args.json:
        payload = {"rows": rows, "proportions": diagnose.proportions(rows)}
        Path(args.json).write_text(json.dumps(payload, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
    print(diagnose.markdown(rows))
    if args.stages:
        print()
        print(diagnose.stage_markdown(rows))
    return 0


def cmd_cells(args) -> int:
    """2x2 diagnostic table: recompose every stored contract, no model calls."""
    from . import cells

    rows = cells.collect(Path(p) for p in args.runs)
    if args.json:
        Path(args.json).write_text(json.dumps(rows, indent=2, ensure_ascii=False),
                                   encoding="utf-8")
    print(cells.markdown(rows))
    return 0


def cmd_trace(args) -> int:
    """Where does the difference between P+ and P- stop, on a given input?"""
    fixture = load_fixture(args.fixture, seed=args.seed)
    if args.args:
        cases = [json.loads(args.args)]
    else:
        bundle_path = (Path(args.bundle) if args.bundle else
                       EXPERIMENT_DIR / "hidden" / f"{fixture.id}_reference.json")
        report = verify(fixture, _load_bundle_file(bundle_path), timeout=args.timeout)
        picks = report.get("witnesses") or []
        if not picks:
            print("no exposed witness in the domain; nothing to trace", file=sys.stderr)
            return 1
        cases = [w["args"] for w in picks[:args.limit]]
    try:
        traced = sandbox.trace_cases(fixture.source, cases, arg_sorts=fixture.arg_sorts,
                                     entry=fixture.entry, timeout=args.timeout)
    except SandboxError as exc:
        print("SANDBOX ERROR:", exc, file=sys.stderr)
        return 2
    for item in traced.get("traces", []):
        item.pop("traces", None) if not args.raw else None
    print(json.dumps(traced, indent=2, ensure_ascii=False))
    return 0


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__,
                                     formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = parser.add_subparsers(dest="command", required=True)

    smoke = sub.add_parser("smoke", help="verify a bundle on CPU (reference bundle by default)")
    smoke.add_argument("--fixture", default="sort_channel.json")
    smoke.add_argument("--bundle", default=None)
    smoke.add_argument("--timeout", type=float, default=180.0)
    smoke.add_argument("--core-logic", choices=list(CORE_LEVELS), default="legacy",
                       help="legacy keeps the historical checker; any other level "
                            "enables the repaired verifier")
    smoke.set_defaults(func=cmd_smoke)

    analyze = sub.add_parser("analyze", help="verify an arbitrary bundle file")
    analyze.add_argument("--fixture", required=True)
    analyze.add_argument("--bundle", required=True)
    analyze.add_argument("--timeout", type=float, default=180.0)
    analyze.set_defaults(func=cmd_analyze)

    run = sub.add_parser("run", help="run Qwen experiment modes")
    run.add_argument("--fixture", default="sort_channel.json")
    run.add_argument("--provider", choices=["ollama", "dashscope"], default="ollama")
    run.add_argument("--model", default="qwen2.5-coder:7b")
    run.add_argument("--endpoint", default=None)
    run.add_argument("--mode", default="all",
                     choices=["all", "direct", "generic", "fixed", "mace", "oracle"])
    run.add_argument("--guard-source", choices=["qwen", "derived"], default="qwen",
                     help="who writes the final guard: the model, or the composer")
    run.add_argument("--evidence-gate", action="store_true",
                     help="only WITNESS_VERIFIED relations may be composed; off by default")
    run.add_argument("--core-logic", choices=list(CORE_LEVELS), default="legacy",
                     help="legacy=historical behaviour; bugs=verifier fixes only; "
                          "candidates=fixes+candidate retention; "
                          "full=fixes+retention+witness-gated composition")
    run.add_argument("--contract", default=None,
                     help="contract for --mode oracle (diagnostic ceiling only)")
    run.add_argument("--rounds", type=int, default=3)
    run.add_argument("--seed", type=int, default=42)
    run.add_argument("--num-ctx", type=int, default=8192)
    run.add_argument("--temperature", type=float, default=0.0)
    run.add_argument("--timeout", type=float, default=180.0)
    run.add_argument("--out", default=None)
    run.set_defaults(func=cmd_run)

    trace = sub.add_parser("trace", help="diff the P+/P- execution traces on an input")
    trace.add_argument("--fixture", default="sort_channel.json")
    trace.add_argument("--args", default=None,
                       help='JSON object of entry arguments, e.g. \'{"xs": [0, -1], ...}\'')
    trace.add_argument("--bundle", default=None,
                       help="bundle whose exposed witnesses are traced when --args is absent")
    trace.add_argument("--limit", type=int, default=2)
    trace.add_argument("--raw", action="store_true", help="include the raw per-line traces")
    trace.add_argument("--seed", type=int, default=0)
    trace.add_argument("--timeout", type=float, default=180.0)
    trace.set_defaults(func=cmd_trace)

    report = sub.add_parser("report", help="summarise a run directory")
    report.add_argument("--dir", required=True)
    report.set_defaults(func=cmd_report)

    summary = sub.add_parser("summarize", help="cross-run table (rounds, guard, cost)")
    summary.add_argument("--runs", nargs="+", required=True)
    summary.add_argument("--json", default=None)
    summary.set_defaults(func=cmd_summarize)

    diag = sub.add_parser("diagnose", help="first failing stage per case")
    diag.add_argument("--runs", nargs="+", required=True)
    diag.add_argument("--json", default=None)
    diag.add_argument("--stages", action="store_true",
                      help="add the INVALID-vs-semantic split")
    diag.set_defaults(func=cmd_diagnose)

    cells = sub.add_parser("cells", help="2x2 diagnostic table from stored runs")
    cells.add_argument("--runs", nargs="+", required=True)
    cells.add_argument("--json", default=None)
    cells.set_defaults(func=cmd_cells)

    args = parser.parse_args(argv)
    if getattr(args, "mode", None):
        args.modes = (["direct", "generic", "fixed", "mace"] if args.mode == "all"
                      else [args.mode])
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
