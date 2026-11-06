"""Execution-based, normalized scoring for benchmark v3 submissions.

The scorer consumes only the hidden reference (operation locations, probe,
declared candidate universe) and the submitted payloads.  It does not trust a
submitted expected observation, a submitted relation label, or the stored
reference matrix.  Every relation is re-executed against freshly built P+/P-
variants with all subsets of the declared candidate universe enumerated.

Status vocabulary
-----------------
``WITNESS_VERIFIED``
    The claim was checked by execution on the submitted finite witness(es).
``FINITE_DOMAIN_EXACT``
    The claim was checked on every input in a submitted finite list, with all
    subsets of U enumerated.  This is *not* exactness over the legal input
    domain.
``PROVEN``
    Reserved for a formally checked proof.  This scorer has no proof checker,
    so it never assigns this status.
``FALSE``
    Execution contradicts the claim.
``INVALID``
    The claim or a submitted input violates the published contract.
``UNVERIFIED``
    The claim names an operation outside the declared U, or asks for a proof
    check that this scorer cannot perform.
``UNSUPPORTED``
    The claim type is unknown.
``DUPLICATE``
    An exact duplicate of an earlier claim; it earns no additional credit.
"""
from __future__ import annotations

import hashlib
import itertools
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Dict, Iterable, List, Sequence, Tuple

from benchmark_real_v3.config import PROJECTS, V3
from benchmark_real_v3.scoring.contracts import validate_payload
from benchmark_real_v3.variant_lab import build_variant, run_probe

RELEASE = V3 / "release"
TRACE_HELPER = V3 / "acceptance_probe.py"
HIDDEN = RELEASE / "HIDDEN"
SCORER_VERSION = "mace-benchmark-v3-scorer-1.0"

STATUSES = [
    "WITNESS_VERIFIED",
    "FINITE_DOMAIN_EXACT",
    "PROVEN",
    "FALSE",
    "INVALID",
    "UNVERIFIED",
    "UNSUPPORTED",
    "DUPLICATE",
]
CREDITED = {"WITNESS_VERIFIED", "FINITE_DOMAIN_EXACT"}
CLAIM_TYPES = {
    "EXPOSING_COUNTEREXAMPLE",
    "MSMS",
    "MMBS",
    "PREREQUISITE_BREAKING",
    "CONDITIONAL_CORRECTNESS",
    "PROVEN",
}


def _canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _compact(text: str) -> str:
    return "".join(text.split())


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


class ReferenceError_(RuntimeError):
    pass


class TaskScorer:
    def __init__(self, reference: Dict[str, Any], hidden_root: Path | None = None):
        self.ref = reference
        self.task_id = reference["task_id"]
        self.project_id = reference["project_id"]
        self.hidden_root = hidden_root or HIDDEN
        self.target = reference["target_operation"]
        self.universe: List[Dict[str, Any]] = reference["candidate_universe"]
        self.by_id = {op["id"]: op for op in self.universe}
        self.probe = reference["probe"]
        self._variants: Dict[Tuple[str, str, str], Path] = {}
        self._relations_cache: Dict[str, Dict[str, Any]] = {}
        self._run_cache: Dict[Tuple[str, str, str, str], Dict[str, Any]] = {}
        self._execution_cache: Dict[str, bool] = {}

    # ------------------------------------------------------------- variants
    def _variant(self, subset_key: str, side: str) -> Path:
        cache_key = (self.task_id, subset_key, side)
        if cache_key in self._variants:
            return self._variants[cache_key]
        disabled = [] if subset_key == "EMPTY" else [
            self.by_id[op_id] for op_id in subset_key.split("+")]
        statements: List[Tuple[str, int]] = []
        blocks: List[Tuple[str, int, int]] = []
        if side == "minus":
            statements.append((self.target["file"], int(self.target["line"])))
        for op in disabled:
            if op.get("kind") == "block":
                blocks.append((
                    op["file"], int(op["first_line"]), int(op["last_line"])))
            else:
                statements.append((op["file"], int(op["line"])))
        name = f"score_{self.task_id}_{side}_{subset_key.replace('+', '_')}"
        variant = build_variant(
            self.project_id, name,
            statement_deletions=statements,
            block_deletions=blocks,
        )
        path = Path(variant["root"])
        self._variants[cache_key] = path
        return path

    def _run(self, subset_key: str, side: str, payload: Dict[str, Any]) -> Dict[str, Any]:
        key = (subset_key, side, _canonical_json(payload), self.task_id)
        if key in self._run_cache:
            return self._run_cache[key]
        path = self._variant(subset_key, side)
        result = run_probe(self.project_id, path, self.probe, payload)
        self._run_cache[key] = result
        return result

    def _a_executes(self, payload: Dict[str, Any]) -> bool:
        """Trace the submitted input on P+ and report whether A executed."""
        cache_key = _canonical_json(payload)
        if cache_key in self._execution_cache:
            return self._execution_cache[cache_key]
        base = self._variant("EMPTY", "plus")
        cfg = PROJECTS[self.project_id]
        env = os.environ.copy()
        env["PYTHONPATH"] = str((base / cfg["source_dir"]).resolve())
        env["PYTHONDONTWRITEBYTECODE"] = "1"
        env["PYTHONHASHSEED"] = "0"
        env["PYTHONIOENCODING"] = "utf-8"
        env.pop("PYTEST_ADDOPTS", None)
        request = {
            "probe": str((V3 / "probes") / self.probe),
            "target_file": str((base / self.target["file"]).resolve()),
            "target_line": int(self.target["line"]),
            "payload": payload,
        }
        completed = subprocess.run(
            [cfg["python"], str(TRACE_HELPER)],
            input=json.dumps(request, ensure_ascii=False),
            cwd=str(base),
            env=env,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=180,
        )
        try:
            data = json.loads(completed.stdout.strip().splitlines()[-1])
            executed = data.get("executed") is True
        except (ValueError, IndexError):
            executed = False
        self._execution_cache[cache_key] = executed
        return executed

    @staticmethod
    def _executable(run: Dict[str, Any]) -> bool:
        observation = run.get("observation")
        return (
            run.get("returncode") == 0
            and isinstance(observation, dict)
            and "outcome" in observation
            and not observation.get("probe_crash")
        )

    def relations(self, payload: Dict[str, Any], *, full: bool = True) -> Dict[str, Any]:
        """Compute masked/exposed and, if requested, MSMS/MMBS for one input."""
        cache_key = ("full:" if full else "base:") + _canonical_json(payload)
        if cache_key in self._relations_cache:
            return self._relations_cache[cache_key]
        subsets: List[str]
        if full:
            subsets = []
            for size in range(len(self.universe) + 1):
                for combo in itertools.combinations(self.universe, size):
                    subsets.append("+".join(sorted(op["id"] for op in combo)) or "EMPTY")
        else:
            subsets = ["EMPTY"]
        runs: Dict[str, Dict[str, Dict[str, Any]]] = {"plus": {}, "minus": {}}
        for subset_key in subsets:
            for side in ("plus", "minus"):
                runs[side][subset_key] = self._run(subset_key, side, payload)
        masked: Dict[str, bool] = {}
        exposed: Dict[str, bool] = {}
        for subset_key in subsets:
            plus = runs["plus"][subset_key]
            minus = runs["minus"][subset_key]
            ok = self._executable(plus) and self._executable(minus)
            masked[subset_key] = bool(
                ok
                and plus["observation"].get("outcome") == "return"
                and plus["observation"] == minus["observation"]
            )
            exposed[subset_key] = bool(
                ok and plus["observation"] != minus["observation"])
        msms: List[List[str]] = []
        mmbs: List[List[str]] = []
        if full:
            for size in range(len(self.universe) + 1):
                for combo in itertools.combinations(self.universe, size):
                    ids = sorted(op["id"] for op in combo)
                    key = "+".join(ids) or "EMPTY"
                    # Only(S) = Masked_strict(U \ S)
                    rest = sorted(set(self.by_id) - set(ids))
                    rest_key = "+".join(rest) or "EMPTY"
                    if ids and masked.get(rest_key):
                        minimal = True
                        for sub_size in range(1, len(ids)):
                            for sub in itertools.combinations(ids, sub_size):
                                sub_rest = sorted(set(self.by_id) - set(sub))
                                if masked.get("+".join(sub_rest) or "EMPTY"):
                                    minimal = False
                                    break
                            if not minimal:
                                break
                        if minimal:
                            msms.append(ids)
                    # Break(S) = Exposed(S), no nonempty proper subset breaks.
                    if ids and exposed.get(key):
                        minimal = True
                        for sub_size in range(0, len(ids)):
                            for sub in itertools.combinations(ids, sub_size):
                                if exposed.get("+".join(sub) or "EMPTY"):
                                    minimal = False
                                    break
                            if not minimal:
                                break
                        if minimal:
                            mmbs.append(ids)
            msms = sorted(msms)
            mmbs = sorted(mmbs)
        result = {
            "masked_strict": masked,
            "exposed": exposed,
            "msms_ids": msms,
            "mmbs_ids": mmbs,
            "runs": runs,
        }
        self._relations_cache[cache_key] = result
        return result

    # ------------------------------------------------------------- locations
    def _normalize_file(self, file_value: Any) -> Tuple[str | None, str | None]:
        if not isinstance(file_value, str):
            return None, "operation file must be a string"
        normalized = file_value.replace("\\", "/").strip()
        while normalized.startswith("./"):
            normalized = normalized[2:]
        if not normalized or normalized.startswith("/") or ".." in normalized.split("/"):
            return None, f"operation file is not project-relative: {file_value!r}"
        return normalized, None

    def resolve_operation(self, submitted: Any) -> Dict[str, Any]:
        """Resolve a submitted location to a declared U operation or a scope error."""
        if not isinstance(submitted, dict):
            return {"error": "operation must be an object"}
        allowed = {"file", "line", "end_line", "code"}
        unknown = sorted(set(submitted) - allowed)
        if unknown:
            return {"error": f"unknown operation field(s): {unknown}"}
        file_value, file_error = self._normalize_file(submitted.get("file"))
        if file_error:
            return {"error": file_error}
        line = submitted.get("line")
        if not _is_int(line) or line < 1:
            return {"error": "operation line must be a positive integer"}
        end_line = submitted.get("end_line", line)
        if not _is_int(end_line) or end_line < line:
            return {"error": "operation end_line must be an integer >= line"}
        code = submitted.get("code")
        if code is not None and not isinstance(code, str):
            return {"error": "operation code must be a string when present"}
        matches = []
        for op in self.universe:
            first = int(op.get("first_line", op.get("line", -1)))
            last = int(op.get("last_line", op.get("line", -1)))
            if op["file"] != file_value:
                continue
            if "end_line" in submitted:
                if first == line and last == end_line:
                    matches.append(op)
            elif first <= line <= last:
                matches.append(op)
        if len(matches) > 1:
            return {"error": "operation location is ambiguous in the declared universe"}
        if not matches:
            root = PROJECTS[self.project_id]["root"]
            path = root / file_value
            if not path.exists() or not path.is_file():
                return {"error": f"source file does not exist: {file_value}"}
            lines = path.read_text(encoding="utf-8").splitlines()
            if line > len(lines):
                return {"error": f"line {line} is outside {file_value}"}
            location = f"{file_value}:{line}"
            if end_line != line:
                location += f"-{end_line}"
            return {
                "op": None,
                "location": location,
                "scope_error": (
                    "operation is outside the declared candidate universe; "
                    "the scorer cannot perform that exact intervention"),
            }
        op = matches[0]
        if code is not None and _compact(code) != _compact(op["code"]):
            return {"error": f"submitted code does not match the operation at "
                             f"{file_value}:{line}"}
        first = int(op.get("first_line", op.get("line")))
        last = int(op.get("last_line", op.get("line")))
        location = f"{op['file']}:{first}" if first == last else (
            f"{op['file']}:{first}-{last}")
        return {"op": op, "location": location}

    def _resolve_operations(self, raw: Any) -> Dict[str, Any]:
        if not isinstance(raw, list) or not raw:
            return {"error": "operations must be a non-empty list"}
        resolved = []
        seen = set()
        for item in raw:
            result = self.resolve_operation(item)
            if result.get("error"):
                return {"error": result["error"]}
            if result.get("scope_error"):
                return {
                    "scope_error": result["scope_error"],
                    "location": result["location"],
                }
            op = result["op"]
            if op["id"] in seen:
                return {"error": f"duplicate operation: {result['location']}"}
            seen.add(op["id"])
            resolved.append({"op": op, "location": result["location"]})
        return {"operations": resolved}

    def _location_map(self) -> Dict[str, str]:
        mapping = {}
        for op in self.universe:
            first = int(op.get("first_line", op.get("line")))
            last = int(op.get("last_line", op.get("line")))
            mapping[op["id"]] = (
                f"{op['file']}:{first}" if first == last
                else f"{op['file']}:{first}-{last}")
        return mapping

    def _relation_sets_to_locations(
        self, relations: Sequence[Sequence[str]]
    ) -> List[List[str]]:
        mapping = self._location_map()
        return sorted([sorted(mapping[op_id] for op_id in rel) for rel in relations])

    # ------------------------------------------------------------- claims
    def _input_list(self, claim: Dict[str, Any]) -> Dict[str, Any]:
        has_one = "input" in claim
        has_many = "inputs" in claim
        if has_one == has_many:
            return {"error": "exactly one of input/inputs is required"}
        raw = [claim["input"]] if has_one else claim["inputs"]
        if not isinstance(raw, list) or not raw:
            return {"error": "inputs must be a non-empty list"}
        if len(raw) > 12:
            return {"error": "at most 12 finite inputs may be submitted"}
        errors = []
        for index, payload in enumerate(raw):
            violations = validate_payload(self.task_id, payload)
            if violations:
                errors.append(f"input[{index}]: " + "; ".join(violations))
        if errors:
            return {"error": "; ".join(errors)}
        return {"inputs": raw, "single": has_one}

    def _claim_key(self, claim: Dict[str, Any]) -> str | None:
        claim_type = claim.get("type")
        if claim_type == "EXPOSING_COUNTEREXAMPLE":
            if "input" not in claim:
                return None
            return _canonical_json([claim_type, claim["input"]])
        if claim_type in ("MSMS", "MMBS"):
            if "input" not in claim and "inputs" not in claim:
                return None
            if "operations" not in claim:
                return None
            ops = []
            for item in claim.get("operations") or []:
                if isinstance(item, dict):
                    ops.append([
                        item.get("file"), item.get("line"),
                        item.get("end_line"), item.get("code"),
                    ])
            return _canonical_json([
                claim_type, claim.get("input"), claim.get("inputs"),
                sorted(ops, key=lambda item: _canonical_json(item)),
            ])
        if claim_type == "PREREQUISITE_BREAKING":
            return _canonical_json([
                claim_type, claim.get("input"), claim.get("control_input"),
                claim.get("operations"),
            ])
        if claim_type == "CONDITIONAL_CORRECTNESS":
            return _canonical_json([
                claim_type, claim.get("condition_input"),
                claim.get("conclusion_input"), claim.get("operations"),
            ])
        if claim_type == "PROVEN":
            return _canonical_json([
                claim_type, claim.get("statement"), claim.get("proof")])
        return None

    def score_claim(self, claim: Any, index: int) -> Dict[str, Any]:
        if not isinstance(claim, dict):
            return self._result(index, "UNKNOWN", "INVALID", "claim must be an object")
        claim_type = claim.get("type")
        if not isinstance(claim_type, str):
            return self._result(index, "UNKNOWN", "INVALID", "claim.type must be a string")
        if claim_type not in CLAIM_TYPES:
            return self._result(
                index, claim_type, "UNSUPPORTED",
                "claim type is not supported by this scorer")
        if claim_type == "PROVEN":
            return self._result(
                index, claim_type, "UNVERIFIED",
                "PROVEN is reserved for a formally checked proof; this scorer "
                "has no proof checker and does not assign it from execution.")
        if claim_type == "EXPOSING_COUNTEREXAMPLE":
            return self._score_exposing(claim, index)
        if claim_type in ("MSMS", "MMBS"):
            return self._score_minimal_set(claim, index, claim_type)
        if claim_type == "PREREQUISITE_BREAKING":
            return self._score_prerequisite(claim, index)
        if claim_type == "CONDITIONAL_CORRECTNESS":
            return self._score_conditional(claim, index)
        return self._result(index, claim_type, "UNSUPPORTED", "unsupported claim")

    @staticmethod
    def _result(index: int, claim_type: Any, status: str, reason: str,
                **extra: Any) -> Dict[str, Any]:
        result = {
            "index": index,
            "type": claim_type,
            "status": status,
            "reason": reason,
            "scope": extra.pop("scope", None),
            "relation_key": extra.pop("relation_key", None),
        }
        result.update(extra)
        return result

    def _score_exposing(self, claim: Dict[str, Any], index: int) -> Dict[str, Any]:
        if "input" not in claim:
            return self._result(index, "EXPOSING_COUNTEREXAMPLE", "INVALID",
                                "input is required")
        violations = validate_payload(self.task_id, claim["input"])
        if violations:
            return self._result(index, "EXPOSING_COUNTEREXAMPLE", "INVALID",
                                "; ".join(violations))
        if not self._a_executes(claim["input"]):
            return self._result(
                index, "EXPOSING_COUNTEREXAMPLE", "FALSE",
                "A is not executed on the submitted input; the deletion has "
                "no observed local effect there")
        rel = self.relations(claim["input"], full=False)
        plus = rel["runs"]["plus"]["EMPTY"]
        minus = rel["runs"]["minus"]["EMPTY"]
        if not self._executable(plus):
            return self._result(index, "EXPOSING_COUNTEREXAMPLE", "INVALID",
                                "P+ did not produce an observation for the input")
        if not self._executable(minus):
            return self._result(index, "EXPOSING_COUNTEREXAMPLE", "INVALID",
                                "P- did not produce an observation for the input")
        if plus["observation"] == minus["observation"]:
            return self._result(
                index, "EXPOSING_COUNTEREXAMPLE", "FALSE",
                "P+ and P- produced equal observations, so the input does not "
                "expose the deletion",
                relation_key="EXPOSING",
                observations={"plus": plus["observation"],
                              "minus": minus["observation"]})
        return self._result(
            index, "EXPOSING_COUNTEREXAMPLE", "WITNESS_VERIFIED",
            "Both sides executed and produced different observations.",
            scope="one submitted input; no claim over other legal inputs",
            relation_key="EXPOSING",
            observations={"plus": plus["observation"],
                          "minus": minus["observation"]})

    def _verify_minimal_set(
        self, claim: Dict[str, Any], kind: str
    ) -> Dict[str, Any]:
        parsed_inputs = self._input_list(claim)
        if parsed_inputs.get("error"):
            return {"error": parsed_inputs["error"]}
        resolved = self._resolve_operations(claim.get("operations"))
        if resolved.get("error"):
            return {"error": resolved["error"]}
        if resolved.get("scope_error"):
            return {"scope_error": resolved["scope_error"],
                    "location": resolved["location"]}
        ids = sorted(item["op"]["id"] for item in resolved["operations"])
        locations = sorted(item["location"] for item in resolved["operations"])
        signature = tuple(ids)
        per_input = []
        for payload in parsed_inputs["inputs"]:
            if not self._a_executes(payload):
                per_input.append({
                    "verified": False, "contradicted": True,
                    "reason": (
                        "A is not executed on the submitted input; a masking "
                        "label there would be vacuous"),
                })
                continue
            rel = self.relations(payload, full=True)
            plus_base = rel["runs"]["plus"]["EMPTY"]
            if not self._executable(plus_base):
                return {
                    "error": (
                        "P+ did not produce an observation for a submitted "
                        "input; the input is not a legal executable witness"),
                }
            if not rel["mmbs_ids"]:
                per_input.append({
                    "verified": False, "contradicted": True,
                    "reason": (
                        "no nonempty subset of U exposes the deletion on this "
                        "input; there is no observable local effect to mask"),
                })
                continue
            masked_empty = rel["masked_strict"].get("EMPTY", False)
            exposed_empty = rel["exposed"].get("EMPTY", False)
            computed = rel["msms_ids"] if kind == "MSMS" else rel["mmbs_ids"]
            verified = signature in {tuple(item) for item in computed}
            if not masked_empty:
                reason = (
                    "the input is not strictly masked at EMPTY; a masking "
                    "relation cannot be established on it")
                if exposed_empty:
                    reason += " (it is an exposing input)"
                per_input.append({
                    "verified": False, "contradicted": True,
                    "reason": reason,
                })
            elif not verified:
                per_input.append({
                    "verified": False, "contradicted": True,
                    "reason": (
                        f"the submitted set is not a minimal "
                        f"{'sufficient' if kind == 'MSMS' else 'breaking'} "
                        "set over the declared candidate universe"),
                    "computed_minimal_sets": self._relation_sets_to_locations(
                        computed),
                })
            else:
                per_input.append({
                    "verified": True,
                    "reason": "set matches an enumerated minimal relation",
                    "computed_minimal_sets": self._relation_sets_to_locations(
                        computed),
                })
        if any(not item["verified"] for item in per_input):
            return {
                "status": "FALSE",
                "reason": "; ".join(item["reason"] for item in per_input),
                "per_input": per_input,
                "locations": locations,
            }
        distinct_inputs = {
            _canonical_json(payload) for payload in parsed_inputs["inputs"]}
        status = (
            "FINITE_DOMAIN_EXACT"
            if len(distinct_inputs) >= 2
            else "WITNESS_VERIFIED"
        )
        return {
            "status": status,
            "reason": (
                "Every submitted finite input matches the enumerated minimal "
                f"{'sufficient' if kind == 'MSMS' else 'breaking'} set, and "
                "all subsets of the declared candidate universe were checked."
            ),
            "per_input": per_input,
            "locations": locations,
            "scope": (
                f"{len(parsed_inputs['inputs'])} submitted finite input(s) and "
                "all subsets of U; not the whole legal input domain"
            ),
        }

    def _score_minimal_set(
        self, claim: Dict[str, Any], index: int, kind: str
    ) -> Dict[str, Any]:
        verified = self._verify_minimal_set(claim, kind)
        if verified.get("error"):
            return self._result(index, kind, "INVALID", verified["error"])
        if verified.get("scope_error"):
            return self._result(
                index, kind, "UNVERIFIED",
                verified["scope_error"],
                scope="outside the declared candidate universe",
                relation_key=f"{kind}:{verified.get('location')}")
        status = verified["status"]
        locations = verified["locations"]
        relation_key = f"{kind}:" + "+".join(locations)
        return self._result(
            index, kind, status, verified["reason"],
            scope=verified.get("scope"),
            relation_key=relation_key,
            operations=locations,
            per_input=verified["per_input"])

    def _score_prerequisite(self, claim: Dict[str, Any], index: int) -> Dict[str, Any]:
        for field in ("input", "control_input", "operations"):
            if field not in claim:
                return self._result(index, "PREREQUISITE_BREAKING", "INVALID",
                                    f"{field} is required")
        for field in ("input", "control_input"):
            violations = validate_payload(self.task_id, claim[field])
            if violations:
                return self._result(
                    index, "PREREQUISITE_BREAKING", "INVALID",
                    f"{field}: " + "; ".join(violations))
        resolved = self._resolve_operations(claim["operations"])
        if resolved.get("error"):
            return self._result(index, "PREREQUISITE_BREAKING", "INVALID",
                                resolved["error"])
        if resolved.get("scope_error"):
            return self._result(
                index, "PREREQUISITE_BREAKING", "UNVERIFIED",
                resolved["scope_error"],
                scope="outside the declared candidate universe")
        ids = tuple(sorted(item["op"]["id"] for item in resolved["operations"]))
        locations = sorted(item["location"] for item in resolved["operations"])
        conditioned = self.relations(claim["input"], full=True)
        control = self.relations(claim["control_input"], full=True)
        if not self._a_executes(claim["input"]):
            return self._result(
                index, "PREREQUISITE_BREAKING", "FALSE",
                "A is not executed on the condition input")
        if not self._a_executes(claim["control_input"]):
            return self._result(
                index, "PREREQUISITE_BREAKING", "FALSE",
                "A is not executed on the control input")
        if not self._executable(conditioned["runs"]["plus"]["EMPTY"]):
            return self._result(
                index, "PREREQUISITE_BREAKING", "INVALID",
                "P+ did not produce an observation for the condition input")
        if not self._executable(control["runs"]["plus"]["EMPTY"]):
            return self._result(
                index, "PREREQUISITE_BREAKING", "INVALID",
                "P+ did not produce an observation for the control input")
        condition_mmbs = {tuple(item) for item in conditioned["mmbs_ids"]}
        control_mmbs = {tuple(item) for item in control["mmbs_ids"]}
        conditioned_ok = (
            conditioned["masked_strict"].get("EMPTY", False)
            and ids in condition_mmbs
        )
        control_ok = ids not in control_mmbs
        if not conditioned_ok:
            status = "FALSE"
            reason = (
                "the submitted set is not a minimal breaking set on the "
                "condition input")
        elif not control_ok:
            status = "FALSE"
            reason = (
                "the same set also breaks the masking relation on the control "
                "input, so the stated prerequisite is not necessary")
        else:
            status = "WITNESS_VERIFIED"
            reason = (
                "The set is a minimal breaking set on the condition input and "
                "does not break on the control input.")
        return self._result(
            index, "PREREQUISITE_BREAKING", status, reason,
            scope=(
                "two submitted point witnesses; this is a conditional "
                "witness check, not a domain-wide implication"),
            relation_key="PREREQUISITE:" + "+".join(locations),
            operations=locations,
            prerequisite=claim.get("prerequisite"),
            details={
                "condition_masked_EMPTY": conditioned["masked_strict"].get("EMPTY"),
                "condition_msms": self._relation_sets_to_locations(
                    conditioned["msms_ids"]),
                "condition_mmbs": self._relation_sets_to_locations(
                    conditioned["mmbs_ids"]),
                "control_masked_EMPTY": control["masked_strict"].get("EMPTY"),
                "control_mmbs": self._relation_sets_to_locations(
                    control["mmbs_ids"]),
            })

    def _score_conditional(self, claim: Dict[str, Any], index: int) -> Dict[str, Any]:
        for field in ("condition_input", "conclusion_input", "operations"):
            if field not in claim:
                return self._result(index, "CONDITIONAL_CORRECTNESS", "INVALID",
                                    f"{field} is required")
        for field in ("condition_input", "conclusion_input"):
            violations = validate_payload(self.task_id, claim[field])
            if violations:
                return self._result(
                    index, "CONDITIONAL_CORRECTNESS", "INVALID",
                    f"{field}: " + "; ".join(violations))
        resolved = self._resolve_operations(claim["operations"])
        if resolved.get("error"):
            return self._result(index, "CONDITIONAL_CORRECTNESS", "INVALID",
                                resolved["error"])
        if resolved.get("scope_error"):
            return self._result(
                index, "CONDITIONAL_CORRECTNESS", "UNVERIFIED",
                resolved["scope_error"],
                scope="outside the declared candidate universe")
        ids = tuple(sorted(item["op"]["id"] for item in resolved["operations"]))
        locations = sorted(item["location"] for item in resolved["operations"])
        condition = self.relations(claim["condition_input"], full=True)
        conclusion = self.relations(claim["conclusion_input"], full=True)
        if not self._a_executes(claim["condition_input"]):
            return self._result(
                index, "CONDITIONAL_CORRECTNESS", "FALSE",
                "A is not executed on the condition input")
        if not self._a_executes(claim["conclusion_input"]):
            return self._result(
                index, "CONDITIONAL_CORRECTNESS", "FALSE",
                "A is not executed on the conclusion input")
        if not self._executable(condition["runs"]["plus"]["EMPTY"]):
            return self._result(
                index, "CONDITIONAL_CORRECTNESS", "INVALID",
                "P+ did not produce an observation for the condition input")
        if not self._executable(conclusion["runs"]["plus"]["EMPTY"]):
            return self._result(
                index, "CONDITIONAL_CORRECTNESS", "INVALID",
                "P+ did not produce an observation for the conclusion input")
        condition_ok = (
            condition["masked_strict"].get("EMPTY", False)
            and ids in {tuple(item) for item in condition["mmbs_ids"]}
        )
        conclusion_ok = ids not in {
            tuple(item) for item in conclusion["mmbs_ids"]}
        if condition_ok and conclusion_ok:
            status = "WITNESS_VERIFIED"
            reason = (
                "The set breaks on the condition input and does not break on "
                "the conclusion/control input.")
        else:
            status = "FALSE"
            reason = (
                "the two submitted inputs do not satisfy the stated "
                "conditional pattern")
        return self._result(
            index, "CONDITIONAL_CORRECTNESS", status, reason,
            scope=(
                "two submitted point witnesses; conditional correctness is "
                "not promoted to a domain-wide theorem"),
            relation_key="CONDITIONAL:" + "+".join(locations),
            operations=locations,
            details={
                "condition_mask_holds": condition_ok,
                "conclusion_break_holds": not conclusion_ok,
                "condition_masked_EMPTY": condition["masked_strict"].get("EMPTY"),
                "conclusion_masked_EMPTY": conclusion["masked_strict"].get("EMPTY"),
            })


def load_reference(task_id: str, hidden_root: Path | None = None) -> Dict[str, Any]:
    root = hidden_root or HIDDEN
    path = root / "tasks" / task_id / "reference.json"
    if not path.exists():
        raise ReferenceError_(f"hidden reference not found: {path}")
    return json.loads(path.read_text(encoding="utf-8"))


def score_submission(
    submission: Dict[str, Any],
    *,
    hidden_root: Path | None = None,
) -> Dict[str, Any]:
    task_id = submission.get("task_id")
    if not isinstance(task_id, str):
        return {
            "protocol": "mace_benchmark_v3_scoring",
            "scorer_version": SCORER_VERSION,
            "status": "INVALID_SUBMISSION",
            "error": "submission.task_id must be a string",
            "claims": [],
            "status_counts": {status: 0 for status in STATUSES},
        }
    try:
        reference = load_reference(task_id, hidden_root)
    except ReferenceError_ as exc:
        return {
            "protocol": "mace_benchmark_v3_scoring",
            "scorer_version": SCORER_VERSION,
            "task_id": task_id,
            "status": "UNKNOWN_TASK",
            "error": str(exc),
            "claims": [],
            "status_counts": {status: 0 for status in STATUSES},
        }
    scorer = TaskScorer(reference, hidden_root)
    claims = submission.get("claims")
    if not isinstance(claims, list):
        return {
            "protocol": "mace_benchmark_v3_scoring",
            "scorer_version": SCORER_VERSION,
            "task_id": task_id,
            "status": "INVALID_SUBMISSION",
            "error": "submission.claims must be a list",
            "claims": [],
            "status_counts": {status: 0 for status in STATUSES},
        }
    results = []
    seen_keys: Dict[str, int] = {}
    credited_relations: Dict[str, int] = {}
    for index, claim in enumerate(claims):
        key = scorer._claim_key(claim) if isinstance(claim, dict) else None
        if key is not None and key in seen_keys:
            results.append(scorer._result(
                index, claim.get("type") if isinstance(claim, dict) else None,
                "DUPLICATE",
                f"exact duplicate of claim #{seen_keys[key]}; no credit"))
            continue
        if key is not None:
            seen_keys[key] = index
        result = scorer.score_claim(claim, index)
        if result["status"] in CREDITED and result.get("relation_key"):
            relation = result["relation_key"]
            if relation in credited_relations:
                result["credit"] = 0
                result["reason"] += (
                    f" Relation already credited by claim "
                    f"#{credited_relations[relation]}; no duplicate credit.")
            else:
                result["credit"] = 1
                credited_relations[relation] = index
        else:
            result["credit"] = 0
        results.append(result)
    status_counts = {status: 0 for status in STATUSES}
    for result in results:
        status_counts[result["status"]] = status_counts.get(
            result["status"], 0) + 1
    return {
        "protocol": "mace_benchmark_v3_scoring",
        "scorer_version": SCORER_VERSION,
        "task_id": task_id,
        "submission_id": submission.get("submission_id"),
        "status_counts": status_counts,
        "score": {
            "credited_relations": len(credited_relations),
            "claim_credit": sum(result.get("credit", 0) for result in results),
            "domain_exact_relations": sum(
                1 for result in results
                if result["status"] == "FINITE_DOMAIN_EXACT"
                and result.get("credit") == 1),
            "witness_verified_relations": sum(
                1 for result in results
                if result["status"] == "WITNESS_VERIFIED"
                and result.get("credit") == 1),
            "deduplicated": status_counts["DUPLICATE"],
        },
        "claims": results,
        "scope_notes": [
            "Minimality is exact only over the declared candidate universe U "
            "and the submitted finite inputs.",
            "A single witness is never promoted to a claim over the whole "
            "legal input domain.",
            "Operations outside U are reported UNVERIFIED, not FALSE.",
        ],
    }
