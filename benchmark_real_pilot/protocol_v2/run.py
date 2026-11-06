"""CLI for protocol v2.

Examples
--------
Freeze T_task once, before any P- run::

    python -m benchmark_real_pilot.protocol_v2.run freeze

Daily benchmark run (frozen T_task only; no project suite)::

    python -m benchmark_real_pilot.protocol_v2.run task --task real_click_truncate_visible

Build the qualification manifest from frozen task runs and cached T_project::

    python -m benchmark_real_pilot.protocol_v2.run manifest
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

KIT = Path(__file__).resolve().parents[2]
if str(KIT) not in sys.path:
    sys.path.insert(0, str(KIT))

from benchmark_real_pilot.protocol_v2.config import TASKS  # noqa: E402
from benchmark_real_pilot.protocol_v2.runner import (  # noqa: E402
    PROTOCOL_DIR,
    build_all_manifests,
    load_existing_task_run,
    run_task_scope,
    write_task_run,
)
from benchmark_real_pilot.protocol_v2.selection import (  # noqa: E402
    freeze_selection,
    load_selection,
)

SELECTION_PATH = PROTOCOL_DIR / "task_selection.json"
MANIFEST_PATH = PROTOCOL_DIR / "task_manifest.json"
CACHE_PATH = PROTOCOL_DIR / "project_suite_cache.json"


def _selection():
    if not SELECTION_PATH.exists():
        raise SystemExit(
            f"missing frozen selection: {SELECTION_PATH}; run the freeze command"
        )
    return load_selection(SELECTION_PATH)


def cmd_freeze(_args) -> int:
    selection = freeze_selection(SELECTION_PATH)
    for task_id, row in selection["tasks"].items():
        print(
            f"{task_id}: {len(row['original_test_ids'])} tests, "
            f"selection_hash={row['selection_hash'][:16]}"
        )
    print(f"wrote {SELECTION_PATH}")
    return 0


def cmd_task(args) -> int:
    selection = _selection()
    task_ids = [args.task] if args.task else list(TASKS)
    for task_id in task_ids:
        task = TASKS[task_id]
        frozen = selection["tasks"][task_id]
        run = run_task_scope(task, frozen, refresh=args.refresh)
        path = write_task_run(task_id, run)
        plus = run["p_plus"]["counts"]
        minus = run["p_minus"]["counts"]
        print(
            f"{task_id}: T_task={len(run['original_test_ids'])} "
            f"P+={plus} P-={minus} survive={run['task_tests_survive']}"
        )
        print(f"wrote {path}")
    return 0


def cmd_manifest(_args) -> int:
    selection = _selection()
    manifest = build_all_manifests(TASKS, selection)
    MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    MANIFEST_PATH.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    CACHE_PATH.write_text(
        json.dumps(
            {
                "protocol_version": "2",
                "generated_utc": manifest["generated_utc"],
                "key_fields": [
                    "project_id",
                    "source_tree_sha256",
                    "environment",
                    "test_scope",
                    "variant",
                ],
                "entries": manifest["project_suite_cache_entries"],
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest["summary"], ensure_ascii=False, indent=2))
    print(f"wrote {MANIFEST_PATH}")
    print(f"wrote {CACHE_PATH}")
    return 0


def cmd_all(args) -> int:
    rc = cmd_freeze(args)
    if rc:
        return rc
    rc = cmd_task(args)
    if rc:
        return rc
    return cmd_manifest(args)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)

    freeze = sub.add_parser("freeze", help="freeze T_task from P+ coverage")
    freeze.set_defaults(func=cmd_freeze)

    task = sub.add_parser("task", help="run only frozen T_task under P+ and P-")
    task.add_argument("--task", choices=sorted(TASKS), default=None)
    task.add_argument("--refresh", action="store_true")
    task.set_defaults(func=cmd_task)

    manifest = sub.add_parser(
        "manifest", help="build manifests from frozen runs + cached T_project"
    )
    manifest.set_defaults(func=cmd_manifest)

    all_cmd = sub.add_parser("all", help="freeze, run T_task, then build manifest")
    all_cmd.add_argument("--task", choices=sorted(TASKS), default=None)
    all_cmd.add_argument("--refresh", action="store_true")
    all_cmd.set_defaults(func=cmd_all)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
