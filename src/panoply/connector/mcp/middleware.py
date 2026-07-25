"""FastMCP middleware enforcing Panoply's domain policies.

``AuthErrorMiddleware`` catches the 401s that arrive *inside* a successful MCP
response — the transport returned HTTP 200, so the client's own OAuth handler
never sees them — and turns them into a silent token refresh plus a retry
hint.  On retry the connection is rebuilt from scratch, so the freshly stored
token is picked up without restarting the proxy.

``SkillsGateMiddleware`` hides skill tools and resources from clients that
didn't opt in.
"""

from __future__ import annotations

import logging
from collections.abc import Sequence

import mcp.types as mt
from fastmcp.exceptions import ResourceError, ToolError
from fastmcp.resources.base import Resource, ResourceResult
from fastmcp.server.dependencies import get_http_request
from fastmcp.server.middleware import Middleware, MiddlewareContext
from fastmcp.tools.base import Tool, ToolResult

from panoply.application.credentials import CredentialsService
from panoply.domain.policies.authentication import (
    Remedy,
    ToolOwnership,
    is_authentication_failure,
)
from panoply.domain.policies.skills import (
    SKILL_TOOL_NAMES,
    is_skill_resource,
    is_skill_tool,
    wants_skills,
)

log = logging.getLogger("panoply.middleware")

REMEDY_HINTS = {
    Remedy.RETRY: (
        "The OAuth token for '{server}' has been refreshed. Please retry your request."
    ),
    Remedy.REAUTHENTICATE: (
        "Authentication failed for '{server}' and the token could not be refreshed "
        "automatically. The refresh token may have expired — please re-authenticate "
        "through your OAuth provider."
    ),
    Remedy.CHECK_CREDENTIALS: (
        "Authentication failed for '{server}'. Check the token configuration for "
        "this server (e.g. the GITLAB_TOKEN environment variable)."
    ),
}


class AuthErrorMiddleware(Middleware):
    """Repairs expired OAuth credentials in the middle of a tool call."""

    def __init__(
        self, ownership: ToolOwnership, credentials: CredentialsService
    ) -> None:
        self.ownership = ownership
        self.credentials = credentials

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next,
    ) -> ToolResult:
        try:
            return await call_next(context)
        except ToolError as exc:
            error_text = str(exc)
            if not is_authentication_failure(error_text):
                raise

            server = self.ownership.owner_of(context.message.name)
            if server is None:
                raise

            if server.uses_oauth:
                log.info(
                    "Auth error on '%s', attempting OAuth token refresh", server.name
                )
                refreshed = await self.credentials.refresh(server)
                if refreshed:
                    log.info("OAuth token refreshed for '%s'", server.name)
                remedy = Remedy.RETRY if refreshed else Remedy.REAUTHENTICATE
            else:
                log.warning("Auth error on non-OAuth server '%s'", server.name)
                remedy = Remedy.CHECK_CREDENTIALS

            hint = REMEDY_HINTS[remedy].format(server=server.name)
            raise ToolError(f"{error_text}\n\n{hint}") from exc


def http_request_wants_skills() -> bool:
    """True when the active HTTP request opted into skills via ``?skills=true``.

    Returns True when there is no HTTP request at all (stdio mode), so the
    middleware is a no-op outside HTTP — stdio never mounts skills anyway.
    """
    try:
        request = get_http_request()
    except RuntimeError:
        return True
    return wants_skills(request.query_params.get("skills"))


class SkillsGateMiddleware(Middleware):
    """Hide skill tools / resources from clients that don't pass ``?skills=true``.

    Skills are mounted on the inner proxy unconditionally so we can keep a
    single set of backend subprocesses, but most MCP clients have native
    skills support and don't want them re-exposed via tools.  Clients that DO
    need them opt in by hitting ``http://HOST:PORT/mcp?skills=true``.
    """

    async def on_list_tools(
        self,
        context: MiddlewareContext[mt.ListToolsRequest],
        call_next,
    ) -> Sequence[Tool]:
        tools = await call_next(context)
        if http_request_wants_skills():
            return tools
        return [tool for tool in tools if not is_skill_tool(tool.name)]

    async def on_list_resources(
        self,
        context: MiddlewareContext[mt.ListResourcesRequest],
        call_next,
    ) -> Sequence[Resource]:
        resources = await call_next(context)
        if http_request_wants_skills():
            return resources
        return [r for r in resources if not is_skill_resource(str(r.uri))]

    async def on_call_tool(
        self,
        context: MiddlewareContext[mt.CallToolRequestParams],
        call_next,
    ) -> ToolResult:
        name = context.message.name
        if name in SKILL_TOOL_NAMES and not http_request_wants_skills():
            raise ToolError(f"Tool '{name}' requires ?skills=true on the /mcp URL.")
        return await call_next(context)

    async def on_read_resource(
        self,
        context: MiddlewareContext[mt.ReadResourceRequestParams],
        call_next,
    ) -> ResourceResult:
        uri = str(context.message.uri)
        if is_skill_resource(uri) and not http_request_wants_skills():
            raise ResourceError(f"Resource '{uri}' requires ?skills=true on the /mcp URL.")
        return await call_next(context)
