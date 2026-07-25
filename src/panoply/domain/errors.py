"""Domain errors.

Every error a use case can raise on a *foreseen* path lives here, so the
connectors can map them onto transport-specific responses (HTTP status codes,
TUI status lines) without pattern-matching on strings.
"""

from __future__ import annotations


class PanoplyError(Exception):
    """Base class for every error raised by the domain."""


class ConfigurationError(PanoplyError):
    """The server configuration is unusable or refers to something unknown."""


class InvalidConfiguration(ConfigurationError):
    """A configuration document does not have the expected shape."""


class NotFound(ConfigurationError):
    """A referenced aggregate does not exist."""


class ServerNotFound(NotFound):
    """No server with that name exists in the catalog."""

    def __init__(self, name: str) -> None:
        super().__init__(f"Server '{name}' not found")
        self.name = name


class PresetNotFound(NotFound):
    """No preset with that id exists in the preset book."""

    def __init__(self, preset_id: str | None = None) -> None:
        super().__init__("Preset not found")
        self.preset_id = preset_id
