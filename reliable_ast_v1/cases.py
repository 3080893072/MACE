"""Case registry for the reliable-analyzer review (Task 1 regression + Task 2)."""
from __future__ import annotations

from pathlib import Path

from benchmark_baseline.ast_method import PROBE_BY_TASK, input_pool
from benchmark_real_v3.config import KIT
from reliable_ast_v1.analyzer import Spec, V4_PROBES, V4_ROOT, V4_PYTHON

PY_ROOT = V4_ROOT / "pyparsing-3.0.9"
CLICK_ROOT = V4_ROOT / "click-8.4.1"
V4_PY = V4_PYTHON


def _v3_spec(task_id: str) -> Spec:
    return Spec(
        case_id=task_id,
        project_id="werkzeug-2.2.3" if task_id.startswith("werkzeug") else "jinja2-3.1.3",
        kind="v3",
        target_file=_target_file(task_id),
        target_line=_target_line(task_id),
        probe=PROBE_BY_TASK[task_id],
        inputs=input_pool(task_id),
        designed=False,
        original_suite="frozen development task; scorer reference unchanged",
        notes="Task 1 regression: known development task, not an independent test.",
    )


def _target_file(task_id: str) -> str:
    from benchmark_baseline.prompts import public_task
    return public_task(task_id)["target_operation"]["file"]


def _target_line(task_id: str) -> int:
    from benchmark_baseline.prompts import public_task
    return int(public_task(task_id)["target_operation"]["line"])


DEV_TASKS = [
    "jinja2_bytecode_cache_read",
    "werkzeug_bind_server_name_lower",
    "werkzeug_filestorage_stream_name",
    "werkzeug_get_host_default_empty",
    "werkzeug_secure_filename_ascii_filter",
]

SPECS = [_v3_spec(task_id) for task_id in DEV_TASKS] + [
    # A candidate: multi-operation cooperative masking.
    Spec(
        case_id="click_607_args_cooperative",
        project_id="click-8.4.1",
        kind="v4",
        root=CLICK_ROOT,
        source_dir="src",
        python=V4_PY,
        target_file="src/click/shell_completion.py",
        target_line=607,
        probe=str(V4_PROBES / "probe_click_shell_completion_dev.py"),
        inputs=[
            {"args": ["get", "full", ""], "incomplete": ""},
            {"args": ["get", ""], "incomplete": ""},
            {"args": ["get", "full"], "incomplete": ""},
            {"args": ["set", "-y", ""], "incomplete": ""},
        ],
        designed=True,
        original_suite=("upstream tests/test_shell_completion.py::test_chained "
                        "exercises _resolve_context; not modified"),
        notes=("v4 qualification reports MSMS [626,629] and MMBS [626],[629] "
               "from test-pass semantics. This review re-checks strict MACE "
               "observation semantics with a public-API probe."),
    ),
    # C1: object attribute state, __init__ branches.
    Spec(
        case_id="pyparsing_3371_self_maxlen",
        project_id="pyparsing-3.0.9",
        kind="v4",
        root=PY_ROOT,
        source_dir=".",
        python=V4_PY,
        target_file="pyparsing/core.py",
        target_line=3371,
        probe=str(V4_PROBES / "probe_pyparsing_white_parse_dev.py"),
        inputs=[
            {"max": 4, "exact": 2, "min": 1, "text": "    "},
            {"max": 4, "exact": 0, "min": 1, "text": "    "},
        ],
        designed=True,
        original_suite=("upstream tests/test_unit.py exercises White; the two "
                        "payloads here are authored for this review"),
        notes=("A is self.maxLen = max; the exact>0 branch at 3376 overwrites "
               "it. Attribute state, not a bare local name."),
    ),
    # C2: cross-function callback return value.
    Spec(
        case_id="click_2482_callback_return",
        project_id="click-8.4.1",
        kind="v4",
        root=CLICK_ROOT,
        source_dir="src",
        python=V4_PY,
        target_file="src/click/core.py",
        target_line=2482,
        probe=str(KIT / "benchmark_real_v4" / "probes" /
                  "probe_click_process_value.py"),
        inputs=[
            {"value": "42", "callback": "const"},
            {"value": "42", "callback": "echo"},
        ],
        designed=True,
        original_suite=("upstream tests/test_arguments.py exercises "
                        "process_value; payloads here are authored"),
        notes=("A is value = type_cast_value(...); line 2497 replaces value "
               "with a callback return value. Cross-function return flow."),
    ),
    # B candidate: multiple fallback masking paths.
    Spec(
        case_id="pyparsing_3228_quoted_fallbacks",
        project_id="pyparsing-3.0.9",
        kind="v4",
        root=PY_ROOT,
        source_dir=".",
        python=V4_PY,
        target_file="pyparsing/core.py",
        target_line=3228,
        probe=str(V4_PROBES / "probe_pyparsing_quoted_dev.py"),
        inputs=[
            {"quote": ":", "esc": "\\", "esc_quote": "::",
             "convert_ws": True, "unquote": True,
             "text": ":sdf\\:jls::djf:"},
            {"quote": ":", "esc": "\\", "esc_quote": "::",
             "convert_ws": True, "unquote": True,
             "text": ":noescapes:"},
        ],
        designed=True,
        original_suite=("upstream tests/test_unit.py::testCustomQuotes uses "
                        "QuotedString(':', '\\\\', '::'); not modified"),
        notes=("A is ret = ret.replace(wslit, wschar) inside a loop; 3232 and "
               "3236 are two later transforms. v4 qualification reports MSMS "
               "[3232,3236] for testCustomQuotes; strict observation semantics "
               "is re-checked here."),
    ),
    # D candidate: loop-carried state.
    Spec(
        case_id="pyparsing_3310_loop_loc",
        project_id="pyparsing-3.0.9",
        kind="v4",
        root=PY_ROOT,
        source_dir=".",
        python=V4_PY,
        target_file="pyparsing/core.py",
        target_line=3310,
        probe=str(V4_PROBES / "probe_pyparsing_charsnotin_dev.py"),
        inputs=[
            {"not_chars": "x", "max": 4, "text": "aaaa"},
            {"not_chars": "x", "max": 8, "text": "aaaa"},
            {"not_chars": "a", "max": 4, "text": "bbbb"},
        ],
        designed=True,
        original_suite=("upstream tests/test_unit.py exercises White/CharsNotIn; "
                        "payloads here are authored"),
        notes=("A is loc += 1 before the while loop; 3313 increments loc inside "
               "the loop. Manual deletion of 3313 makes parseImpl loop forever "
               "(probe timeout), so it is TIMEOUT/BROKEN_INTERVENTION rather "
               "than an exposed relation."),
    ),
]
