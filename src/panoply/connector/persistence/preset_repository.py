"""JSON-file implementation of :class:`PresetRepository`."""

from __future__ import annotations

from panoply.connector.persistence.files import atomic_write_json, read_json
from panoply.connector.settings import Settings
from panoply.domain.model.preset import PresetBook


class JsonPresetRepository:
    """Stores the whole preset book in a single ``presets.json``."""

    def __init__(self, settings: Settings) -> None:
        self.settings = settings

    @property
    def path(self):
        return self.settings.presets_path

    def load(self) -> PresetBook:
        try:
            return PresetBook.from_payload(read_json(self.path))
        except FileNotFoundError:
            return PresetBook.empty()

    def save(self, book: PresetBook) -> None:
        atomic_write_json(self.path, book.to_payload())
