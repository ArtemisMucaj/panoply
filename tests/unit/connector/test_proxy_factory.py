"""Unit tests for :class:`FastMCPProxyFactory`."""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest
from fastmcp.server import FastMCP

from panoply.connector.mcp import proxy_factory as factory_module
from panoply.connector.mcp.proxy_factory import FastMCPProxyFactory
from panoply.connector.mcp.search_transform import PanoplySearchTransform
from panoply.connector.settings import Settings
from panoply.domain.model.catalog import ServerCatalog
from panoply.domain.ports.proxy import ProxyOptions

CATALOG = ServerCatalog.from_payload(
    {
        "mcpServers": {
            "gl": {"command": "npx", "args": ["-y", "some-mcp"], "description": "Git"},
            "remote": {"url": "https://remote.example.com/mcp", "transport": "http"},
            "off": {"url": "https://off.example.com/mcp", "enabled": False},
        }
    }
)


class StubTranslator:
    """Translates without touching credentials or the environment."""

    def for_catalog(self, catalog: ServerCatalog):
        from fastmcp.mcp_config import MCPConfig

        return MCPConfig.model_validate(catalog.transport_payload())


@pytest.fixture
def factory(settings: Settings) -> FastMCPProxyFactory:
    return FastMCPProxyFactory(StubTranslator(), MagicMock(), settings)


@pytest.fixture
def stub_clients():
    """Keep real proxy clients from spawning subprocesses or opening sockets."""
    with (
        patch.object(factory_module, "StatefulProxyClient") as stateful,
        patch.object(factory_module, "ProxyClient") as plain,
    ):
        yield stateful, plain


class TestTransportSelection:
    def test_returns_a_fastmcp_server(self, factory, stub_clients) -> None:
        built = factory.create(CATALOG, ProxyOptions(name="test"))
        assert isinstance(built.server, FastMCP)

    def test_stdio_backends_get_a_stateful_client(self, factory, stub_clients) -> None:
        stateful, plain = stub_clients
        factory.create(CATALOG, ProxyOptions(name="test"))
        assert stateful.call_count == 1
        assert plain.call_count == 1

    def test_disabled_servers_are_not_connected(self, factory, stub_clients) -> None:
        stateful, plain = stub_clients
        factory.create(CATALOG, ProxyOptions(name="test"))
        assert stateful.call_count + plain.call_count == 2

    def test_backends_get_an_init_timeout(self, factory, stub_clients, settings) -> None:
        """An unreachable backend must fail fast, not hang tools/list."""
        stateful, plain = stub_clients
        factory.create(CATALOG, ProxyOptions(name="test"))
        assert (
            stateful.call_args.kwargs["init_timeout"] == settings.backend_init_timeout
        )
        assert plain.call_args.kwargs["init_timeout"] == settings.backend_init_timeout

    def test_stateful_clients_are_kept_alive(self, factory, stub_clients) -> None:
        """``new_stateful`` reads caches off the client — dropping the last
        reference would silently break every stdio backend."""
        built = factory.create(CATALOG, ProxyOptions(name="test"))
        assert len(built.clients) == 1

    def test_each_transport_gets_its_own_factory_callable(
        self, factory, stub_clients
    ) -> None:
        """stdio → a session-lived subprocess; http → a fresh connection."""
        from fastmcp.server.providers.proxy import ProxyProvider

        stateful, plain = stub_clients
        captured: list = []
        real_init = ProxyProvider.__init__

        def capturing_init(self, client_factory, **kwargs):
            captured.append(client_factory)
            real_init(self, client_factory, **kwargs)

        with patch.object(ProxyProvider, "__init__", capturing_init):
            factory.create(CATALOG, ProxyOptions(name="test"))

        # Catalog order: the stdio backend "gl", then the http backend "remote".
        stdio_factory, http_factory = captured
        assert stdio_factory == stateful.return_value.new_stateful
        # The http factory is wrapped to mirror the front connection's protocol
        # era, so it is not ``new`` itself -- but calling it must still go
        # through ``new``, i.e. a fresh connection per request.
        plain.return_value.new.assert_not_called()
        http_factory()
        plain.return_value.new.assert_called_once()

    def test_http_factory_mirrors_the_front_connection_era(
        self, factory, stub_clients, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A backend client with no ``mode`` omits the required ``_meta`` envelope.

        fastmcp 4 negotiates a protocol era per request; an HTTP backend answers
        400 to every ``list_tools`` when the proxy's client never picked one, so
        the whole backend silently vanishes from search. Regression test.
        """
        from fastmcp.server.providers.proxy import ProxyProvider

        monkeypatch.setattr(
            factory_module, "_mirror_front_era_mode", lambda: "2025-06-18"
        )

        captured: list = []
        real_init = ProxyProvider.__init__

        def capturing_init(self, client_factory, **kwargs):
            captured.append(client_factory)
            real_init(self, client_factory, **kwargs)

        with patch.object(ProxyProvider, "__init__", capturing_init):
            factory.create(CATALOG, ProxyOptions(name="test"))

        fresh = captured[1]()
        assert fresh.mode == "2025-06-18"

    def test_one_namespaced_provider_per_backend(self, factory, stub_clients) -> None:
        namespaces = []
        real_add = FastMCP.add_provider

        def capturing_add(self, provider, *, namespace=""):
            namespaces.append(namespace)
            real_add(self, provider, namespace=namespace)

        with patch.object(FastMCP, "add_provider", capturing_add):
            factory.create(CATALOG, ProxyOptions(name="test"))

        # FastMCP.__init__ adds its own local provider under the empty namespace.
        assert set(ns for ns in namespaces if ns) == {"gl", "remote"}


class TestAssembly:
    def test_disabled_tools_are_hidden_at_build_time(
        self, factory, stub_clients
    ) -> None:
        catalog = ServerCatalog.from_payload(
            {"mcpServers": {"gl": {"command": "npx", "disabledTools": ["noisy"]}}}
        )
        disabled: list = []
        with patch.object(
            FastMCP, "disable", lambda self, names: disabled.append(names)
        ):
            factory.create(catalog, ProxyOptions(name="test"))
        assert disabled == [{"gl_noisy"}]

    def test_a_live_proxy_can_flip_one_tool(self, factory, stub_clients) -> None:
        built = factory.create(CATALOG, ProxyOptions(name="test"))
        with patch.object(built.server, "enable") as enable:
            built.enable_tool("gl_noisy")
        enable.assert_called_once_with(names={"gl_noisy"})

    def test_search_transform_carries_the_server_descriptions(
        self, factory, stub_clients
    ) -> None:
        transforms = []
        with patch.object(
            FastMCP, "add_transform", lambda self, t: transforms.append(t)
        ):
            factory.create(CATALOG, ProxyOptions(name="test"))
        transform = transforms[-1]
        assert isinstance(transform, PanoplySearchTransform)
        assert transform._server_descriptions == {"gl": "Git", "remote": ""}

    def test_code_mode_replaces_the_search_transform(
        self, factory, stub_clients
    ) -> None:
        from fastmcp.experimental.transforms.code_mode import CodeMode

        transforms = []
        with patch.object(
            FastMCP, "add_transform", lambda self, t: transforms.append(t)
        ):
            factory.create(CATALOG, ProxyOptions(name="test", code_mode=True))
        assert isinstance(transforms[-1], CodeMode)

    def test_auth_middleware_is_installed(self, factory, stub_clients) -> None:
        from panoply.connector.mcp.middleware import AuthErrorMiddleware

        middlewares = []
        with patch.object(
            FastMCP, "add_middleware", lambda self, m: middlewares.append(m)
        ):
            factory.create(CATALOG, ProxyOptions(name="test"))
        assert any(isinstance(m, AuthErrorMiddleware) for m in middlewares)

    def test_no_skills_directories_means_no_skills_gate(
        self, factory, stub_clients
    ) -> None:
        """``settings.skill_dirs`` is empty in tests, so nothing to gate."""
        from panoply.connector.mcp.middleware import SkillsGateMiddleware

        middlewares = []
        with patch.object(
            FastMCP, "add_middleware", lambda self, m: middlewares.append(m)
        ):
            factory.create(CATALOG, ProxyOptions(name="test", skills=True))
        assert not any(isinstance(m, SkillsGateMiddleware) for m in middlewares)


def test_zstandard_decoder_available() -> None:
    """httpx must be able to decode zstd responses from backends."""
    try:
        from httpx._decoders import SUPPORTED_DECODERS
    except ImportError:
        return
    assert "zstd" in SUPPORTED_DECODERS
