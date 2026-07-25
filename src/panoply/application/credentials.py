"""Use cases over cached OAuth credentials."""

from __future__ import annotations

import asyncio
import logging

from panoply.domain.model.server import ServerDefinition
from panoply.domain.model.tool import ToolDescriptor
from panoply.domain.ports.credentials import CredentialStore
from panoply.domain.ports.discovery import ToolProbe

log = logging.getLogger("panoply.credentials")

#: A silent refresh (exchanging a refresh token) is a single round-trip.  If it
#: takes longer than this the client is almost certainly waiting on a browser
#: flow, which we must not block a tool call on.
DEFAULT_REFRESH_TIMEOUT = 5.0


class CredentialsService:
    """Authenticates against proxied servers and reports what is cached.

    Both operations are expressed as a probe: opening a fresh connection is
    what makes the MCP client exercise its OAuth handler, which then writes
    any newly-obtained token back to the shared store.
    """

    def __init__(
        self,
        store: CredentialStore,
        probe: ToolProbe,
        refresh_timeout: float = DEFAULT_REFRESH_TIMEOUT,
    ) -> None:
        self.store = store
        self.probe = probe
        self.refresh_timeout = refresh_timeout

    def forget_all(self) -> None:
        """Wipe every cached token."""
        self.store.clear()
        log.info("Cleared all cached OAuth tokens")

    def cached_token_count(self, server: ServerDefinition) -> int:
        """How many cache entries belong to *server*, keyed by its URL."""
        url = server.url
        if not url:
            return 0
        return sum(1 for key in self.store.keys() if url in key)

    async def authenticate(self, server: ServerDefinition) -> list[ToolDescriptor]:
        """Run the full login flow, opening a browser if one is needed."""
        return await self.probe.probe(server)

    async def refresh(self, server: ServerDefinition) -> bool:
        """Try to renew *server*'s access token without user interaction.

        Returns False when the refresh token is gone too — the flow would need
        a browser, and the caller should tell the user to re-authenticate.
        """
        try:
            await asyncio.wait_for(
                self.probe.probe(server), timeout=self.refresh_timeout
            )
            return True
        except asyncio.TimeoutError:
            log.info("OAuth refresh for '%s' timed out", server.name)
            return False
        except Exception as exc:
            log.info("OAuth refresh for '%s' failed: %s", server.name, exc)
            return False
