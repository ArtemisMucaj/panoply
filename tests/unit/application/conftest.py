"""In-memory doubles for the ports.

The application layer is supposed to run with no framework and no filesystem;
these fakes are what makes that testable — and a compile-time check that the
ports are small enough to reimplement in a few lines.
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path
from typing import Any

import pytest

from panoply.application.configuration import ConfigurationService
from panoply.application.events import ConfigurationEvents
from panoply.domain.model.catalog import ServerCatalog
from panoply.domain.model.preset import PresetBook
from panoply.domain.model.server import ServerDefinition
from panoply.domain.model.tool import ToolDescriptor

DEFAULT_SOURCE = Path("/memory/servers.json")


class InMemoryCatalogRepository:
    """A dict of documents keyed by path."""

    def __init__(self, documents: dict[Path, dict[str, Any]] | None = None) -> None:
        self.documents: dict[Path, dict[str, Any]] = dict(documents or {})
        self.default = DEFAULT_SOURCE

    def default_source(self) -> Path:
        return self.default

    def exists(self, source: Path) -> bool:
        return source in self.documents

    def ensure(self, source: Path) -> Path:
        self.documents.setdefault(source, ServerCatalog.empty().to_payload())
        return source

    def read_document(self, source: Path) -> dict[str, Any]:
        return self.documents[source]

    def load(self, source: Path) -> ServerCatalog:
        return ServerCatalog.from_payload(self.documents.get(source, {}))

    def save(self, source: Path, catalog: ServerCatalog) -> None:
        self.documents[source] = catalog.to_payload()

    async def write_document(self, source: Path, document: dict[str, Any]) -> None:
        self.documents[source] = document

    async def update(
        self, source: Path, mutate: Callable[[ServerCatalog], ServerCatalog]
    ) -> ServerCatalog:
        updated = mutate(self.load(source))
        self.save(source, updated)
        return updated


class InMemoryPresetRepository:
    def __init__(self, book: PresetBook | None = None) -> None:
        self.book = book or PresetBook.empty()

    def load(self) -> PresetBook:
        return self.book

    def save(self, book: PresetBook) -> None:
        self.book = book


class ScriptedProbe:
    """Returns canned tools per server name, or raises what it was told to."""

    def __init__(self, results: dict[str, Any] | None = None) -> None:
        self.results = results or {}
        self.calls: list[str] = []

    async def probe(self, server: ServerDefinition) -> list[ToolDescriptor]:
        self.calls.append(server.name)
        outcome = self.results.get(server.name, [])
        if isinstance(outcome, BaseException):
            raise outcome
        if callable(outcome):
            return await outcome()
        return [
            tool if isinstance(tool, ToolDescriptor) else ToolDescriptor(tool)
            for tool in outcome
        ]


class RecordingEvents(ConfigurationEvents):
    """Counts what was published."""

    def __init__(self) -> None:
        super().__init__()
        self.changes = 0
        self.tool_changes: list[tuple[str, str, bool]] = []
        self.on_configuration_changed(self._count_change)
        self.on_tool_visibility_changed(self._count_tool_change)

    def _count_change(self) -> None:
        self.changes += 1

    def _count_tool_change(self, server: str, tool: str, enabled: bool) -> None:
        self.tool_changes.append((server, tool, enabled))


@pytest.fixture
def events() -> RecordingEvents:
    return RecordingEvents()


@pytest.fixture
def catalogs() -> InMemoryCatalogRepository:
    return InMemoryCatalogRepository(
        {
            DEFAULT_SOURCE: {
                "mcpServers": {
                    "alpha": {"url": "http://a"},
                    "beta": {"command": "echo", "disabledTools": ["noisy"]},
                    "gamma": {"url": "http://g", "enabled": False},
                }
            }
        }
    )


@pytest.fixture
def presets() -> InMemoryPresetRepository:
    return InMemoryPresetRepository()


@pytest.fixture
def configuration(
    catalogs: InMemoryCatalogRepository,
    presets: InMemoryPresetRepository,
    events: RecordingEvents,
) -> ConfigurationService:
    return ConfigurationService(catalogs, presets, events)
