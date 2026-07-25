"""Use cases over the server catalog."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from panoply.application.events import ConfigurationEvents
from panoply.domain.model.catalog import ServerCatalog
from panoply.domain.ports.repositories import PresetRepository, ServerCatalogRepository

log = logging.getLogger("panoply.configuration")


class ConfigurationService:
    """Reads and edits the catalog the proxy serves.

    Every write goes through the repository's atomic update, then announces
    itself on :class:`ConfigurationEvents` so a running proxy can catch up.
    """

    def __init__(
        self,
        catalogs: ServerCatalogRepository,
        presets: PresetRepository,
        events: ConfigurationEvents,
    ) -> None:
        self.catalogs = catalogs
        self.presets = presets
        self.events = events

    # ── Locating the active document ──────────────────────────────────────────

    def active_source(self) -> Path:
        """The config file currently in force.

        The active preset wins, then the default document — which is created
        empty if this is a first run.  A preset pointing at a file that has
        since been deleted silently falls back to the default rather than
        leaving the proxy with nothing to serve.
        """
        preset = self.presets.load().active
        if preset is not None and self.catalogs.exists(preset.file_path):
            return preset.file_path
        return self.catalogs.ensure(self.catalogs.default_source())

    def resolve(self, source: Path | None = None) -> Path:
        return source if source is not None else self.active_source()

    # ── Reading ───────────────────────────────────────────────────────────────

    def load_catalog(self, source: Path | None = None) -> ServerCatalog:
        return self.catalogs.load(self.resolve(source))

    def read_document(self, source: Path | None = None) -> dict[str, Any]:
        return self.catalogs.read_document(self.resolve(source))

    # ── Writing ───────────────────────────────────────────────────────────────

    async def replace_document(
        self, document: dict[str, Any], source: Path | None = None
    ) -> None:
        """Overwrite a whole configuration document.

        The body is stored verbatim: this is the escape hatch for editors that
        manage the file themselves, so Panoply must not normalise it away.
        """
        await self.catalogs.write_document(self.resolve(source), document)
        self.events.configuration_changed()

    async def set_server_enabled(
        self, name: str, enabled: bool, source: Path | None = None
    ) -> None:
        await self.catalogs.update(
            self.resolve(source), lambda catalog: catalog.with_server_enabled(name, enabled)
        )
        log.info("%s server %s", "Enabled" if enabled else "Disabled", name)
        self.events.configuration_changed()

    async def set_tool_enabled(
        self, server: str, tool: str, enabled: bool, source: Path | None = None
    ) -> None:
        """Switch one tool on or off.

        Announced as a tool-visibility change rather than a full configuration
        change: the set of backends is untouched, so a running proxy can flip
        the tool in place instead of restarting subprocesses.
        """
        await self.catalogs.update(
            self.resolve(source),
            lambda catalog: catalog.with_tool_enabled(server, tool, enabled),
        )
        log.info("%s tool %s_%s", "Enabled" if enabled else "Disabled", server, tool)
        self.events.tool_visibility_changed(server, tool, enabled)
