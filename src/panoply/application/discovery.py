"""Use cases for finding out what tools the backends offer."""

from __future__ import annotations

import asyncio
import logging
from pathlib import Path

from panoply.application.configuration import ConfigurationService
from panoply.domain.model.server import ServerDefinition
from panoply.domain.model.tool import ToolDescriptor
from panoply.domain.ports.discovery import ToolProbe

log = logging.getLogger("panoply.discovery")

DEFAULT_PROBE_TIMEOUT = 30.0

#: Exceptions that mean "this task or this process is going away". They are
#: re-raised rather than downgraded to an empty tool list: swallowing
#: ``CancelledError`` in particular would make a probe ignore its own
#: cancellation, so a disconnected client or a shutdown would wait out the full
#: timeout and the caller would still be handed a result.
PROPAGATE = (SystemExit, KeyboardInterrupt, GeneratorExit, asyncio.CancelledError)


class DiscoveryService:
    """Probes backends for their tool lists.

    The management UI needs the *real* per-server catalogue — asking the
    running proxy would only return the three synthetic tools it fronts.
    """

    def __init__(
        self,
        probe: ToolProbe,
        configuration: ConfigurationService,
        timeout: float = DEFAULT_PROBE_TIMEOUT,
    ) -> None:
        self.probe = probe
        self.configuration = configuration
        self.timeout = timeout

    async def inspect(self, server: ServerDefinition) -> list[ToolDescriptor]:
        """Probe one server, letting failures surface to the caller."""
        return await self.probe.probe(server)

    async def inspect_safely(self, server: ServerDefinition) -> list[ToolDescriptor]:
        """Probe one server; an unreachable or slow backend yields no tools.

        One broken server must never take down the whole listing, so every
        failure short of a shutdown signal is downgraded to an empty list.
        """
        try:
            return await asyncio.wait_for(self.inspect(server), timeout=self.timeout)
        except PROPAGATE:
            raise
        except asyncio.TimeoutError:
            log.warning("[%s] probe timed out after %.1fs", server.name, self.timeout)
            return []
        except BaseException as exc:
            log.warning("[%s] probe failed: %s: %s", server.name, type(exc).__name__, exc)
            return []

    async def catalogue(
        self, source: Path | None = None
    ) -> dict[str, list[ToolDescriptor]]:
        """Probe every enabled server in parallel."""
        servers = self.configuration.load_catalog(source).enabled_servers
        results = await asyncio.gather(*(self.inspect_safely(s) for s in servers))
        return {server.name: tools for server, tools in zip(servers, results)}
