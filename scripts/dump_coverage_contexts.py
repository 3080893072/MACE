"""Dump per-line dynamic test contexts from a coverage.py data file.

Usage::

    <venv-python> scripts/dump_coverage_contexts.py DATA_FILE PACKAGE_ROOT OUT [WHITELIST]

The output maps absolute source path -> line -> sorted test node ids.  Only
files below ``PACKAGE_ROOT`` are kept (the project's own source).  Contexts of
the form ``nodeid|phase`` are reduced to ``nodeid``; non-test contexts are
dropped.  WHITELIST is an optional JSON object ``{path: [line, ...]}``; when
given, only those paths/lines are dumped (needed for large suites where the
full context table is many gigabytes).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from coverage import CoverageData


def main(argv) -> int:
    if len(argv) not in (4, 5):
        raise SystemExit(__doc__)
    data_file, package_root, out_path = argv[1], Path(argv[2]).resolve(), argv[3]
    whitelist = None
    if len(argv) == 5:
        raw = json.loads(Path(argv[4]).read_text(encoding="utf-8"))
        whitelist = {str(Path(k).resolve()): {int(line) for line in lines}
                     for k, lines in raw.items()}
    data = CoverageData(basename=data_file)
    data.read()
    result = {}
    for filename in sorted(data.measured_files()):
        path = Path(filename).resolve()
        if path != package_root and package_root not in path.parents:
            continue
        wanted = None
        if whitelist is not None:
            wanted = whitelist.get(str(path))
            if not wanted:
                continue
        try:
            by_line = data.contexts_by_lineno(filename)
        except Exception as exc:  # noqa: BLE001 - report, do not hide
            result[str(path)] = {"error": f"{type(exc).__name__}: {exc}"}
            continue
        rows = {}
        for line, contexts in by_line.items():
            if wanted is not None and int(line) not in wanted:
                continue
            tests = sorted({ctx.split("|", 1)[0] for ctx in contexts
                            if "::" in ctx})
            if tests:
                rows[str(line)] = tests
        result[str(path)] = rows
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)
    Path(out_path).write_text(json.dumps(result, indent=1), encoding="utf-8")
    print(json.dumps({"files": len(result),
                      "lines": sum(len(row) for row in result.values()
                                   if isinstance(row, dict))}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
