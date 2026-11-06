"""Algorithm pilot over the source-derived (SD) tasks.

This is an *adapter*, not an algorithm change.  It reuses the frozen v3
baseline components unchanged:

* ``benchmark_v3_baselines.ast_discovery`` + ``rank_and_prune``  (C)
* ``benchmark_v3_baselines.subgraph`` + ``candidate_selection``  (Graph)
* ``benchmark_v3_baselines.graph_search.search_relations``       (C / Graph)
* ``benchmark_v3_baselines.graph_search.search_relations_role_separated`` (C0)

The algorithm sees only a public view built here: the frozen P+ source, the
public target operation A, and an opaque input grid (``in1..inN``).  It never
reads ``reference.json``, MSMS/MMBS, input roles, or the block boundaries;
those are read only by the scorer after every method has finished.

Usage::

    python -I benchmark_v4_dataset/tools/sd_algorithm_pilot.py \
        --methods c_fixed graph c0 [--case ID ...]
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

_MARKER = re.compile(r"^\s*#\s*SD:U:[A-Za-z0-9_]+:(?:begin|end)\s*$")

KIT = Path(__file__).resolve().parents[2]
DS = KIT / "benchmark_v4_dataset"
DISC = DS / "discovery"
SD = DS / "source_derived"
OUT = KIT / "runs" / "sd_v1_algorithm_pilot"

MAX_OPS = 6                 # BUDGET["max_candidate_ops"]
BUDGET_PER_INPUT = 16       # C0 budget, same as run_role_separated_offline
WORKERS = 12

import sys
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from mace.paths import venv_python, venvs_root, work_root  # noqa: E402

WORK = work_root("sd_pilot")
VENVS = venvs_root()

from benchmark_v3_baselines.ast_discovery import discover, rank_and_prune  # noqa: E402
from benchmark_v3_baselines import subgraph  # noqa: E402
from benchmark_v3_baselines.graph_search import (  # noqa: E402
    payload_key, search_relations, search_relations_role_separated,
    subset_key)


def load(path: Path):
    return json.loads(path.read_text("utf-8"))


def stage0_row(slug: str) -> dict:
    for row in load(DISC / "stage0" / "projects.json")["projects"]:
        if row["slug"] == slug:
            return row
    raise SystemExit(f"unknown slug {slug}")


def _normalise(value) -> dict:
    if isinstance(value, dict) and set(value) == {"error"}:
        text = str(value["error"])
        kind, _, message = text.partition(": ")
        return {"outcome": "raise", "type": kind, "message": message}
    return {"outcome": "return", "value": value}


def _delete_span(lines: list[str], first: int, last: int) -> list[str]:
    out = list(lines)
    indent = out[first - 1][: len(out[first - 1]) - len(out[first - 1].lstrip())]
    for i in range(first - 1, last):
        out[i] = "\n"
    out[first - 1] = indent + "pass  # disabled by the pilot\n"
    return out


def _hardlink_tree(src: Path, dest: Path) -> None:
    dest.mkdir(parents=True, exist_ok=True)
    for entry in src.iterdir():
        if entry.name == "__pycache__":
            continue
        target = dest / entry.name
        if entry.is_dir():
            _hardlink_tree(entry, target)
        else:
            try:
                os.link(entry, target)
            except OSError:
                shutil.copy2(entry, target)


class SDExecutor:
    """Same surface as ``benchmark_v3_baselines.execution.Executor``."""

    def __init__(self, slug: str, root: Path, rel: str, patched: list[str],
                 a_line: int, probe: Path, key_map: dict[str, str],
                 work: Path):
        self.slug = slug
        self.root = root
        self.rel = rel
        self.patched = patched
        self.a_line = a_line
        self.probe = probe
        self.top = rel.split("/")[0]
        self.key_map = key_map
        self.work = work
        self.universe: dict[str, dict] = {}
        self._dirs: dict = {}
        self._texts: dict = {}
        self._runs: dict = {}
        self._observed_all: dict = {}
        self._trace: dict = {}
        self.probe_executions = 0
        self.variant_builds = 0

    def set_universe(self, ops) -> None:
        self.universe = {op["id"]: op for op in ops}

    # -- variants ---------------------------------------------------------
    def _text(self, disabled, side: str) -> list[str]:
        key = (tuple(sorted(disabled)), side)
        if key in self._texts:
            return self._texts[key]
        lines = list(self.patched)
        if side == "minus":
            lines = _delete_span(lines, self.a_line, self.a_line)
        for op_id in sorted(disabled):
            op = self.universe.get(op_id)
            if op is None:
                raise KeyError(op_id)
            lines = _delete_span(lines, int(op["first_line"]),
                                 int(op.get("last_line", op["first_line"])))
        self._texts[key] = lines
        return lines

    def variant_dir(self, disabled, side: str) -> Path:
        key = (tuple(sorted(disabled)), side)
        if key in self._dirs:
            return self._dirs[key]
        digest = hashlib.sha1(
            (subset_key(disabled) + "|" + side).encode("utf-8")).hexdigest()[:16]
        dest = self.work / "var" / digest
        if not dest.exists():
            _hardlink_tree(self.root / self.top, dest / self.top)
        target = dest / self.rel
        if target.exists() or target.is_symlink():
            target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("".join(self._text(disabled, side)), encoding="utf-8")
        self.variant_builds += 1
        self._dirs[key] = dest
        return dest

    # -- probes -----------------------------------------------------------
    def _run_probe(self, disabled, side: str) -> dict:
        key = (tuple(sorted(disabled)), side)
        cached = self._observed_all.get(key)
        if cached is not None:
            return cached
        vdir = self.variant_dir(disabled, side)
        boot = (
            "import sys, runpy\n"
            f"sys.path.insert(0, {str(vdir)!r})\n"
            f"sys.path.insert(0, {str(vdir / self.top)!r})\n"
            f"runpy.run_path({str(self.probe)!r}, run_name='__main__')\n")
        env = {k: v for k, v in os.environ.items()
               if k in ("PATH", "SystemRoot", "TEMP", "TMP", "HOME",
                        "USERPROFILE", "LOCALAPPDATA", "APPDATA")}
        env.update({"PYTHONIOENCODING": "utf-8",
                    "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"})
        scratch = Path(tempfile.mkdtemp(prefix="sd_pilot_"))
        try:
            proc = subprocess.run(
                [str(venv_python(self.slug)),
                 "-I", "-c", boot], cwd=str(scratch), env=env,
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=300)
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        self.probe_executions += 1
        if proc.returncode != 0:
            data = {"__probe_error__": True, "stderr": proc.stderr[-500:]}
        else:
            try:
                data = json.loads(proc.stdout.strip().splitlines()[-1])
            except Exception:  # noqa: BLE001
                data = {"__probe_error__": True, "stdout": proc.stdout[-500:]}
        self._observed_all[key] = data
        return data

    def prefetch(self, subsets, workers: int = WORKERS) -> None:
        jobs = [(tuple(d), side) for d in subsets for side in ("plus", "minus")]
        with ThreadPoolExecutor(max_workers=workers) as pool:
            list(pool.map(lambda job: self._run_probe(*job), jobs))

    def observation(self, disabled, side: str, payload: dict):
        key = (subset_key(disabled), side, payload_key(payload))
        if key in self._runs:
            return self._runs[key]
        data = self._run_probe(disabled, side)
        if data.get("__probe_error__"):
            value = {"__probe_error__": True}
        else:
            value = _normalise(data.get(self.key_map[payload["id"]]))
        self._runs[key] = value
        return value

    # -- trace ------------------------------------------------------------
    def a_executes(self, payload: dict) -> bool:
        key = payload_key(payload)
        if key in self._trace:
            return self._trace[key]
        vdir = self.variant_dir([], "plus")
        target = str((vdir / self.rel).resolve())
        boot = (
            "import json, runpy, sys\n"
            f"target = {target!r}\n"
            f"line = {self.a_line}\n"
            "hit = []\n"
            "def tr(frame, event, arg):\n"
            "    if event == 'line' and frame.f_lineno == line and "
            "frame.f_code.co_filename == target:\n"
            "        hit.append(1)\n"
            "    return tr\n"
            f"sys.path.insert(0, {str(vdir)!r})\n"
            f"sys.path.insert(0, {str(vdir / self.top)!r})\n"
            "sys.settrace(tr)\n"
            "try:\n"
            f"    runpy.run_path({str(self.probe)!r}, run_name='__main__')\n"
            "finally:\n"
            "    sys.settrace(None)\n"
            "print(json.dumps({'executed': bool(hit)}))\n")
        env = {k: v for k, v in os.environ.items()
               if k in ("PATH", "SystemRoot", "TEMP", "TMP", "HOME",
                        "USERPROFILE", "LOCALAPPDATA", "APPDATA")}
        env.update({"PYTHONIOENCODING": "utf-8",
                    "PYTHONDONTWRITEBYTECODE": "1", "PYTHONHASHSEED": "0"})
        scratch = Path(tempfile.mkdtemp(prefix="sd_trace_"))
        try:
            proc = subprocess.run(
                [str(venv_python(self.slug)),
                 "-I", "-c", boot], cwd=str(scratch), env=env,
                capture_output=True, text=True, encoding="utf-8",
                errors="replace", timeout=300)
            executed = False
            for line in reversed(proc.stdout.strip().splitlines()):
                try:
                    executed = json.loads(line).get("executed") is True
                    break
                except Exception:  # noqa: BLE001
                    continue
        finally:
            shutil.rmtree(scratch, ignore_errors=True)
        self._trace[key] = executed
        return executed


def _active_ops(executor: SDExecutor, payload: dict) -> list[str]:
    """Frozen C isolation step (baseline_c._active_ops)."""
    base_plus = executor.observation([], "plus", payload)
    base_minus = executor.observation([], "minus", payload)
    active = []
    for op_id in executor.universe:
        if (executor.observation([op_id], "plus", payload) != base_plus
                or executor.observation([op_id], "minus", payload) != base_minus):
            active.append(op_id)
    return active


def block_spans(enumeration: dict) -> dict[str, tuple[int, int]]:
    """1-based code-line span of every U block in the patched file."""
    return {bid: (rng["begin"] + 2, rng["end"])
            for bid, rng in enumeration["line_map"].items()}


def _block_vectors(enumeration: dict, input_keys: list[str]) -> dict:
    """Observation vector of every hidden block subset, over all inputs."""
    labels = list(enumeration["per_input"][input_keys[0]]["by_variant"])
    out = {}
    for label in labels:
        kept = (() if label == "KEEP_EMPTY"
                else tuple(label[len("KEEP_"):].split("_")))
        vec = []
        for key in input_keys:
            raw = enumeration["per_input"][key]["by_variant"].get(label)
            vec.append(json.dumps(_normalise(raw), sort_keys=True,
                                  ensure_ascii=False))
        out[frozenset(kept)] = tuple(vec)
    return out


def project_containment(ids, universe: dict, spans: dict):
    """Map operation ids onto hidden block ids by span containment.

    Returns (blocks, stray_op_ids).  An operation stands for a hidden block
    when its whole span lies inside exactly one block; a statement *inside*
    a block therefore counts as that block's operative part, while an
    operation outside every block is stray.  The stricter span-identity
    mapping is recorded separately as a diagnostic.
    """
    blocks, stray = set(), []
    for op_id in sorted(set(ids)):
        op = universe.get(op_id)
        if op is None:
            stray.append(op_id)
            continue
        first = int(op["first_line"])
        last = int(op.get("last_line", first))
        hit = [bid for bid, (b, e) in spans.items() if b <= first and last <= e]
        if len(hit) == 1:
            blocks.add(hit[0])
        else:
            stray.append(op_id)
    return blocks, stray


def project_identity(ids, universe: dict, spans: dict):
    """As above, but only an exact block-span match counts."""
    blocks, stray = set(), []
    for op_id in sorted(set(ids)):
        op = universe.get(op_id)
        if op is None:
            stray.append(op_id)
            continue
        first = int(op["first_line"])
        last = int(op.get("last_line", first))
        hit = [bid for bid, span in spans.items() if span == (first, last)]
        if hit:
            blocks.add(hit[0])
        else:
            stray.append(op_id)
    return blocks, stray


def family(sets) -> set:
    return {frozenset(s) for s in sets}


def _combinations(items, size):
    if size == 0:
        yield ()
        return
    for index in range(len(items) - size + 1):
        head = items[index]
        for tail in _combinations(items[index + 1:], size - 1):
            yield (head,) + tail


def run_method(method: str, case_path: Path) -> dict:
    spec = load(case_path)
    cid = spec["case_id"]
    slug = spec["base"]["slug"]
    rel = spec["base"]["file"]
    meta = stage0_row(slug)
    root = (DISC / meta["root"]).resolve()
    enumeration = load(SD / "evidence" / cid / "enumeration.json")
    reference = load(SD / "tasks" / cid / "reference.json")

    patched = (SD / "evidence" / cid / "patched" / Path(rel).name) \
        .read_text("utf-8").splitlines(keepends=True)
    # The public view must not reveal block boundaries: the researcher's
    # "# SD:U:<id>:begin/end" markers are blanked (same line count, so every
    # line number still matches the executed file).  The variants executed
    # by the probe keep the real text.
    public_text = "".join(
        line if not _MARKER.match(line) else "\n" for line in patched)
    a_line = int(spec["base"]["A_line"])
    probe = (KIT / spec["probe"]).resolve()
    spans = block_spans(enumeration)

    input_keys = list(spec["inputs"])                  # declaration order
    public_payloads = [{"id": f"in{i + 1}"} for i in range(len(input_keys))]
    key_map = {f"in{i + 1}": key for i, key in enumerate(input_keys)}

    work = WORK / cid / method
    work.mkdir(parents=True, exist_ok=True)

    started = time.perf_counter()
    executor = SDExecutor(slug, root, rel, patched, a_line, probe, key_map, work)
    task = {"file": rel,
            "target_operation": {"file": rel, "line": a_line,
                                 "code": spec["base"]["A_code"]}}
    source_text = public_text

    discovery = {"method": method}
    graph_scores = None
    if method in ("c_fixed", "c0"):
        found = discover(task, source_text)
        executor.set_universe(found["candidate_ops"])
        pruned = rank_and_prune(executor, found, public_payloads, MAX_OPS)
        universe = pruned["universe"]
        discovery.update({
            "rule": found["discovery_rule"],
            "candidate_ops": len(found["candidate_ops"]),
            "kept": len(universe),
            "considered": pruned.get("considered"),
            "dropped_no_effect": pruned.get("dropped_no_effect"),
            "dropped_duplicate_effect": pruned.get("dropped_duplicate_effect"),
            "truncated": pruned.get("truncated"),
        })
    elif method == "graph":
        graph = subgraph.build(task, source_text)
        selection = subgraph.candidate_selection(graph, MAX_OPS)
        universe = selection["ops"]
        graph_scores = {op["id"]: op["graph_score"] for op in universe}
        discovery.update({
            "rule": graph["discovery_rule"],
            "stats": graph.get("stats"),
            "eligible": selection["eligible"],
            "selected": selection["selected"],
            "truncated": selection["truncated"],
        })
    else:
        raise ValueError(method)

    executor.set_universe(universe)
    universe_ids = [op["id"] for op in universe]
    all_subsets = [list(c) for size in range(len(universe_ids) + 1)
                   for c in _combinations(universe_ids, size)]

    per_input = []
    for payload in public_payloads:
        executes = executor.a_executes(payload)
        plus = executor.observation([], "plus", payload)
        minus = executor.observation([], "minus", payload)
        executable = (not plus.get("__probe_error__")
                      and not minus.get("__probe_error__"))
        masked_empty = bool(executable and plus.get("outcome") == "return"
                            and plus == minus)
        exposed_empty = bool(executable and plus != minus)
        msms, mmbs, metrics = [], [], {}
        if executes and masked_empty:
            if method in ("c_fixed", "graph"):
                # exhaustive search: every subset is needed, so run them in
                # parallel and let the frozen search read the run cache.
                executor.prefetch(all_subsets)
                _active_ops(executor, payload)   # frozen C isolation step
            if method == "c_fixed":
                rel_out = search_relations(executor, payload, universe_ids,
                                           mode="exhaustive")
            elif method == "graph":
                rel_out = search_relations(executor, payload, universe_ids,
                                           graph_scores=graph_scores,
                                           mode="graph")
            else:
                rel_out = search_relations_role_separated(
                    executor, payload, universe_ids,
                    budget=BUDGET_PER_INPUT)
            msms = rel_out["msms_ids"]
            mmbs = rel_out["mmbs_ids"]
            metrics = {k: rel_out.get(k) for k in (
                "evaluations", "subsets_total", "complete",
                "evidence_complete", "unknown_subsets", "invalid_subsets",
                "cache_hits", "first_msms", "first_mmbs")}
        per_input.append({
            "public_id": payload["id"],
            "input_key": key_map[payload["id"]],
            "a_executes": executes,
            "masked_empty": masked_empty,
            "exposed_empty": exposed_empty,
            "searched": bool(executes and masked_empty),
            "msms_ids": msms,
            "mmbs_ids": mmbs,
            "metrics": metrics,
        })

    wall = time.perf_counter() - started
    algorithm_probes = executor.probe_executions
    algorithm_seconds = round(wall, 2)

    # ---- scoring: hidden data is read only here -------------------------
    #
    # Primary MSMS metric is the set of hidden blocks reached by the
    # algorithm's kept operations (span containment).  A statement inside a
    # block counts as that block's operative part; an operation outside all
    # blocks is stray and fails the match.  An exact-span variant and an
    # intervention-equivalence class are recorded as diagnostics.
    #
    # A secondary diagnostic maps an emitted kept set S to the hidden block
    # subsets whose *minus-side* observation on every declared input equals
    # the observation of disabling U \ S.  This is the benchmark's own
    # FINITE_DOMAIN_EXACT scope and it can credit a vacuous "keep all"
    # answer, so it is reported but not used as the primary metric.
    hidden_inputs = reference["inputs"]
    covered = {bid for bid, (b, e) in spans.items()
               if any(b <= int(op["first_line"]) and
                      int(op.get("last_line", op["first_line"])) <= e
                      for op in universe)}
    discovery["u_covered"] = sorted(covered)
    discovery["u_total"] = sorted(spans)
    discovery["u_recall"] = (round(len(covered) / len(spans), 3)
                             if spans else 0.0)
    discovery["u_exact"] = sorted(covered) == sorted(spans)

    block_vec = _block_vectors(enumeration, input_keys)   # minus side
    class_of_block = {b: frozenset(k for k, v in block_vec.items() if v == vec)
                      for b, vec in block_vec.items()}

    equiv_cache = {}

    def intervention_class(kept_ids):
        disabled = tuple(op for op in universe_ids if op not in set(kept_ids))
        if disabled in equiv_cache:
            return equiv_cache[disabled]
        obs = [executor.observation(list(disabled), "minus", payload)
               for payload in public_payloads]
        vec = tuple(json.dumps(o, sort_keys=True, ensure_ascii=False)
                    for o in obs)
        cls = frozenset(k for k, v in block_vec.items() if v == vec)
        equiv_cache[disabled] = cls
        return cls

    def cls_json(cls):
        return sorted(sorted(b) for b in cls)

    scores = {"msms_exact": 0, "msms_exact_intervention": 0,
              "mmbs_exact": None,
              "mmbs_status": ("NOT_SEPARABLE: reference mmbs is identical to "
                              "msms on every input of every case"),
              "masking_inputs": 0, "false_relations": 0,
              "unmatched_sets": 0, "mmbs_emitted_sets": 0}
    detail = []
    for row in per_input:
        hidden = hidden_inputs[row["input_key"]]
        if hidden["role"] != "masking":
            continue
        scores["masking_inputs"] += 1
        scores["mmbs_emitted_sets"] += len(row["mmbs_ids"])
        want = family(hidden["msms"])
        hits = [project_containment(s, executor.universe, spans)
                for s in row["msms_ids"]]
        got = family([h[0] for h in hits])
        stray = [o for h in hits for o in h[1]]
        msms_ok = got == want and not stray
        exact_hits = [project_identity(s, executor.universe, spans)
                      for s in row["msms_ids"]]
        classes = [intervention_class(s) for s in row["msms_ids"]]
        want_classes = {class_of_block[frozenset(h)] for h in hidden["msms"]}
        inter_ok = set(classes) == want_classes and all(classes)
        scores["msms_exact"] += int(msms_ok)
        scores["msms_exact_intervention"] += int(inter_ok)
        scores["unmatched_sets"] += sum(1 for h in hits if not h[0])
        scores["false_relations"] += len(got - want) + len(stray)
        detail.append({
            "input": row["input_key"],
            "hidden_msms": sorted(sorted(s) for s in hidden["msms"]),
            "got_msms_ops": [sorted(s) for s in row["msms_ids"]],
            "got_msms_blocks": sorted(sorted(s) for s in got),
            "got_msms_blocks_identity": [
                sorted(h[0]) for h in exact_hits],
            "stray_ops": stray,
            "got_msms_intervention_classes": [cls_json(c) for c in classes],
            "msms_exact": msms_ok, "intervention_equivalent": inter_ok,
            "got_mmbs_disabled_sets": [sorted(s) for s in row["mmbs_ids"]],
        })

    cooperative = spec["mechanism"] in ("M2_TWO_OPERATION_COOPERATIVE",
                                        "M3_THREE_OPERATION_COOPERATIVE")
    if cooperative and scores["masking_inputs"]:
        scores["coop_exact"] = bool(
            scores["msms_exact"] == scores["masking_inputs"])

    return {
        "case_id": cid,
        "method": method,
        "mechanism": spec["mechanism"],
        "project": meta["name"],
        "universe": universe,
        "discovery": discovery,
        "per_input": per_input,
        "scoring": scores,
        "detail": detail,
        "cost": {
            "wall_seconds_algorithm": algorithm_seconds,
            "probe_executions_algorithm": algorithm_probes,
            "probe_executions_scoring": (executor.probe_executions
                                         - algorithm_probes),
            "variant_builds": executor.variant_builds,
            "subsets_evaluated": sum(
                int(r["metrics"].get("evaluations") or 0)
                for r in per_input),
        },
    }


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--methods", nargs="+",
                    default=["c_fixed", "graph", "c0"])
    ap.add_argument("--case", action="append", default=[])
    args = ap.parse_args()

    cases = sorted((SD / "cases").glob("*.json"))
    if args.case:
        cases = [c for c in cases if c.stem in set(args.case)]

    OUT.mkdir(parents=True, exist_ok=True)
    results = []
    for case_path in cases:
        for method in args.methods:
            rec = run_method(method, case_path)
            results.append(rec)
            sc = rec["scoring"]
            print(f"{rec['case_id']:34s} {method:8s} "
                  f"U={rec['discovery'].get('u_recall')} "
                  f"msms={sc['msms_exact']}/{sc['masking_inputs']} "
                  f"inter={sc['msms_exact_intervention']}/"
                  f"{sc['masking_inputs']} "
                  f"false={sc['false_relations']} "
                  f"probes={rec['cost']['probe_executions_algorithm']}"
                  f"+{rec['cost']['probe_executions_scoring']} "
                  f"{rec['cost']['wall_seconds_algorithm']}s", flush=True)
            (OUT / f"{rec['case_id']}__{method}.json").write_text(
                json.dumps(rec, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "raw_results.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
