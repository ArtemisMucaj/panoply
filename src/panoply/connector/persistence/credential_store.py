"""Disk-backed implementation of :class:`CredentialStore`."""

from __future__ import annotations

from key_value.aio.stores.disk import DiskStore

from panoply.connector.settings import Settings


class DiskCredentialStore:
    """Wraps the ``py-key-value`` disk store that FastMCP writes tokens into.

    The MCP client's OAuth handler needs the store object itself, so
    :attr:`backend` is deliberately exposed for the config translator to hand
    over — everything else goes through the port.
    """

    def __init__(self, settings: Settings) -> None:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        self.backend = DiskStore(directory=str(settings.data_dir))

    def keys(self) -> list[str]:
        return list(self.backend._cache.iterkeys())

    def clear(self) -> None:
        self.backend._cache.clear()
