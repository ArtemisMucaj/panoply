"""Unit tests for :class:`MCPConfigTranslator`."""

from __future__ import annotations

import pytest

from panoply.connector.mcp import translator as translator_module
from panoply.connector.mcp.translator import MCPConfigTranslator
from panoply.connector.settings import Settings
from panoply.domain.model.catalog import ServerCatalog
from panoply.domain.model.server import ServerDefinition


class FakeCredentialStore:
    backend = object()


class FakeOAuth:
    """Stands in for the real OAuth client so no network is touched."""

    instances: list[FakeOAuth] = []

    def __init__(self, **kwargs) -> None:
        self.kwargs = kwargs
        FakeOAuth.instances.append(self)


@pytest.fixture
def fake_oauth(monkeypatch: pytest.MonkeyPatch) -> type[FakeOAuth]:
    FakeOAuth.instances = []
    monkeypatch.setattr(translator_module, "OAuth", FakeOAuth)
    return FakeOAuth


@pytest.fixture
def translator(settings: Settings) -> MCPConfigTranslator:
    return MCPConfigTranslator(
        FakeCredentialStore(), settings, environment={"MY_TOKEN": "abc123"}
    )


class TestForCatalog:
    def test_includes_only_enabled_servers(self, translator) -> None:
        catalog = ServerCatalog.from_payload(
            {
                "mcpServers": {
                    "on": {"url": "http://on", "transport": "http"},
                    "off": {"url": "http://off", "transport": "http", "enabled": False},
                }
            }
        )
        config = translator.for_catalog(catalog)
        assert set(config.mcpServers) == {"on"}

    def test_expands_env_placeholders(self, translator) -> None:
        catalog = ServerCatalog.from_payload(
            {
                "mcpServers": {
                    "s": {
                        "command": "echo",
                        "args": ["hi"],
                        "env": {"TOKEN": "${MY_TOKEN}", "LITERAL": "plain"},
                    }
                }
            }
        )
        config = translator.for_catalog(catalog)
        assert config.mcpServers["s"].env == {"TOKEN": "abc123", "LITERAL": "plain"}

    def test_a_server_without_env_is_untouched(self, translator) -> None:
        catalog = ServerCatalog.from_payload(
            {"mcpServers": {"s": {"command": "echo", "args": []}}}
        )
        config = translator.for_catalog(catalog)
        assert not getattr(config.mcpServers["s"], "env", None)

    def test_panoply_only_keys_are_stripped_before_validation(
        self, translator
    ) -> None:
        """``enabled`` / ``disabledTools`` aren't MCP fields — they must not
        reach the schema, which is what makes this seam necessary at all."""
        catalog = ServerCatalog.from_payload(
            {
                "mcpServers": {
                    "s": {
                        "url": "http://s",
                        "transport": "http",
                        "enabled": True,
                        "disabledTools": ["noisy"],
                    }
                }
            }
        )
        server = translator.for_catalog(catalog).mcpServers["s"]
        assert not hasattr(server, "disabledTools")

    def test_oauth_servers_get_a_client_on_the_shared_port(
        self, translator, settings, fake_oauth
    ) -> None:
        catalog = ServerCatalog.from_payload(
            {
                "mcpServers": {
                    "o": {
                        "url": "https://o.example.com/mcp",
                        "transport": "http",
                        "auth": "oauth",
                    }
                }
            }
        )
        config = translator.for_catalog(catalog)
        client = config.mcpServers["o"].auth
        assert isinstance(client, fake_oauth)
        assert client.kwargs["callback_port"] == settings.oauth_callback_port
        assert client.kwargs["client_name"] == "Panoply Proxy"
        assert client.kwargs["token_storage"] is FakeCredentialStore.backend


class TestForServer:
    def test_builds_a_single_server_config(self, translator) -> None:
        server = ServerDefinition("solo", {"url": "http://s", "transport": "http"})
        assert set(translator.for_server(server).mcpServers) == {"solo"}

    def test_probing_uses_the_port_it_was_given(self, translator, fake_oauth) -> None:
        """Probing must not try to bind the port the running server owns."""
        server = ServerDefinition(
            "o", {"url": "http://o", "transport": "http", "auth": "oauth"}
        )
        translator.for_server(server, callback_port=55555)
        assert fake_oauth.instances[-1].kwargs["callback_port"] == 55555

    def test_falls_back_to_the_shared_port(
        self, translator, settings, fake_oauth
    ) -> None:
        server = ServerDefinition(
            "o", {"url": "http://o", "transport": "http", "auth": "oauth"}
        )
        translator.for_server(server)
        assert (
            fake_oauth.instances[-1].kwargs["callback_port"]
            == settings.oauth_callback_port
        )
