"""Port for the cached OAuth credentials of proxied servers."""

from __future__ import annotations

from typing import Protocol, runtime_checkable


@runtime_checkable
class CredentialStore(Protocol):
    """Opaque store of tokens, keyed by the backend they belong to."""

    def keys(self) -> list[str]:
        """Every cache key currently held (used to report per-server counts)."""

    def clear(self) -> None:
        """Forget every cached credential."""
