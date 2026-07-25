"""JSON-file implementation of :class:`ServerCatalogRepository`."""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

from panoply.connector.persistence.files import PathLocks, atomic_write_json, read_json
from panoply.connector.settings import Settings
from panoply.domain.model.catalog import ServerCatalog


class JsonServerCatalogRepository:
    """Stores catalogs as MCP-config JSON documents, one per file."""

    def __init__(self, settings: Settings, locks: PathLocks | None = None) -> None:
        self.settings = settings
        self.locks = locks or PathLocks()

    # ── Locating ──────────────────────────────────────────────────────────────

    def default_source(self) -> Path:
        return self.settings.default_catalog_path

    def exists(self, source: Path) -> bool:
        return source.exists()

    def ensure(self, source: Path) -> Path:
        """Create an empty catalog at *source* if this is a first run."""
        if not source.exists():
            atomic_write_json(source, ServerCatalog.empty().to_payload())
        return source

    # ── Reading ───────────────────────────────────────────────────────────────

    def read_document(self, source: Path) -> dict[str, Any]:
        return read_json(source)

    def load(self, source: Path) -> ServerCatalog:
        try:
            return ServerCatalog.from_payload(read_json(source))
        except FileNotFoundError:
            return ServerCatalog.empty()

    # ── Writing ───────────────────────────────────────────────────────────────

    def save(self, source: Path, catalog: ServerCatalog) -> None:
        atomic_write_json(source, catalog.to_payload())

    async def write_document(self, source: Path, document: dict[str, Any]) -> None:
        async with self.locks.for_path(source):
            atomic_write_json(source, document)

    async def update(
        self,
        source: Path,
        mutate: Callable[[ServerCatalog], ServerCatalog],
    ) -> ServerCatalog:
        """Read, apply *mutate*, write — under this document's lock.

        The catalog is re-read inside the lock so concurrent edits compose
        instead of clobbering each other, and a raising *mutate* (an unknown
        server, say) leaves the file untouched.
        """
        async with self.locks.for_path(source):
            updated = mutate(ServerCatalog.from_payload(read_json(source)))
            atomic_write_json(source, updated.to_payload())
            return updated
