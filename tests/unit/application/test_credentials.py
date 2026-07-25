"""Unit tests for :class:`CredentialsService`."""

from __future__ import annotations

import asyncio

from panoply.application.credentials import CredentialsService
from panoply.domain.model.server import ServerDefinition
from panoply.domain.model.tool import ToolDescriptor

from .conftest import ScriptedProbe

OAUTH_SERVER = ServerDefinition(
    "atlassian", {"url": "https://atlassian.example.com/mcp", "auth": "oauth"}
)


class FakeStore:
    def __init__(self, keys: list[str] | None = None) -> None:
        self._keys = list(keys or [])
        self.cleared = False

    def keys(self) -> list[str]:
        return list(self._keys)

    def clear(self) -> None:
        self.cleared = True
        self._keys.clear()


class TestTokenCounts:
    def test_counts_keys_matching_the_server_url(self) -> None:
        store = FakeStore(["https://atlassian.example.com/mcp|token|abc"])
        service = CredentialsService(store, ScriptedProbe())
        assert service.cached_token_count(OAUTH_SERVER) == 1

    def test_unrelated_keys_do_not_count(self) -> None:
        store = FakeStore(["https://other.example.com/mcp|token|abc"])
        service = CredentialsService(store, ScriptedProbe())
        assert service.cached_token_count(OAUTH_SERVER) == 0

    def test_a_server_without_a_url_counts_nothing(self) -> None:
        store = FakeStore(["anything"])
        service = CredentialsService(store, ScriptedProbe())
        stdio = ServerDefinition("local", {"command": "echo"})
        assert service.cached_token_count(stdio) == 0

    def test_forget_all_clears_the_store(self) -> None:
        store = FakeStore(["a"])
        CredentialsService(store, ScriptedProbe()).forget_all()
        assert store.cleared


class TestRefresh:
    async def test_successful_probe_means_refreshed(self) -> None:
        probe = ScriptedProbe({"atlassian": ["t"]})
        service = CredentialsService(FakeStore(), probe)
        assert await service.refresh(OAUTH_SERVER) is True

    async def test_failing_probe_means_not_refreshed(self) -> None:
        probe = ScriptedProbe({"atlassian": RuntimeError("denied")})
        service = CredentialsService(FakeStore(), probe)
        assert await service.refresh(OAUTH_SERVER) is False

    async def test_a_hanging_probe_is_a_browser_flow_not_a_refresh(self) -> None:
        """Waiting means the refresh token is gone and a browser is needed."""

        async def hang() -> list[ToolDescriptor]:
            await asyncio.sleep(10)
            return []

        probe = ScriptedProbe({"atlassian": hang})
        service = CredentialsService(FakeStore(), probe, refresh_timeout=0.05)
        assert await service.refresh(OAUTH_SERVER) is False


class TestAuthenticate:
    async def test_returns_the_probed_tools(self) -> None:
        probe = ScriptedProbe({"atlassian": ["t1", "t2"]})
        service = CredentialsService(FakeStore(), probe)
        assert await service.authenticate(OAUTH_SERVER) == [
            ToolDescriptor("t1"),
            ToolDescriptor("t2"),
        ]
