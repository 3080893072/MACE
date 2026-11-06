"""Record a verdict for every candidate that survived the full suite.

The verdict map is exhaustive over the survivors of ``screening_funnel.json``;
the script fails if a survivor has no recorded verdict or if a verdict names a
candidate that did not survive.  Qualified entries point at the executed
enable/disable matrix; rejected entries state the concrete reason and keep the
screening row as evidence.

These are task-construction verdicts, not claims that a rejected operation is
unobservable in every possible context.  ``UNVERIFIED`` scope notes say what
was not tested.
"""
from __future__ import annotations

import json
from pathlib import Path

from benchmark_real_v3.config import EVIDENCE

FUNNEL = EVIDENCE / "screening_funnel.json"
OUT = EVIDENCE / "qualification_registry.json"

ROW_DIR = EVIDENCE / "screening_rows"


def _row(candidate_id: str) -> str:
    for path in sorted(ROW_DIR.glob("*.json")):
        data = json.loads(path.read_text(encoding="utf-8"))
        if data["candidate_id"] == candidate_id:
            return str(path)
    raise RuntimeError(f"no screening row for {candidate_id}")


VERDICTS = {
    # ---------------------------------------------------------------- qualified
    "jinja2-3.1.3:src/jinja2/loaders.py:132:code": {
        "verdict": "QUALIFIED",
        "task_id": "jinja2_bytecode_cache_read",
        "mechanism": "coexisting backup path",
        "basis": (
            "Executed exposing input (poisoned BytecodeCache: P+ renders 2, "
            "P- renders 42) and executed masking input (benign cache: both 42) "
            "with MSMS = MMBS = [compile_fallback].  The P- applicable suite "
            "passes (845 tests)."
        ),
        "evidence": ["evidence/jinja2_bytecode_cache_read_matrix.json"],
    },
    "werkzeug-2.2.3:src/werkzeug/datastructures.py:2918:filename": {
        "verdict": "QUALIFIED",
        "task_id": "werkzeug_filestorage_stream_name",
        "mechanism": "conditional overwrite",
        "basis": (
            "Executed exposing input (tempfile-backed stream: P+ filename is "
            "the path, P- is None) and executed masking input (<stderr>: both "
            "None) with MSMS = MMBS = [special_name_reset].  The P- applicable "
            "suite passes (816 tests)."
        ),
        "evidence": ["evidence/werkzeug_filestorage_stream_name_matrix.json"],
    },
    "werkzeug-2.2.3:src/werkzeug/routing/map.py:307:server_name": {
        "verdict": "QUALIFIED",
        "task_id": "werkzeug_bind_server_name_lower",
        "mechanism": "cross-function re-derivation with a control prerequisite",
        "basis": (
            "Executed exposing input (no supplied subdomain: P+ subdomain '' "
            "vs P- '<invalid>') and executed masking input (subdomain='www': "
            "both 'example.com') with MSMS = MMBS = [bind_relower].  The "
            "masking requires the control prerequisite subdomain is not None.  "
            "The P- applicable suite passes (816 tests)."
        ),
        "evidence": ["evidence/werkzeug_bind_server_name_lower_matrix.json"],
    },
    "werkzeug-2.2.3:src/werkzeug/sansio/utils.py:82:host": {
        "verdict": "QUALIFIED",
        "task_id": "werkzeug_get_host_default_empty",
        "mechanism": "two alternative conditional overwrites",
        "basis": (
            "Executed exposing input (neither Host header nor server: P+ host "
            "'' vs P- UnboundLocalError) and two executed masking inputs.  "
            "Host header masks A with MSMS = MMBS = [overwrite_host_header]; "
            "server address masks A with MSMS = MMBS = [overwrite_server].  "
            "The two paths are mutually exclusive per input.  The P- "
            "applicable suite passes (816 tests)."
        ),
        "evidence": ["evidence/werkzeug_get_host_default_empty_matrix.json"],
    },
    "werkzeug-2.2.3:src/werkzeug/utils.py:222:filename": {
        "verdict": "QUALIFIED",
        "task_id": "werkzeug_secure_filename_ascii_filter",
        "mechanism": "downstream sanitization absorption",
        "basis": (
            "Executed exposing input (U+1680: P+ 'ab' vs P- 'a_b') and "
            "executed masking input (CJK letters removed by the later "
            "whitelist: both 'txt') with MSMS = MMBS = [sanitize_whitelist].  "
            "The P- applicable suite passes (816 tests)."
        ),
        "evidence": ["evidence/werkzeug_secure_filename_ascii_filter_matrix.json"],
    },
    # ------------------------------------------------- no exposing input found
    "jinja2-3.1.3:src/jinja2/debug.py:27:tb": {
        "verdict": "REJECT_NO_EXPOSING_INPUT",
        "basis": (
            "t.cast is a runtime identity.  The deleted assignment would leave "
            "tb bound to the same object returned by sys.exc_info(); no legal "
            "input can distinguish the variants."
        ),
    },
    "jinja2-3.1.3:src/jinja2/utils.py:354:word": {
        "verdict": "REJECT_NO_EXPOSING_INPUT",
        "basis": (
            "Dead store.  Every Load of word is dominated by the unconditional "
            "Store at line 361 inside the inner while loop; if the loop body is "
            "never entered, word is never read.  The static flag "
            "later_write_reads_A came from line 366, but line 361 intervenes "
            "and does not read the old value."
        ),
    },
    "click-8.4.1:src/click/core.py:3383:source": {
        "verdict": "REJECT_NO_EXPOSING_INPUT",
        "basis": (
            "Redundant assignment.  value is FLAG_NEEDS_VALUE only when the "
            "parser supplied it through opts, and Parameter.consume_value "
            "already returns ParameterSource.COMMANDLINE in that case."
        ),
    },
    "click-8.4.1:src/click/core.py:3406:source": {
        "verdict": "REJECT_NO_EXPOSING_INPUT",
        "basis": (
            "Redundant assignment for the same reason as line 3383: "
            "FLAG_NEEDS_VALUE entries come from the parser, so source is "
            "already COMMANDLINE when this branch is reached."
        ),
    },
    "click-8.4.1:src/click/testing.py:202:input": {
        "verdict": "REJECT_NO_EXPOSING_INPUT",
        "basis": (
            "Equivalent replacement.  For input=None, P+ returns "
            "BytesIO(b''); deleting the line falls through to BytesIO(None), "
            "which is also an empty buffer."
        ),
    },
    "werkzeug-2.2.3:src/werkzeug/test.py:400:query_string": {
        "verdict": "REJECT_NO_EXPOSING_INPUT",
        "basis": (
            "Equivalent replacement.  For query_string=None, deleting the line "
            "enters the next branch with None, and MultiDict(None) builds the "
            "same empty mapping as MultiDict()."
        ),
    },
    "werkzeug-2.2.3:src/werkzeug/wsgi.py:684:stream": {
        "verdict": "REJECT_NO_EXPOSING_INPUT",
        "basis": (
            "t.cast is a runtime identity; the value is unchanged, so no "
            "observation can differ."
        ),
    },
    "werkzeug-2.2.3:src/werkzeug/datastructures.py:1778:best_specificity": {
        "verdict": "REJECT_NO_EXPOSING_INPUT",
        "basis": (
            "Dead store.  The first accepted match assigns best_specificity at "
            "line 1791.  Line 1788 reads it only when quality > best_quality is "
            "false, which requires a prior accepted match; the first accepted "
            "match short-circuits before the read."
        ),
    },
    # ---------------------------------------------- no masking relation found
    "jinja2-3.1.3:src/jinja2/debug.py:42:tb": {
        "verdict": "REJECT_NO_MASKING_RELATION",
        "basis": (
            "Deleting the render-frame skip changes runtime tracebacks (an "
            "exposing input is constructible), but no later statement in "
            "cleanup_traceback absorbs the extra frame.  Template.render is "
            "not in internal_code, so the internal-code skip at lines 51-53 "
            "does not mask the deletion."
        ),
    },
    "click-8.4.1:src/click/core.py:452:auto_envvar_prefix": {
        "verdict": "REJECT_NO_MASKING_RELATION",
        "basis": (
            "The uppercased prefix is stored directly; the later statement only "
            "replaces hyphens with underscores and does not restore or mask the "
            "letter case.  No execution-confirmed masking relation was found."
        ),
    },
    "click-8.4.1:src/click/exceptions.py:181:param_hint": {
        "verdict": "REJECT_NO_MASKING_RELATION",
        "basis": (
            "The joined hint is consumed immediately by the f-string at line "
            "182; no later operation re-normalizes or replaces it."
        ),
    },
    "click-8.4.1:src/click/termui.py:212:confirmation_prompt": {
        "verdict": "REJECT_NO_MASKING_RELATION",
        "basis": (
            "The translated prompt string is consumed by _build_prompt in the "
            "same branch; no later operation supplies or absorbs it."
        ),
    },
    "click-8.4.1:src/click/core.py:3260:default": {
        "verdict": "REJECT_NO_MASKING_RELATION",
        "basis": (
            "No later statement in the bool-flag branch rewrites default, and "
            "no operation outside the branch absorbs a deleted assignment.  No "
            "execution-confirmed masking relation was found."
        ),
    },
    "click-8.4.1:src/click/shell_completion.py:607:args": {
        "verdict": "REJECT_NO_MASKING_RELATION",
        "basis": (
            "args is read by the while condition and resolve_command in the "
            "same iteration; the next-iteration assignment cannot mask that "
            "read."
        ),
    },
    "jinja2-3.1.3:src/jinja2/lexer.py:640:value": {
        "verdict": "REJECT_NO_MASKING_RELATION",
        "basis": (
            "The name-token value is consumed by value.isidentifier() and the "
            "token append before any later write; no operation absorbs it."
        ),
    },
    "werkzeug-2.2.3:src/werkzeug/wsgi.py:826:separator": {
        "verdict": "REJECT_NO_MASKING_RELATION",
        "basis": (
            "The converted separator is consumed by re.compile in the same "
            "branch; no later operation masks the conversion."
        ),
    },
    "werkzeug-2.2.3:src/werkzeug/wsgi.py:846:buf_size": {
        "verdict": "REJECT_NO_MASKING_RELATION",
        "basis": (
            "buf_size is read by the cap check at line 851 before the only "
            "later write at line 857; no execution-confirmed masking relation "
            "was found."
        ),
    },
    "werkzeug-2.2.3:src/werkzeug/datastructures.py:2921:filename": {
        "verdict": "REJECT_NO_MASKING_RELATION",
        "basis": (
            "fsdecode output flows directly to the public filename attribute.  "
            "The special-name reset at lines 2923-2924 applies to '<...>' names, "
            "where deletion is exposed rather than masked."
        ),
    },
    "werkzeug-2.2.3:src/werkzeug/routing/map.py:704:subdomain": {
        "verdict": "REJECT_NO_MASKING_RELATION",
        "basis": (
            "subdomain is consumed by the truth test and the f-string at lines "
            "708-709; no later operation re-supplies it."
        ),
    },
    "werkzeug-2.2.3:src/werkzeug/_reloader.py:127:name": {
        "verdict": "REJECT_NO_MASKING_RELATION",
        "basis": (
            "abspath output is consumed by isfile/dirname/dirs.add.  "
            "_find_common_roots preserves the relative-vs-absolute path "
            "structure, so it does not mask the conversion."
        ),
    },
    "werkzeug-2.2.3:src/werkzeug/datastructures.py:339:value": {
        "verdict": "REJECT_NO_MASKING_RELATION",
        "basis": (
            "list(value) is stored directly in tmp.  The else-branch line 341 "
            "is not executed for tuple/list values, so no operation in the "
            "function masks A."
        ),
    },
    "werkzeug-2.2.3:src/werkzeug/http.py:771:last_end": {
        "verdict": "REJECT_NO_MASKING_RELATION",
        "basis": (
            "last_end is read by the next iteration's guard (lines 764/782); "
            "the suffix branch does not execute the later write at line 794, "
            "so no operation masks A on the inputs where it matters."
        ),
    },
    "werkzeug-2.2.3:src/werkzeug/wrappers/response.py:518:content_length": {
        "verdict": "REJECT_NO_MASKING_RELATION",
        "basis": (
            "Deleting A leaves content_length=None, which triggers the "
            "automatic-length block.  A correct supplied length is masked by "
            "the block, but disabling the block leaves both variants with the "
            "original header, so Break(U) is false and MMBS is empty."
        ),
    },
    "werkzeug-2.2.3:src/werkzeug/http.py:440:continued_encoding": {
        "verdict": "REJECT_NO_MASKING_RELATION",
        "mechanism": "loop-carried state; masked but not breakable under U",
        "basis": (
            "Supplementary MSMS-only case.  Executed inputs: expose_reset "
            "(P+ size '%E6%96%87' vs P- decoded '文') and mask_state_overwrite "
            "(both '文字') with MSMS = [write_state].  MMBS is empty: disabling "
            "line 444 removes every non-None supplier of continued_encoding, "
            "so P+ and P- both end with None and the deletion is no longer "
            "observable.  The task is rejected under the both-direction "
            "(MSMS and MMBS) criterion used by the five qualified tasks.  A "
            "symmetric task with A=line 444, U=line 440 (which does admit an "
            "MMBS) was NOT screened in this round: line 444 is not a static "
            "candidate and the predeclared targeted budget was already spent.  "
            "It remains UNVERIFIED."
        ),
        "evidence": [
            "evidence/werkzeug_parse_options_header_continuation_state_matrix.json",
            "evidence/rejected_tasks/werkzeug_parse_options_header_continuation_state_spec.json",
        ],
    },
}


def main() -> int:
    funnel = json.loads(FUNNEL.read_text(encoding="utf-8"))
    survivors = set(funnel["survivors"])
    unknown = survivors - set(VERDICTS)
    extra = set(VERDICTS) - survivors
    if unknown:
        raise RuntimeError(f"unreviewed survivors: {sorted(unknown)}")
    if extra:
        raise RuntimeError(f"verdicts for non-survivors: {sorted(extra)}")

    registry = {}
    for candidate_id in sorted(survivors):
        entry = dict(VERDICTS[candidate_id])
        entry["candidate_id"] = candidate_id
        entry["screening_row"] = _row(candidate_id)
        if entry["verdict"] != "QUALIFIED":
            entry.setdefault(
                "scope",
                "Rejected for this task-construction round only; no claim "
                "that A is unobservable outside the stated check.",
            )
        else:
            entry["scope"] = (
                "Exact over the declared inputs and candidate universe U; "
                "not a claim over the whole legal input domain or operations "
                "outside U."
            )
        registry[candidate_id] = entry

    OUT.write_text(
        json.dumps({
            "protocol": "benchmark_real_v3",
            "survivors": len(survivors),
            "qualified": sum(
                1 for e in registry.values()
                if e["verdict"] == "QUALIFIED"),
            "verdict_counts": {
                verdict: sum(
                    1 for e in registry.values()
                    if e["verdict"] == verdict)
                for verdict in sorted({e["verdict"] for e in registry.values()})
            },
            "candidates": registry,
        }, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(json.dumps({
        "survivors": len(survivors),
        "verdicts": {
            v: sum(1 for e in registry.values() if e["verdict"] == v)
            for v in sorted({e["verdict"] for e in registry.values()})
        },
    }, ensure_ascii=False, indent=2))
    print("wrote", OUT)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
