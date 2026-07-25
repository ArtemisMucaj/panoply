"""Turns a :class:`ServerCatalog` into the config FastMCP wants.

This is the seam between the domain's view of a backend (a name and a settings
mapping) and FastMCP's ``MCPConfig``: OAuth clients are attached here, and
``${VAR}`` placeholders in ``env`` are resolved against the real environment.
"""

from __future__ import annotations

import os
from collections.abc import Mapping

from fastmcp.client.auth import OAuth
from fastmcp.mcp_config import MCPConfig

from panoply.connector.persistence.credential_store import DiskCredentialStore
from panoply.connector.settings import Settings
from panoply.domain.model.catalog import ServerCatalog
from panoply.domain.model.environment import expand_mapping
from panoply.domain.model.server import OAUTH, ServerDefinition


class MCPConfigTranslator:
    """Builds validated ``MCPConfig`` objects with credentials wired in."""

    def __init__(
        self,
        credentials: DiskCredentialStore,
        settings: Settings,
        environment: Mapping[str, str] | None = None,
    ) -> None:
        self.credentials = credentials
        self.settings = settings
        self.environment = os.environ if environment is None else environment

    def for_catalog(self, catalog: ServerCatalog) -> MCPConfig:
        """Every enabled server in *catalog*, ready to proxy."""
        return self._configure(
            MCPConfig.model_validate(catalog.transport_payload()),
            callback_port=self.settings.oauth_callback_port,
        )

    def for_server(
        self, server: ServerDefinition, *, callback_port: int | None = None
    ) -> MCPConfig:
        """A single server on its own — used for probing and logins.

        *callback_port* overrides the shared OAuth callback port: probing must
        not try to bind the port the long-running server already owns.
        """
        payload = {"mcpServers": {server.name: server.transport_settings}}
        return self._configure(
            MCPConfig.model_validate(payload),
            callback_port=callback_port or self.settings.oauth_callback_port,
        )

    def _configure(self, config: MCPConfig, *, callback_port: int) -> MCPConfig:
        for server in config.mcpServers.values():
            if getattr(server, "auth", None) == OAUTH:
                server.auth = OAuth(
                    token_storage=self.credentials.backend,
                    callback_port=callback_port,
                    client_name=self.settings.oauth_client_name,
                )
            env = getattr(server, "env", None)
            if env:
                server.env = expand_mapping(env, self.environment)
        return config
