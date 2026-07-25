"""Low-level JSON file handling shared by the repositories."""

from __future__ import annotations

import asyncio
import json
import os
import tempfile
from pathlib import Path
from typing import Any


def read_json(path: Path) -> Any:
    return json.loads(path.read_text())


def atomic_write_json(path: Path, data: Any) -> None:
    """Write *data* to *path* via a temp file and an atomic rename.

    A crash mid-write leaves the previous document intact rather than a
    truncated one — which for ``servers.json`` is the difference between a
    proxy that restarts and one that comes back with no backends.
    """
    content = json.dumps(data, indent=2)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as handle:
            handle.write(content)
        os.replace(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


class PathLocks:
    """One asyncio lock per resolved path, created on demand.

    Serialises the read-modify-write cycles of concurrent API requests
    touching the same document.
    """

    def __init__(self) -> None:
        self._locks: dict[str, asyncio.Lock] = {}

    def for_path(self, path: Path) -> asyncio.Lock:
        return self._locks.setdefault(str(path.resolve()), asyncio.Lock())

    def clear(self) -> None:
        self._locks.clear()
