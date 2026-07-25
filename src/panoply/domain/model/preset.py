"""Named configurations the user can switch between.

A preset points at a configuration file on disk; the *active* preset decides
which catalog the proxy serves.  ``PresetBook`` is the aggregate that owns
both the collection and the "which one is active" invariant.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from panoply.domain.errors import InvalidConfiguration, PresetNotFound

PRESETS_KEY = "presets"
ACTIVE_KEY = "activePresetID"


@dataclass(frozen=True)
class Preset:
    """A named pointer to a configuration file."""

    id: str
    name: str
    file_path: Path
    extras: Mapping[str, Any] = field(default_factory=dict)

    @classmethod
    def from_payload(cls, payload: Any) -> Preset:
        if not isinstance(payload, Mapping):
            raise InvalidConfiguration("preset entries must be JSON objects")
        identifier = payload.get("id") or ""
        name = payload.get("name") or ""
        file_path = payload.get("filePath")
        if file_path is None:
            return cls(identifier, name, Path("servers.json"))
        extras = {
            k: v for k, v in payload.items() if k not in {"id", "name", "filePath"}
        }
        return cls(identifier, name, Path(file_path), extras)

    def to_payload(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "filePath": str(self.file_path),
            **self.extras,
        }

    def renamed(self, name: str) -> Preset:
        return Preset(self.id, name, self.file_path, self.extras)

    def relocated(self, file_path: Path) -> Preset:
        return Preset(self.id, self.name, file_path, self.extras)


@dataclass(frozen=True)
class PresetBook:
    """Every preset plus the id of the active one (``None`` = the default)."""

    presets: tuple[Preset, ...] = ()
    active_id: str | None = None

    # ── Construction ──────────────────────────────────────────────────────────

    @classmethod
    def from_payload(cls, payload: Any) -> PresetBook:
        if not isinstance(payload, Mapping):
            raise InvalidConfiguration("presets file must be a JSON object")
        entries = payload.get(PRESETS_KEY)
        if entries is None:
            entries = []
        if not isinstance(entries, list):
            raise InvalidConfiguration(f"'{PRESETS_KEY}' must be a JSON array")
        return cls(
            tuple(Preset.from_payload(entry) for entry in entries),
            payload.get(ACTIVE_KEY),
        )

    @classmethod
    def empty(cls) -> PresetBook:
        return cls()

    def to_payload(self) -> dict[str, Any]:
        return {
            PRESETS_KEY: [preset.to_payload() for preset in self.presets],
            ACTIVE_KEY: self.active_id,
        }

    # ── Reading ───────────────────────────────────────────────────────────────

    def __iter__(self) -> Iterator[Preset]:
        return iter(self.presets)

    def __len__(self) -> int:
        return len(self.presets)

    def find(self, preset_id: str) -> Preset | None:
        return next((p for p in self.presets if p.id == preset_id), None)

    def get(self, preset_id: str) -> Preset:
        preset = self.find(preset_id)
        if preset is None:
            raise PresetNotFound(preset_id)
        return preset

    @property
    def active(self) -> Preset | None:
        return self.find(self.active_id) if self.active_id else None

    def is_active(self, preset_id: str) -> bool:
        return self.active_id == preset_id

    # ── Transitions ───────────────────────────────────────────────────────────

    def added(self, preset: Preset) -> PresetBook:
        return PresetBook((*self.presets, preset), self.active_id)

    def replaced(self, preset: Preset) -> PresetBook:
        if self.find(preset.id) is None:
            raise PresetNotFound(preset.id)
        presets = tuple(preset if p.id == preset.id else p for p in self.presets)
        return PresetBook(presets, self.active_id)

    def removed(self, preset_id: str) -> PresetBook:
        """Drop a preset; deleting the active one reverts to the default."""
        self.get(preset_id)
        presets = tuple(p for p in self.presets if p.id != preset_id)
        active = None if self.is_active(preset_id) else self.active_id
        return PresetBook(presets, active)

    def activated(self, preset_id: str | None) -> PresetBook:
        """Make *preset_id* active; ``None`` reverts to the default config."""
        if preset_id is not None:
            self.get(preset_id)
        return PresetBook(self.presets, preset_id)
