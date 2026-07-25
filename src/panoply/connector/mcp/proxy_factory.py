"""FastMCP implementation of :class:`ProxyFactory`.

Replaces ``fastmcp.server.create_proxy(MCPConfig)`` with a builder that picks
the right client per transport and then layers Panoply's own behaviour on top:
disabled tools, auth repair, the skills gate, and the search transform.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field

from fastmcp.experimental.transforms.code_mode import CodeMode
from fastmcp.mcp_config import MCPConfig, StdioMCPServer
from fastmcp.server import FastMCP
from fastmcp.server.providers.proxy import (
    ProxyClient,
    ProxyProvider,
    StatefulProxyClient,
)

from panoply.application.credentials import CredentialsService
from panoply.connector.mcp.middleware import AuthErrorMiddleware, SkillsGateMiddleware
from panoply.connector.mcp.search_transform import PanoplySearchTransform
from panoply.connector.mcp.skills import mount_skills
from panoply.connector.mcp.translator import MCPConfigTranslator
from panoply.connector.settings import Settings
from panoply.domain.model.catalog import ServerCatalog
from panoply.domain.policies.authentication import ToolOwnership
from panoply.domain.ports.proxy import ProxyOptions

log = logging.getLogger("panoply.proxy")


@dataclass
class FastMCPProxyServer:
    """A built FastMCP proxy, plus the handles Panoply needs on it.

    ``clients`` keeps the stateful proxy clients alive: ``new_stateful`` reads
    caches off the client instance, so letting them be garbage-collected would
    silently break every stdio backend.
    """

    server: FastMCP
    clients: list[StatefulProxyClient] = field(default_factory=list)

    def enable_tool(self, qualified_name: str) -> None:
        self.server.enable(names={qualified_name})

    def disable_tool(self, qualified_name: str) -> None:
        self.server.disable(names={qualified_name})


class FastMCPProxyFactory:
    """Assembles the proxy the agent talks to."""

    def __init__(
        self,
        translator: MCPConfigTranslator,
        credentials: CredentialsService,
        settings: Settings,
    ) -> None:
        self.translator = translator
        self.credentials = credentials
        self.settings = settings

    def create(
        self, catalog: ServerCatalog, options: ProxyOptions
    ) -> FastMCPProxyServer:
        config = self.translator.for_catalog(catalog)
        proxy = self._build_proxy(config, options.name)

        skill_dirs = self.settings.existing_skill_dirs() if options.skills else []
        if skill_dirs:
            mount_skills(proxy.server, skill_dirs)

        disabled = catalog.disabled_tool_names()
        if disabled:
            log.info("Disabled tools: %s", ", ".join(sorted(disabled)))
            proxy.server.disable(names=set(disabled))

        proxy.server.add_middleware(
            AuthErrorMiddleware(ToolOwnership.from_catalog(catalog), self.credentials)
        )
        if skill_dirs:
            proxy.server.add_middleware(SkillsGateMiddleware())

        descriptions = catalog.descriptions()
        described = sorted(name for name, text in descriptions.items() if text)
        if described:
            log.info("Server descriptions loaded for: %s", ", ".join(described))

        proxy.server.add_transform(
            CodeMode()
            if options.code_mode
            else PanoplySearchTransform(
                max_results=self.settings.search_results,
                always_visible=["list_resources", "read_resource"] if skill_dirs else None,
                server_descriptions=descriptions,
            )
        )
        return proxy

    # ── Transport selection ───────────────────────────────────────────────────

    def _build_proxy(self, config: MCPConfig, name: str) -> FastMCPProxyServer:
        """One provider per backend, namespaced by server name.

        stdio backends get a ``StatefulProxyClient`` so the subprocess lives
        for the whole frontend session instead of being respawned on every
        tool call; HTTP/SSE backends get a fresh connection per request, which
        is what statelessness over HTTP actually means.
        """
        server: FastMCP = FastMCP(name=name)
        proxy = FastMCPProxyServer(server)

        for server_name, backend in config.mcpServers.items():
            transport = backend.to_transport()
            timeout = self.settings.backend_init_timeout

            if isinstance(backend, StdioMCPServer):
                log.info(
                    "Backend %-20s  stdio  (stateful, timeout=%ss)", server_name, timeout
                )
                client = StatefulProxyClient(transport, init_timeout=timeout)
                proxy.clients.append(client)
                factory = client.new_stateful
            else:
                log.info(
                    "Backend %-20s  http   %s (timeout=%ss)",
                    server_name,
                    getattr(backend, "url", "?"),
                    timeout,
                )
                factory = ProxyClient(transport, init_timeout=timeout).new

            server.add_provider(ProxyProvider(factory), namespace=server_name)

        return proxy
