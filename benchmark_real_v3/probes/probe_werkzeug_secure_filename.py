"""Observe secure_filename for one user-supplied filename."""
from __future__ import annotations

import json
import sys

from werkzeug.utils import secure_filename


def main() -> int:
    payload = json.load(sys.stdin)
    try:
        name = secure_filename(payload["filename"])
        observation = {"outcome": "return", "filename": name}
    except Exception as exc:  # noqa: BLE001
        observation = {
            "outcome": "raise",
            "type": type(exc).__name__,
            "message": str(exc),
        }
    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
