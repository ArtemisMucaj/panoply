"""The catalog of backend servers — Panoply's central aggregate.

A ``ServerCatalog`` is one configuration document (``servers.json`` or a
preset file) read as domain objects.  Every mutation returns a new catalog,
so a use case can build the next state and hand it to a repository to persist
atomically.
"""

from __future__ import annotations

from collections.abc import Iterator, Mapping
from dataclasses import dataclass, field
from typing import Any

from panoply.domain.errors import InvalidConfiguration, ServerNotFound
from panoply.domain.model.server import ServerDefinition

SERVERS_KEY = "mcpServers"


@dataclass(frozen=True)
class ServerCatalog:
    """An ordered set of :class:`ServerDefinition` plus the document around it.

    ``extras`` (top-level keys other than ``mcpServers``) and ``malformed``
    (entries that aren't JSON objects) are carried through untouched so that
    loading and saving a hand-written config never destroys anything Panoply
    doesn't understand.
    """

    servers: tuple[ServerDefinition, ...] = ()
    extras: Mapping[str, Any] = field(default_factory=dict)
    malformed: Mapping[str, Any] = field(default_factory=dict)

    # ── Construction ──────────────────────────────────────────────────────────

    @classmethod
    def from_payload(cls, payload: Any) -> ServerCatalog:
        """Read a parsed configuration document into the aggregate."""
        if not isinstance(payload, Mapping):
            raise InvalidConfiguration("configuration must be a JSON object")
        entries = payload.get(SERVERS_KEY)
        if entries is None:
            entries = {}
        if not isinstance(entries, Mapping):
            raise InvalidConfiguration(f"'{SERVERS_KEY}' must be a JSON object")

        servers: list[ServerDefinition] = []
        malformed: dict[str, Any] = {}
        for name, settings in entries.items():
            if isinstance(settings, Mapping):
                servers.append(ServerDefinition(name, dict(settings)))
            else:
                malformed[name] = settings

        extras = {k: v for k, v in payload.items() if k != SERVERS_KEY}
        return cls(tuple(servers), extras, malformed)

    @classmethod
    def empty(cls) -> ServerCatalog:
        return cls()

    def to_payload(self) -> dict[str, Any]:
        """Serialise back to a configuration document."""
        entries: dict[str, Any] = {s.name: dict(s.settings) for s in self.servers}
        entries.update(self.malformed)
        return {**self.extras, SERVERS_KEY: entries}

    # ── Reading ───────────────────────────────────────────────────────────────

    def __iter__(self) -> Iterator[ServerDefinition]:
        return iter(self.servers)

    def __len__(self) -> int:
        return len(self.servers)

    def __contains__(self, name: object) -> bool:
        return any(s.name == name for s in self.servers)

    @property
    def names(self) -> tuple[str, ...]:
        return tuple(s.name for s in self.servers)

    @property
    def enabled_servers(self) -> tuple[ServerDefinition, ...]:
        return tuple(s for s in self.servers if s.enabled)

    def find(self, name: str) -> ServerDefinition | None:
        return next((s for s in self.servers if s.name == name), None)

    def get(self, name: str) -> ServerDefinition:
        server = self.find(name)
        if server is None:
            raise ServerNotFound(name)
        return server

    # ── Projections used by the proxy runtime ─────────────────────────────────

    def disabled_tool_names(self) -> frozenset[str]:
        """Qualified ``server_tool`` names to hide, for enabled servers only.

        A disabled server contributes nothing at all, so there is no point
        listing its individually-disabled tools.
        """
        return frozenset(
            name
            for server in self.enabled_servers
            for name in server.qualified_disabled_tools()
        )

    def descriptions(self) -> dict[str, str]:
        """``{server: description}`` for enabled servers (blank when absent)."""
        return {s.name: s.description for s in self.enabled_servers}

    def transport_entries(self) -> dict[str, dict[str, Any]]:
        """Enabled servers as MCP client config entries, extras stripped."""
        return {s.name: s.transport_settings for s in self.enabled_servers}

    def transport_payload(self) -> dict[str, Any]:
        """The whole document reduced to what an MCP client library accepts."""
        return {**self.extras, SERVERS_KEY: self.transport_entries()}

    # ── Transitions ───────────────────────────────────────────────────────────

    def with_server(self, server: ServerDefinition) -> ServerCatalog:
        """Replace the entry of the same name, keeping catalog order."""
        if server.name not in self:
            raise ServerNotFound(server.name)
        servers = tuple(
            server if existing.name == server.name else existing
            for existing in self.servers
        )
        return ServerCatalog(servers, self.extras, self.malformed)

    def with_server_enabled(self, name: str, enabled: bool) -> ServerCatalog:
        return self.with_server(self.get(name).with_enabled(enabled))

    def with_tool_enabled(self, name: str, tool: str, enabled: bool) -> ServerCatalog:
        return self.with_server(self.get(name).with_tool_enabled(tool, enabled))
