"""Reliable deterministic masking analyzer (independent version 1).

What this version changes relative to ``benchmark_baseline.ast_method``:
  * candidates are collected from the target state key (Name, Attribute,
    Subscript) with exact AST node identity and source span;
  * "downstream" is decided by dynamic event order from P+ and P- traces, not
    by source line number;
  * candidates executed only on the P- fallback path are included;
  * the tracer matches code objects once, so no per-line realpath;
  * MSMS (keep-only) and MMBS (delete-only) are validated separately;
  * a bounded combination search is retained for cooperative / fallback sets;
  * observations are classified into RETURN / LEGAL_RAISE / PROBE_CRASH /
    NONZERO, and intervention crashes are not reported as exposed relations;
  * UNKNOWN / UNVERIFIED / FALSE / BROKEN_INTERVENTION / OUT_OF_BUDGET remain
    distinct statuses.

It reads only public task bundles, public probes, and public sources.
"""
from __future__ import annotations

import ast
import hashlib
import itertools
import json
import os
import shutil
import subprocess
import tempfile
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from benchmark_baseline.ast_method import PUBLIC_FILE_CACHE
from benchmark_baseline.prompts import PUBLIC
from benchmark_real_v3.config import KIT
from benchmark_real_v3.config import PROJECTS as V3_PROJECTS
from benchmark_real_v3.variant_lab import build_variant as v3_build_variant
from benchmark_real_v3.variant_lab import run_probe as v3_run_probe

HERE = Path(__file__).resolve().parent
TRACER = HERE / "tracer.py"
V4_ROOT = Path("<local-path>")
V4_PYTHON = "<local-path>"
V4_PROBES = HERE / "probes"
VARIANT_ROOT = Path("D:/tmp/relv1_variants")
MAX_EVENTS = 50000
MAX_SUBSETS_PER_ROW = 24
MAX_COMBO_SIZE = 5
MAX_CLAIMS = 8


@dataclass
class Spec:
    case_id: str
    project_id: str
    kind: str                      # "v3" or "v4"
    target_file: str
    target_line: int
    probe: str
    inputs: List[Dict[str, Any]]
    root: Path | None = None
    source_dir: str = "."
    python: str | None = None
    designed: bool = True
    original_suite: str = "not run in this review"
    notes: str = ""
    watch_names: List[str] = field(default_factory=list)


# ------------------------------------------------------------------ helpers
def _read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def _sha(text: str) -> str:
    return hashlib.sha1(text.encode("utf-8", "replace")).hexdigest()


def _target_expression(node: ast.AST) -> str | None:
    if isinstance(node, ast.Assign):
        if len(node.targets) != 1:
            return None
        target = node.targets[0]
    elif isinstance(node, (ast.AnnAssign, ast.AugAssign)):
        target = node.target
    else:
        return None
    try:
        return ast.unparse(target)
    except Exception:  # noqa: BLE001
        return None


def _assignment_nodes(tree: ast.Module) -> List[ast.AST]:
    return [n for n in ast.walk(tree)
            if isinstance(n, (ast.Assign, ast.AnnAssign, ast.AugAssign))]


def _find_target(tree: ast.Module, line: int) -> ast.AST | None:
    exact = [n for n in _assignment_nodes(tree) if int(n.lineno) == line]
    if len(exact) == 1:
        return exact[0]
    containing = [n for n in _assignment_nodes(tree)
                  if int(n.lineno) <= line <= int(getattr(n, "end_lineno", n.lineno))]
    if len(containing) == 1:
        return containing[0]
    return None


def _span(node: ast.AST) -> Tuple[int, int]:
    first = int(node.lineno)
    last = int(getattr(node, "end_lineno", first) or first)
    return first, last


def collect_candidates(source_path: Path, target_file: str,
                       target_line: int) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    """Collect assignments sharing A's exact state key, with node identity."""
    source = _read(source_path)
    try:
        tree = ast.parse(source)
    except SyntaxError as exc:
        return [], {"status": "UNKNOWN", "reason": f"SyntaxError: {exc}"}
    target = _find_target(tree, target_line)
    if target is None:
        return [], {"status": "UNSUPPORTED",
                    "reason": "target line is not a single assignment"}
    key = _target_expression(target)
    if key is None:
        return [], {"status": "UNSUPPORTED",
                    "reason": "target has multiple or unsupported assignment targets"}
    t_first, t_last = _span(target)
    seen = set()
    out: List[Dict[str, Any]] = []
    for node in _assignment_nodes(tree):
        if _target_expression(node) != key:
            continue
        first, last = _span(node)
        if not (last < t_first or first > t_last):
            continue
        ident = (first, last, int(getattr(node, "col_offset", -1)),
                 int(getattr(node, "end_col_offset", -1) or -1))
        if ident in seen:
            continue
        seen.add(ident)
        segment = ast.get_source_segment(source, node) or ""
        out.append({
            "file": target_file,
            "line": first,
            "end_line": last,
            "col": ident[2],
            "end_col": ident[3],
            "key": key,
            "node_sha1": _sha(segment),
            "source": segment[:240],
        })
    out.sort(key=lambda item: (item["line"], item["end_line"]))
    audit = audit_candidates(tree, source, target, key, out)
    return out, audit


def audit_candidates(tree: ast.Module, source: str, target: ast.AST,
                     key: str, candidates: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """Static audit of exact-node identity and file-level deletion collateral."""
    all_same = [n for n in _assignment_nodes(tree) if _target_expression(n) == key]
    rows = []
    for cand in candidates:
        first, last = cand["line"], cand["end_line"]
        covering = []
        for node in _assignment_nodes(tree):
            if node is target:
                continue
            a, b = _span(node)
            if a <= first <= b or a <= last <= b:
                covering.append({"line": a, "end_line": b,
                                 "sha1": _sha(ast.get_source_segment(source, node) or "")})
        rows.append({
            "candidate": {"line": first, "end_line": last,
                          "node_sha1": cand["node_sha1"]},
            "same_key_nodes_in_file": len(all_same),
            "covering_assignments": covering,
            "collateral_risk": bool(len(covering) > 0 or len(all_same) > 1),
        })
    return {
        "status": "OK",
        "state_key": key,
        "target_span": list(_span(target)),
        "same_key_nodes_in_file": len(all_same),
        "candidates": rows,
    }


def classify_run(run: Dict[str, Any]) -> str:
    """RETURN / LEGAL_RAISE / PROBE_CRASH / NONZERO / TIMEOUT."""
    if run.get("timeout"):
        return "TIMEOUT"
    if run.get("returncode") != 0:
        return "NONZERO"
    obs = run.get("observation")
    if not isinstance(obs, dict):
        return "PROBE_CRASH"
    if obs.get("probe_crash"):
        return "PROBE_CRASH"
    if obs.get("outcome") == "return":
        return "RETURN"
    if obs.get("outcome") == "raise":
        return "LEGAL_RAISE"
    return "BAD_OBSERVATION"


def executable(run: Dict[str, Any]) -> bool:
    return classify_run(run) in {"RETURN", "LEGAL_RAISE"}


def masked_strict(plus: Dict[str, Any], minus: Dict[str, Any]) -> bool:
    return bool(executable(plus) and executable(minus)
                and classify_run(plus) == "RETURN"
                and plus.get("observation") == minus.get("observation"))


def exposed_strict(plus: Dict[str, Any], minus: Dict[str, Any]) -> bool:
    return bool(executable(plus) and executable(minus)
                and plus.get("observation") != minus.get("observation"))


# ------------------------------------------------------------------ runner
class Runner:
    def __init__(self, spec: Spec):
        self.spec = spec
        self.builds = 0
        self.executions = 0
        self._variants: Dict[Tuple[str, Tuple[Tuple[int, int], ...]], Path] = {}
        self._runs: Dict[Tuple[str, str], Dict[str, Any]] = {}
        if spec.kind == "v3":
            self.root = None
            self.python = V3_PROJECTS[spec.project_id]["python"]
            self.source_dir = V3_PROJECTS[spec.project_id]["source_dir"]
            self.source_path = PUBLIC / "tasks" / spec.case_id / "source" / spec.target_file
            self.probe_path = KIT / "benchmark_real_v3" / "probes" / spec.probe
            PUBLIC_FILE_CACHE[spec.case_id] = spec.target_file
        else:
            assert spec.root is not None
            self.root = spec.root
            self.python = spec.python or V4_PYTHON
            self.source_dir = spec.source_dir
            self.source_path = self.root / spec.target_file
            self.probe_path = Path(spec.probe)

    # -- building ---------------------------------------------------------
    def _delete(self, root: Path, ops: Iterable[Dict[str, Any]]) -> None:
        by_file: Dict[str, List[Tuple[int, int]]] = {}
        for op in ops:
            by_file.setdefault(op["file"], []).append(
                (int(op["line"]), int(op["end_line"])))
        for rel, spans in by_file.items():
            path = root / rel
            lines = path.read_text(encoding="utf-8").splitlines(keepends=True)
            for first, last in sorted(spans, reverse=True):
                for idx in range(first - 1, min(last, len(lines))):
                    original = lines[idx]
                    indent = original[:len(original) - len(original.lstrip())]
                    newline = "\n" if original.endswith("\n") else ""
                    lines[idx] = f"{indent}pass  # reliable_ast_v1 intervention{newline}"
            path.write_text("".join(lines), encoding="utf-8")

    def variant(self, deleted: Sequence[Dict[str, Any]], side: str) -> Path:
        spans = tuple(sorted({(int(op["line"]), int(op["end_line"]))
                              for op in deleted}))
        key = (side, spans)
        if key in self._variants:
            return self._variants[key]
        tag = "_".join(f"{a}-{b}" for a, b in spans) or "EMPTY"
        if self.spec.kind == "v3":
            statements, blocks = [], []
            for first, last in spans:
                if first == last:
                    statements.append((self.spec.target_file, first))
                else:
                    blocks.append((self.spec.target_file, first, last))
            if side == "minus":
                statements.append((self.spec.target_file, self.spec.target_line))
            built = v3_build_variant(
                self.spec.project_id,
                f"relv1_{self.spec.case_id}_{side}_{tag}",
                statement_deletions=statements, block_deletions=blocks)
            root = Path(built["root"])
        else:
            root = VARIANT_ROOT / self.spec.case_id / f"{side}_{tag}"
            if root.exists():
                shutil.rmtree(root)
            root.parent.mkdir(parents=True, exist_ok=True)
            shutil.copytree(
                self.root, root,
                ignore=shutil.ignore_patterns(
                    "__pycache__", "*.pyc", ".pytest_cache", ".git"))
            ops = list(deleted)
            if side == "minus":
                ops.append({"file": self.spec.target_file,
                            "line": self.spec.target_line,
                            "end_line": self.spec.target_line})
            self._delete(root, ops)
        self.builds += 1
        self._variants[key] = root
        return root

    def run(self, deleted: Sequence[Dict[str, Any]], side: str,
            payload: Dict[str, Any]) -> Dict[str, Any]:
        key = (side + "|" + json.dumps(sorted(
            {(op["line"], op["end_line"]) for op in deleted}), sort_keys=True),
               json.dumps(payload, sort_keys=True))
        if key in self._runs:
            return self._runs[key]
        root = self.variant(deleted, side)
        self.executions += 1
        if self.spec.kind == "v3":
            result = v3_run_probe(self.spec.project_id, root,
                                  self.spec.probe, payload)
            run = {"returncode": result.get("returncode"),
                   "observation": result.get("observation"),
                   "stderr": ""}
        else:
            env = os.environ.copy()
            env["PYTHONPATH"] = str((root / self.source_dir).resolve())
            env["PYTHONDONTWRITEBYTECODE"] = "1"
            env["PYTHONHASHSEED"] = "0"
            env["PYTHONIOENCODING"] = "utf-8"
            try:
                completed = subprocess.run(
                    [self.python, str(self.spec.probe)],
                    input=json.dumps(payload), cwd=str(root), env=env,
                    capture_output=True, text=True, encoding="utf-8",
                    errors="replace", timeout=30)
                observation = None
                try:
                    lines = completed.stdout.strip().splitlines()
                    observation = json.loads(lines[-1]) if lines else None
                except Exception:  # noqa: BLE001
                    observation = None
                run = {"returncode": completed.returncode,
                       "observation": observation,
                       "stderr": completed.stderr[-300:]}
            except subprocess.TimeoutExpired:
                run = {"returncode": None, "observation": None,
                       "stderr": "TIMEOUT", "timeout": True}
        run["classification"] = classify_run(run)
        self._runs[key] = run
        return run

    def pair(self, deleted: Sequence[Dict[str, Any]],
             payload: Dict[str, Any]) -> Dict[str, Any]:
        plus = self.run(deleted, "plus", payload)
        minus = self.run(deleted, "minus", payload)
        kind = "MASKED" if masked_strict(plus, minus) else (
            "EXPOSED" if exposed_strict(plus, minus) else "NOT_RELATION")
        return {"plus": plus, "minus": minus, "kind": kind}

    # -- tracing ----------------------------------------------------------
    def trace(self, side: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        root = self.variant([], side)
        out = Path(tempfile.mkstemp(prefix="relv1_trace_", suffix=".json")[1])
        request = {
            "probe": str(self.probe_path),
            "target_file": str((root / self.spec.target_file).resolve()),
            "payload": payload,
            "out": str(out),
            "watch_names": self.spec.watch_names,
            "max_events": MAX_EVENTS,
        }
        req = out.with_suffix(".req.json")
        req.write_text(json.dumps(request), encoding="utf-8")
        env = os.environ.copy()
        env["PYTHONPATH"] = str((root / self.source_dir).resolve())
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONHASHSEED"] = "0"
        env["PYTHONIOENCODING"] = "utf-8"
        try:
            completed = subprocess.run(
                [self.python, str(TRACER), str(req)],
                cwd=str(root), env=env, capture_output=True, text=True,
                encoding="utf-8", errors="replace", timeout=180)
            if completed.returncode != 0 or not out.exists():
                return {"events": [], "errors": [
                    {"type": "TRACE_FAILED",
                     "message": completed.stderr[-400:]}]}
            return json.loads(out.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            return {"events": [], "errors": [{"type": "TRACE_EXCEPTION",
                                               "message": repr(exc)}]}
        finally:
            for path in (out, req):
                try:
                    path.unlink()
                except OSError:
                    pass


# ------------------------------------------------------------------ analysis
def _events(data: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [e for e in data.get("events", []) if e.get("event") == "line"]


def _first(events: Sequence[Dict[str, Any]], line: int) -> Dict[str, Any] | None:
    for event in events:
        if int(event["line"]) == line:
            return event
    return None


def _eligibility(candidate: Dict[str, Any], target_line: int,
                 plus_events: Sequence[Dict[str, Any]],
                 minus_events: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    line = int(candidate["line"])
    a_events = [e for e in plus_events if int(e["line"]) == target_line]
    a_plus = a_events[0] if a_events else None
    c_events = [e for e in plus_events if int(e["line"]) == line]
    minus_events_at_line = [e for e in minus_events if int(e["line"]) == line]
    plus_seqs = [int(e["seq"]) for e in c_events]
    minus_seqs = [int(e["seq"]) for e in minus_events_at_line]
    in_plus, in_minus = bool(plus_seqs), bool(minus_seqs)
    a_first_seq = int(a_events[0]["seq"]) if a_events else None
    # Cross-function candidates execute in a different call frame, so the
    # comparison is by global event sequence, not by call_id.  A candidate
    # that only executes before A in the trace is not downstream.
    after_events = [e for e in c_events
                    if a_first_seq is not None and int(e["seq"]) > a_first_seq]
    after_a_plus = bool(after_events)
    first_after = min((int(e["seq"]) for e in after_events), default=None)
    a_func = a_plus["func"] if a_plus is not None else None
    # In P- there is no A event to compare against, so source-line order must
    # not be used as a proxy.  A candidate that only executes once A is gone
    # is dynamically enabled by the deletion and is a legal fallback candidate.
    after_a_minus = bool(in_minus and not in_plus)
    return {
        "line": line, "in_plus": in_plus, "in_minus": in_minus,
        "plus_seq_first": plus_seqs[0] if plus_seqs else None,
        "plus_seq_last": plus_seqs[-1] if plus_seqs else None,
        "plus_seq_after_a": first_after,
        "plus_occurrences": len(plus_seqs),
        "minus_occurrences": len(minus_seqs),
        "minus_seq_first": minus_seqs[0] if minus_seqs else None,
        "a_plus_seq": int(a_plus["seq"]) if a_plus is not None else None,
        "a_func": a_func,
        "after_a_plus": after_a_plus, "after_a_minus": after_a_minus,
        "dynamic_downstream": bool(after_a_plus or after_a_minus),
    }


def _subsets(universe: Sequence[Dict[str, Any]], max_size: int,
             limit: int) -> List[Tuple[Dict[str, Any], ...]]:
    subsets = []
    for size in range(1, min(max_size, len(universe)) + 1):
        for combo in itertools.combinations(universe, size):
            subsets.append(combo)
            if len(subsets) >= limit:
                return subsets
    return subsets


def _op_ref(op: Dict[str, Any]) -> Dict[str, Any]:
    return {"file": op["file"], "line": int(op["line"])}


def _status_for_pair(pair: Dict[str, Any]) -> str:
    if pair["kind"] == "MASKED":
        return "MASKED"
    if pair["kind"] == "EXPOSED":
        return "EXPOSED"
    cp = classify_run(pair["plus"])
    cm = classify_run(pair["minus"])
    if cp in {"NONZERO", "PROBE_CRASH", "TIMEOUT"} or cm in {
            "NONZERO", "PROBE_CRASH", "TIMEOUT"}:
        return "BROKEN_INTERVENTION"
    if cp == "LEGAL_RAISE" or cm == "LEGAL_RAISE":
        return "LEGAL_EXCEPTION_SEMANTICS"
    return "FALSE"


def analyze_row(runner: Runner, spec: Spec, universe: Sequence[Dict[str, Any]],
                payload: Dict[str, Any], budget: Dict[str, int]) -> Dict[str, Any]:
    cache: Dict[Tuple[int, ...], Dict[str, Any]] = {}

    def evaluate(op_set: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
        key = tuple(sorted(int(op["line"]) for op in op_set))
        if key not in cache:
            pair = runner.pair(op_set, payload)
            cache[key] = {
                "deleted": [_op_ref(op) for op in op_set],
                "kind": pair["kind"],
                "status": _status_for_pair(pair),
                "plus_class": classify_run(pair["plus"]),
                "minus_class": classify_run(pair["minus"]),
                "plus_observation": pair["plus"].get("observation"),
                "minus_observation": pair["minus"].get("observation"),
            }
        return cache[key]

    # MSMS: Only(S) = delete U \ S.  MMBS: Break(S) = delete S.
    msms, mmbs = [], []
    singleton_msms, singleton_mmbs = [], []
    for op in universe:
        others = [x for x in universe if x is not op]
        keep = evaluate(others)
        delete = evaluate([op])
        # A relation whose own deletion crashes/hangs the probe is an
        # intervention artifact, not a masking operation.
        if keep["kind"] == "MASKED" and delete["status"] != "BROKEN_INTERVENTION":
            singleton_msms.append([op])
        if delete["kind"] == "EXPOSED":
            singleton_mmbs.append([op])
    msms.extend(singleton_msms)
    mmbs.extend(singleton_mmbs)
    unsafe = {int(op["line"]) for op in universe
              if evaluate([op])["status"] == "BROKEN_INTERVENTION"}

    # Bounded combination search only when a singleton did not already explain
    # the relation.  This retains cooperative / multiple-fallback coverage.
    need_msms = not singleton_msms and len(universe) >= 2
    need_mmbs = not singleton_mmbs and len(universe) >= 2
    if need_msms or need_mmbs:
        for combo in _subsets(universe, MAX_COMBO_SIZE, MAX_SUBSETS_PER_ROW):
            if budget["used"] >= budget["limit"]:
                break
            if len(combo) < 2:
                continue
            if any(int(op["line"]) in unsafe for op in combo):
                continue
            if need_msms and not msms:
                others = [x for x in universe if x not in combo]
                budget["used"] += 1
                keep = evaluate(others)
                if keep["kind"] == "MASKED":
                    proper = list(itertools.chain.from_iterable(
                        itertools.combinations(combo, k)
                        for k in range(1, len(combo))))
                    if not any(cache.get(
                            tuple(sorted(int(x["line"]) for x in sub)),
                            {}).get("kind") == "MASKED" for sub in proper):
                        msms.append(list(combo))
            if need_mmbs and not mmbs:
                budget["used"] += 1
                delete = evaluate(combo)
                if delete["kind"] == "EXPOSED":
                    proper = list(itertools.chain.from_iterable(
                        itertools.combinations(combo, k)
                        for k in range(1, len(combo))))
                    if not any(cache.get(
                            tuple(sorted(int(x["line"]) for x in sub)),
                            {}).get("kind") == "EXPOSED" for sub in proper):
                        mmbs.append(list(combo))
            if (not need_msms or msms) and (not need_mmbs or mmbs):
                break

    # A sufficient set is only meaningful if some candidate deletion actually
    # makes A's absence observable.  Without an exposing evaluation the base
    # pair is already masked and every retained subset would satisfy
    # Masked_strict vacuously; the scorer rejects such claims
    # ("no observable local effect to mask").
    exposed_any = any(item["kind"] == "EXPOSED" for item in cache.values())
    if msms and not exposed_any:
        msms = []
    if msms or mmbs:
        row_status = "VALIDATED"
    elif budget["used"] >= budget["limit"]:
        row_status = "OUT_OF_BUDGET"
    elif any(item["status"] == "BROKEN_INTERVENTION"
             for item in cache.values()):
        # The intervention itself hangs or crashes.  That is not a refutation
        # of the relation, so it must stay UNVERIFIED rather than FALSE.
        row_status = "UNVERIFIED"
    else:
        row_status = "FALSE"
    return {
        "input": payload,
        "status": row_status,
        "msms": [[_op_ref(op) for op in combo] for combo in msms],
        "mmbs": [[_op_ref(op) for op in combo] for combo in mmbs],
        "evaluations": list(cache.values()),
    }


def analyze_spec(spec: Spec, max_rows: int = 3) -> Dict[str, Any]:
    start = time.time()
    runner = Runner(spec)
    candidates, audit = collect_candidates(
        runner.source_path, spec.target_file, spec.target_line)
    key = spec.watch_names[0] if spec.watch_names else audit.get("state_key", "")
    spec.watch_names = [key]
    runner.variant([], "plus")
    runner.variant([], "minus")
    rows, claims, masked_rows = [], [], 0
    seen_claims = set()
    for payload in spec.inputs:
        plus = runner.run([], "plus", payload)
        minus = runner.run([], "minus", payload)
        kind = "MASKED" if masked_strict(plus, minus) else (
            "EXPOSED" if exposed_strict(plus, minus) else "NOT_RELATION")
        plus_events_data = runner.trace("plus", payload)
        minus_events_data = runner.trace("minus", payload)
        plus_events = _events(plus_events_data)
        minus_events = _events(minus_events_data)
        a_plus = _first(plus_events, spec.target_line)
        a_executes = a_plus is not None
        a_event_count = sum(1 for e in plus_events
                            if int(e["line"]) == spec.target_line)
        eligibility = {int(op["line"]): _eligibility(
            op, spec.target_line, plus_events, minus_events)
            for op in candidates}
        universe = [op for op in candidates
                    if eligibility[int(op["line"])]["dynamic_downstream"]]
        row = {
            "input": payload,
            "base_kind": kind,
            "a_executes": a_executes,
            "a_event_count": a_event_count,
            "plus_class": classify_run(plus),
            "minus_class": classify_run(minus),
            "plus_observation": plus.get("observation"),
            "minus_observation": minus.get("observation"),
            "trace_errors": (plus_events_data.get("errors", [])
                             + minus_events_data.get("errors", [])),
            "eligibility": eligibility,
            "universe": [_op_ref(op) for op in universe],
            "analysis": None,
        }
        if (kind == "EXPOSED" and a_executes and len(claims) < MAX_CLAIMS):
            claims.append({"type": "EXPOSING_COUNTEREXAMPLE", "input": payload})
        if kind == "MASKED" and a_executes and masked_rows < max_rows:
            masked_rows += 1
            row["analysis"] = analyze_row(
                runner, spec, universe, payload,
                {"used": 0, "limit": MAX_SUBSETS_PER_ROW})
            for kind_name, groups in (("MSMS", row["analysis"]["msms"]),
                                      ("MMBS", row["analysis"]["mmbs"])):
                for group in groups:
                    signature = (kind_name,
                                 json.dumps(payload, sort_keys=True),
                                 tuple(sorted(op["line"] for op in group)))
                    if signature in seen_claims or len(claims) >= MAX_CLAIMS:
                        continue
                    seen_claims.add(signature)
                    claims.append({"type": kind_name, "input": payload,
                                   "operations": group})
        rows.append(row)
    return {
        "case_id": spec.case_id,
        "project_id": spec.project_id,
        "kind": spec.kind,
        "target": {"file": spec.target_file, "line": spec.target_line,
                   "state_key": key},
        "designed": spec.designed,
        "original_suite": spec.original_suite,
        "notes": spec.notes,
        "candidates": candidates,
        "candidate_audit": audit,
        "inputs_evaluated": rows,
        "claims": claims,
        "variant_builds": runner.builds,
        "executions": runner.executions,
        "wall_seconds": round(time.time() - start, 3),
        "status": ("WITNESS_VERIFIED_LOCAL" if claims else "UNVERIFIED"),
    }
