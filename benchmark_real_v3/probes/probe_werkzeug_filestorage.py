"""Observe FileStorage filename derivation from the stream object."""
from __future__ import annotations

import io
import json
import os
import sys
import tempfile

from werkzeug.datastructures import FileStorage


class NamedBytesIO(io.BytesIO):
    def __init__(self, data: bytes, name):
        super().__init__(data)
        self.name = name


def main() -> int:
    payload = json.load(sys.stdin)
    kind = payload["stream"]
    cleanup = []
    if kind == "stderr":
        stream = sys.stderr
    elif kind == "none":
        stream = io.BytesIO(payload.get("data", "").encode())
    elif kind == "tempfile":
        fd, path = tempfile.mkstemp()
        os.close(fd)
        stream = open(path, "wb")
        cleanup.append(stream)
        cleanup.append(path)
    elif kind == "named":
        stream = NamedBytesIO(
            payload.get("data", "").encode(), payload.get("name", ""))
    else:
        raise SystemExit(f"unknown stream kind: {kind}")
    try:
        storage = FileStorage(stream)
        filename = storage.filename
        observation = {
            "outcome": "return",
            "filename": filename,
            "filename_type": type(filename).__name__,
        }
    except Exception as exc:  # noqa: BLE001
        observation = {
            "outcome": "raise",
            "type": type(exc).__name__,
            "message": str(exc),
        }
    finally:
        for item in cleanup:
            try:
                if hasattr(item, "close"):
                    item.close()
                else:
                    os.unlink(item)
            except OSError:
                pass
    print(json.dumps(observation, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
