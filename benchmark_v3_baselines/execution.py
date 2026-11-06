"""Program intervention: build P+/P- variants and observe them.

The mechanics are the same as the benchmark's public execution contract:
a variant is a full copy of the upstream tree with a small set of statements
replaced by ``pass``; the probe is the frozen public probe script.  P+ keeps
the target operation, P- deletes it.

This module never reads the hidden reference and never enumerates the hidden
candidate universe.  The universe it works over is supplied by the caller
(Baseline C's AST discovery or Baseline B's verifier).
"""
from __future__ import annotations

import hashlib
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from benchmark_real_v3.config import PROJECTS
from benchmark_real_v3.variant_lab import build_variant, run_probe

from benchmark_v3_baselines.config import PROBES

TRACE_RUNNER = Path(__file__).resolve().parent / "trace_runner.py"


def _key(ids: Iterable[str]) -> str:
    return "+".join(sorted(ids)) or "EMPTY"


def _variant_name(prefix: str, side: str, disabled: Iterable[str]) -> str:
    """Unique, bounded directory name for one intervention.

    The old scheme used the sanitized subset key and truncated it to 110
    characters.  For more than two operations the truncation made distinct
    subsets share a directory; because variants are cached across payloads,
    a later probe could read a directory last written for another subset.
    A digest of the full key keeps one directory per subset.
    """
    digest = hashlib.sha1(_key(disabled).encode("utf-8")).hexdigest()[:16]
    return f"{prefix}_{side}_{digest}"[:110]


def _json_key(payload: Dict[str, Any]) -> str:
    return json.dumps(payload, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"))


class Executor:
    """Bounded, cached access to P+/P- executions for one task."""

    def __init__(self, task_id: str, project_id: str, probe: str,
                 target: Dict[str, Any], variant_prefix: str):
        self.task_id = task_id
        self.project_id = project_id
        self.probe = probe
        self.target = target
        self.prefix = variant_prefix
        self.universe: Dict[str, Dict[str, Any]] = {}
        self._variants: Dict[Tuple[str, str], Path] = {}
        self._runs: Dict[Tuple[str, str, str], Dict[str, Any]] = {}
        self._trace: Dict[str, bool] = {}
        self.probe_executions = 0

    # -- universe ----------------------------------------------------------
    def set_universe(self, ops: Sequence[Dict[str, Any]]) -> None:
        self.universe = {op["id"]: op for op in ops}

    # -- variants ----------------------------------------------------------
    def _edits(self, disabled: Sequence[str]) -> Tuple[List[Tuple[str, int]],
                                                      List[Tuple[str, int, int]]]:
        statements: List[Tuple[str, int]] = []
        blocks: List[Tuple[str, int, int]] = []
        for op_id in disabled:
            op = self.universe.get(op_id)
            if op is None:
                raise KeyError(f"unknown operation {op_id!r}")
            first = int(op.get("first_line", op.get("line")))
            last = int(op.get("last_line", first))
            if last > first or op.get("kind") == "block":
                # A multi-line statement is replaced as one block; deleting
                # only its first physical line would leave a syntax error.
                blocks.append((op["file"], first, last))
            else:
                statements.append((op["file"], first))
        return statements, blocks

    def variant(self, disabled: Sequence[str], side: str) -> Path:
        key = (_key(disabled), side)
        if key in self._variants:
            return self._variants[key]
        statements, blocks = self._edits(sorted(disabled))
        if side == "minus":
            statements.append((self.target["file"], int(self.target["line"])))
        name = _variant_name(self.prefix, side, disabled)
        built = build_variant(
            self.project_id, name,
            statement_deletions=statements, block_deletions=blocks)
        path = Path(built["root"])
        self._variants[key] = path
        return path

    # -- probes ------------------------------------------------------------
    def run(self, disabled: Sequence[str], side: str,
            payload: Dict[str, Any]) -> Dict[str, Any]:
        key = (_key(disabled), side, _json_key(payload))
        if key in self._runs:
            return self._runs[key]
        path = self.variant(disabled, side)
        result = run_probe(self.project_id, path, self.probe, payload,
                           timeout=180)
        self.probe_executions += 1
        self._runs[key] = result
        return result

    @staticmethod
    def executable(run: Dict[str, Any]) -> bool:
        observation = run.get("observation")
        return (
            run.get("returncode") == 0
            and isinstance(observation, dict)
            and "outcome" in observation
            and not observation.get("probe_crash")
        )

    def observation(self, disabled: Sequence[str], side: str,
                    payload: Dict[str, Any]) -> Any:
        run = self.run(disabled, side, payload)
        if not self.executable(run):
            return {"__probe_error__": True,
                    "returncode": run.get("returncode"),
                    "stderr_tail": (run.get("stderr_tail") or "")[-400:]}
        return run["observation"]

    # -- trace -------------------------------------------------------------
    def a_executes(self, payload: Dict[str, Any]) -> bool:
        key = _json_key(payload)
        if key in self._trace:
            return self._trace[key]
        base = self.variant([], "plus")
        cfg = PROJECTS[self.project_id]
        env = os.environ.copy()
        env["PYTHONPATH"] = str((base / cfg["source_dir"]).resolve())
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONHASHSEED"] = "0"
        env["PYTHONIOENCODING"] = "utf-8"
        env.pop("PYTEST_ADDOPTS", None)
        request = {
            "probe": str(PROBES / self.probe),
            "target_file": str((base / self.target["file"]).resolve()),
            "target_line": int(self.target["line"]),
            "payload": payload,
        }
        completed = subprocess.run(
            [cfg["python"], str(TRACE_RUNNER)],
            input=json.dumps(request, ensure_ascii=False),
            cwd=str(base), env=env, capture_output=True, text=True,
            encoding="utf-8", errors="replace", timeout=180,
        )
        try:
            data = json.loads(completed.stdout.strip().splitlines()[-1])
            executed = data.get("executed") is True
        except (ValueError, IndexError):
            executed = False
        self._trace[key] = executed
        return executed

    # -- finite-domain relations ------------------------------------------
    def relations(self, payload: Dict[str, Any], ids: Sequence[str]) -> Dict[str, Any]:
        """Enumerate every subset of ``ids`` for one input.

        Both maps are indexed by the *disabled* set, exactly like the
        benchmark's public definitions:

        * ``masked[D]`` means P+ and P- agree when every operation in D is
          deleted.  ``Masked_strict(U \\ S)`` therefore reads
          ``masked[key(U - S)]``.
        * ``exposed[D]`` means P+ and P- differ when D is deleted, so
          ``Break(S) = Exposed(S)`` reads ``exposed[key(S)]``.
        """
        ids = sorted(ids)
        subsets: List[List[str]] = []
        for size in range(len(ids) + 1):
            for combo in _combinations(ids, size):
                subsets.append(list(combo))
        masked: Dict[str, bool] = {}
        exposed: Dict[str, bool] = {}
        observations: Dict[str, Any] = {}
        for disabled in subsets:
            plus = self.observation(disabled, "plus", payload)
            minus = self.observation(disabled, "minus", payload)
            key = _key(disabled)
            observations[key] = {"plus": plus, "minus": minus}
            ok = not plus.get("__probe_error__") and not minus.get("__probe_error__")
            masked[key] = bool(ok and plus.get("outcome") == "return"
                               and plus == minus)
            exposed[key] = bool(ok and plus != minus)
        msms = _minimal_masked(masked, ids)
        mmbs = _minimal_exposed(exposed, ids)
        return {
            "ids": ids,
            "masked": masked,
            "exposed": exposed,
            "msms_ids": msms,
            "mmbs_ids": mmbs,
            "observations": observations,
        }


def _combinations(items: Sequence[str], size: int) -> Iterable[Tuple[str, ...]]:
    if size == 0:
        yield ()
        return
    for index in range(len(items) - size + 1):
        head = items[index]
        for tail in _combinations(items[index + 1:], size - 1):
            yield (head,) + tail


def _subsets(universe: Sequence[str]) -> Iterable[List[str]]:
    for size in range(len(universe) + 1):
        for combo in _combinations(universe, size):
            yield list(combo)


def _minimal_masked(masked: Dict[str, bool],
                    universe: Sequence[str]) -> List[List[str]]:
    """Non-empty minimal S with Masked_strict(U \\ S).

    ``masked`` is keyed by the disabled set, so keeping S and deleting the
    complement is ``masked[U - S]``.
    """
    universe = sorted(universe)
    out: List[List[str]] = []
    for kept in _subsets(universe):
        if not kept:
            continue
        rest = sorted(set(universe) - set(kept))
        if not masked.get(_key(rest), False):
            continue
        minimal = True
        for size in range(1, len(kept)):
            for sub in _combinations(kept, size):
                sub_rest = sorted(set(universe) - set(sub))
                if masked.get(_key(sub_rest), False):
                    minimal = False
                    break
            if not minimal:
                break
        if minimal:
            out.append(sorted(kept))
    return sorted(out)


def _minimal_exposed(exposed: Dict[str, bool],
                     universe: Sequence[str]) -> List[List[str]]:
    """Non-empty minimal S with Exposed(S) (S is the disabled set)."""
    universe = sorted(universe)
    out: List[List[str]] = []
    for ids in _subsets(universe):
        if not ids:
            continue
        if not exposed.get(_key(ids), False):
            continue
        minimal = True
        for size in range(0, len(ids)):
            for sub in _combinations(ids, size):
                if exposed.get(_key(sub), False):
                    minimal = False
                    break
            if not minimal:
                break
        if minimal:
            out.append(sorted(ids))
    return sorted(out)


def digest(obj: Any) -> str:
    return hashlib.sha256(
        json.dumps(obj, ensure_ascii=False, sort_keys=True,
                   separators=(",", ":")).encode("utf-8")).hexdigest()
