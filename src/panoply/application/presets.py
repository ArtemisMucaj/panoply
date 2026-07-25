"""Use cases over the preset book."""

from __future__ import annotations

import logging
import uuid
from collections.abc import Callable
from pathlib import Path

from panoply.application.events import ConfigurationEvents
from panoply.domain.model.preset import Preset, PresetBook
from panoply.domain.ports.repositories import PresetRepository

log = logging.getLogger("panoply.presets")


def _uuid() -> str:
    return str(uuid.uuid4())


class PresetService:
    """Manages named configurations and which one is active.

    Activating, deleting the active preset, or repointing it at another file
    all change which catalog is served, so they announce a configuration
    change; renaming does not.
    """

    def __init__(
        self,
        presets: PresetRepository,
        events: ConfigurationEvents,
        identifiers: Callable[[], str] = _uuid,
    ) -> None:
        self.presets = presets
        self.events = events
        self.identifiers = identifiers

    def book(self) -> PresetBook:
        return self.presets.load()

    def create(self, name: str, file_path: Path | str) -> Preset:
        preset = Preset(self.identifiers(), name, Path(file_path))
        self.presets.save(self.book().added(preset))
        log.info("Created preset %s (%s)", name, preset.file_path)
        return preset

    def update(
        self,
        preset_id: str,
        *,
        name: str | None = None,
        file_path: Path | str | None = None,
    ) -> Preset:
        book = self.book()
        preset = book.get(preset_id)
        if name is not None:
            preset = preset.renamed(name)
        if file_path is not None:
            preset = preset.relocated(Path(file_path))
        self.presets.save(book.replaced(preset))
        if file_path is not None and book.is_active(preset_id):
            self.events.configuration_changed()
        return preset

    def delete(self, preset_id: str) -> None:
        book = self.book()
        was_active = book.is_active(preset_id)
        self.presets.save(book.removed(preset_id))
        log.info("Deleted preset %s", preset_id)
        if was_active:
            self.events.configuration_changed()

    def activate(self, preset_id: str | None) -> str | None:
        """Switch presets. ``None`` reverts to the default configuration."""
        book = self.book().activated(preset_id)
        self.presets.save(book)
        log.info("Activated preset %s", preset_id or "(default)")
        self.events.configuration_changed()
        return book.active_id
