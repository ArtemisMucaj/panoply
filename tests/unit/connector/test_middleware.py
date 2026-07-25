"""Unit tests for :class:`AuthErrorMiddleware`.

Every branch is exercised through the public ``on_call_tool`` interface with
no real MCP server: ``call_next`` and the credentials service are doubles.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fastmcp.exceptions import ToolError

from panoply.connector.mcp.middleware import AuthErrorMiddleware
from panoply.domain.model.catalog import ServerCatalog
from panoply.domain.policies.authentication import ToolOwnership


def ownership(**servers: dict) -> ToolOwnership:
    return ToolOwnership.from_catalog(
        ServerCatalog.from_payload({"mcpServers": servers})
    )


class FakeCredentials:
    def __init__(self, refreshed: bool = True) -> None:
        self.refreshed = refreshed
        self.calls: list[str] = []

    async def refresh(self, server) -> bool:
        self.calls.append(server.name)
        return self.refreshed


def make_context(tool_name: str):
    return SimpleNamespace(message=SimpleNamespace(name=tool_name))


def make_call_next(error: str | None = None):
    async def call_next(ctx):
        if error is not None:
            raise ToolError(error)
        return "ok"

    return call_next


class TestPassthrough:
    async def test_success_returns_the_result(self) -> None:
        mw = AuthErrorMiddleware(ownership(gitlab={"auth": "oauth"}), FakeCredentials())
        assert await mw.on_call_tool(make_context("gitlab_list"), make_call_next()) == (
            "ok"
        )

    async def test_non_auth_error_propagates_unchanged(self) -> None:
        mw = AuthErrorMiddleware(ownership(gitlab={"auth": "oauth"}), FakeCredentials())
        with pytest.raises(ToolError, match="Connection refused"):
            await mw.on_call_tool(
                make_context("gitlab_list"), make_call_next("Connection refused")
            )

    async def test_auth_error_from_an_unknown_server_propagates_unchanged(self) -> None:
        mw = AuthErrorMiddleware(ownership(gitlab={"auth": "oauth"}), FakeCredentials())
        with pytest.raises(ToolError, match="^401 Unauthorized$"):
            await mw.on_call_tool(
                make_context("unknown_tool"), make_call_next("401 Unauthorized")
            )

    async def test_no_servers_configured_propagates_unchanged(self) -> None:
        mw = AuthErrorMiddleware(ownership(), FakeCredentials())
        with pytest.raises(ToolError, match="Unauthorized"):
            await mw.on_call_tool(
                make_context("any_tool"), make_call_next("401 Unauthorized")
            )

    async def test_non_auth_errors_never_reach_the_credentials_service(self) -> None:
        credentials = FakeCredentials()
        mw = AuthErrorMiddleware(ownership(gitlab={"auth": "oauth"}), credentials)
        with pytest.raises(ToolError):
            await mw.on_call_tool(
                make_context("gitlab_list"), make_call_next("404 Not Found")
            )
        assert credentials.calls == []


class TestOAuthRefresh:
    async def test_successful_refresh_hints_retry(self) -> None:
        mw = AuthErrorMiddleware(ownership(gitlab={"auth": "oauth"}), FakeCredentials())
        with pytest.raises(ToolError, match="has been refreshed") as caught:
            await mw.on_call_tool(
                make_context("gitlab_list"),
                make_call_next("GitLab API error: 401 Unauthorized"),
            )
        message = str(caught.value)
        assert "Please retry" in message
        # the original error is preserved for the agent to read
        assert "401 Unauthorized" in message

    async def test_failed_refresh_hints_reauthentication(self) -> None:
        mw = AuthErrorMiddleware(
            ownership(gitlab={"auth": "oauth"}), FakeCredentials(refreshed=False)
        )
        with pytest.raises(ToolError, match="could not be refreshed") as caught:
            await mw.on_call_tool(
                make_context("gitlab_list"), make_call_next("401 Unauthorized")
            )
        assert "re-authenticate" in str(caught.value)

    async def test_the_owning_server_is_the_one_refreshed(self) -> None:
        credentials = FakeCredentials()
        mw = AuthErrorMiddleware(
            ownership(git={"command": "git-mcp"}, gitlab={"auth": "oauth"}), credentials
        )
        with pytest.raises(ToolError):
            await mw.on_call_tool(
                make_context("gitlab_create_issue"), make_call_next("401 Unauthorized")
            )
        assert credentials.calls == ["gitlab"]


class TestNonOAuthServer:
    async def test_hints_at_the_token_configuration(self) -> None:
        mw = AuthErrorMiddleware(
            ownership(gitlab={"command": "gitlab-mcp"}), FakeCredentials()
        )
        with pytest.raises(ToolError, match="token configuration") as caught:
            await mw.on_call_tool(
                make_context("gitlab_list"), make_call_next("error: 401 Unauthorized")
            )
        assert "GITLAB_TOKEN" in str(caught.value)
        assert "401 Unauthorized" in str(caught.value)

    async def test_no_refresh_is_attempted(self) -> None:
        credentials = FakeCredentials()
        mw = AuthErrorMiddleware(ownership(git={"command": "git-mcp"}), credentials)
        with pytest.raises(ToolError):
            await mw.on_call_tool(
                make_context("git_push"), make_call_next("401 Unauthorized")
            )
        assert credentials.calls == []


class TestPrefixMatching:
    """Longest-name-first, observed through which hint comes back."""

    async def test_longest_prefix_wins(self) -> None:
        mw = AuthErrorMiddleware(
            ownership(git={"command": "git-mcp"}, gitlab={"auth": "oauth"}),
            FakeCredentials(refreshed=False),
        )
        with pytest.raises(ToolError, match="re-authenticate"):
            await mw.on_call_tool(
                make_context("gitlab_create_issue"), make_call_next("401 Unauthorized")
            )

    async def test_short_prefix_still_matches(self) -> None:
        mw = AuthErrorMiddleware(
            ownership(git={"command": "git-mcp"}, gitlab={"auth": "oauth"}),
            FakeCredentials(),
        )
        with pytest.raises(ToolError, match="token configuration"):
            await mw.on_call_tool(
                make_context("git_push"), make_call_next("401 Unauthorized")
            )
