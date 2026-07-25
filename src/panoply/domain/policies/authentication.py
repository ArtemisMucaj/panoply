"""Deciding what an authentication failure from a backend means.

A proxied server can answer a tool call with an in-band 401 — the MCP
transport itself returns HTTP 200, so the client's OAuth handler never sees
it.  These rules turn such an error into an intent the connector can act on.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from panoply.domain.model.catalog import ServerCatalog
from panoply.domain.model.server import ServerDefinition

AUTH_MARKERS = ("401", "unauthorized")


def is_authentication_failure(text: str) -> bool:
    """True when an error message looks like a credentials problem."""
    lowered = text.lower()
    return any(marker in lowered for marker in AUTH_MARKERS)


class Remedy(Enum):
    """What the caller should be told to do about a failed tool call."""

    #: The token was refreshed silently — retrying should now succeed.
    RETRY = "retry"
    #: The refresh token is gone too; a full re-authentication is needed.
    REAUTHENTICATE = "reauthenticate"
    #: The server authenticates some other way (env token, header, …).
    CHECK_CREDENTIALS = "check_credentials"


@dataclass(frozen=True)
class ToolOwnership:
    """Maps a qualified tool name back to the server that contributed it.

    Servers are matched longest-name-first so ``gitlab_create_issue`` resolves
    to ``gitlab`` and not to a shorter ``git`` that happens to share a prefix.
    """

    servers: tuple[ServerDefinition, ...] = ()

    @classmethod
    def from_catalog(cls, catalog: ServerCatalog) -> ToolOwnership:
        """Index the enabled servers — only they contribute tools to match."""
        return cls(
            tuple(
                sorted(catalog.enabled_servers, key=lambda s: len(s.name), reverse=True)
            )
        )

    def owner_of(self, qualified_tool: str) -> ServerDefinition | None:
        return next((s for s in self.servers if s.owns(qualified_tool)), None)
