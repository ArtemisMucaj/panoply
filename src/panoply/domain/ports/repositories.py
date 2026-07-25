"""Persistence ports.

The domain states what it needs from storage; ``panoply.connector.persistence``
supplies JSON-file implementations.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

from panoply.domain.model.catalog import ServerCatalog
from panoply.domain.model.preset import PresetBook


@runtime_checkable
class ServerCatalogRepository(Protocol):
    """Reads and writes catalog documents, one per source location."""

    def default_source(self) -> Path:
        """Where the catalog lives when no preset is active."""

    def exists(self, source: Path) -> bool: ...

    def ensure(self, source: Path) -> Path:
        """Create an empty catalog at *source* if it isn't there yet."""

    def load(self, source: Path) -> ServerCatalog: ...

    def read_document(self, source: Path) -> dict[str, Any]:
        """Return the raw parsed document, unvalidated and unmodified."""

    async def write_document(self, source: Path, document: dict[str, Any]) -> None:
        """Replace the document at *source* atomically."""

    def save(self, source: Path, catalog: ServerCatalog) -> None:
        """Write *catalog* to *source* atomically, without locking.

        For callers that already own the document (the TUI); concurrent
        writers should go through :meth:`update` instead.
        """

    async def update(
        self,
        source: Path,
        mutate: Callable[[ServerCatalog], ServerCatalog],
    ) -> ServerCatalog:
        """Apply *mutate* to the stored catalog as one atomic read-modify-write.

        The repository owns the unit of work: it holds the per-source lock,
        loads, applies the domain transition, and persists the result.  If
        *mutate* raises, nothing is written.
        """


@runtime_checkable
class PresetRepository(Protocol):
    """Reads and writes the single preset book."""

    def load(self) -> PresetBook: ...

    def save(self, book: PresetBook) -> None: ...
