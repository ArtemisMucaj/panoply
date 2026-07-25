"""Notifications the application layer publishes when state changes.

Use cases don't know that a live proxy exists — they announce what happened
and whoever is running (the HTTP host, a test) reacts.  This is what lets a
config edit hot-swap the proxy without the REST API importing FastMCP.
"""

from __future__ import annotations

import logging
from collections.abc import Callable

log = logging.getLogger("panoply.events")

ConfigurationChanged = Callable[[], None]
ToolVisibilityChanged = Callable[[str, str, bool], None]


class ConfigurationEvents:
    """A tiny synchronous publisher. Subscribers are called in order."""

    def __init__(self) -> None:
        self._changed: list[ConfigurationChanged] = []
        self._tool_visibility: list[ToolVisibilityChanged] = []

    # ── Subscribing ───────────────────────────────────────────────────────────

    def on_configuration_changed(self, handler: ConfigurationChanged) -> None:
        """React to a change that alters *which* backends are proxied."""
        self._changed.append(handler)

    def on_tool_visibility_changed(self, handler: ToolVisibilityChanged) -> None:
        """React to a single tool being switched on or off."""
        self._tool_visibility.append(handler)

    def clear(self) -> None:
        self._changed.clear()
        self._tool_visibility.clear()

    # ── Publishing ────────────────────────────────────────────────────────────

    def configuration_changed(self) -> None:
        for handler in self._changed:
            self._safely(handler)

    def tool_visibility_changed(self, server: str, tool: str, enabled: bool) -> None:
        for handler in self._tool_visibility:
            self._safely(handler, server, tool, enabled)

    @staticmethod
    def _safely(handler: Callable[..., None], *args: object) -> None:
        """A broken subscriber must not fail the use case that published."""
        try:
            handler(*args)
        except Exception:
            log.exception("configuration event handler failed")
