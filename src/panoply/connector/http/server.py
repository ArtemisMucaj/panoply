"""The streamable-HTTP MCP host.

Serves ``/mcp`` from an *outer* server whose single provider points at an
inner proxy.  Swapping that inner proxy is what makes a config change take
effect instantly: connected sessions stay open, and a ``tools/list_changed``
notification tells clients to re-read the catalog.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

from panoply.connector.container import Container
from panoply.connector.http.api import start_api_thread
from panoply.domain.ports.proxy import ProxyOptions

log = logging.getLogger("panoply.http")

INNER_PROXY_NAME = "panoply-proxy"


async def broadcast_tools_changed(asgi_app) -> None:
    """Tell every live MCP session that the tool list moved under them."""
    from mcp.shared.message import SessionMessage
    from mcp.types import JSONRPCMessage, JSONRPCNotification

    session_manager = asgi_app.session_manager
    if session_manager is None:
        return
    notification = JSONRPCNotification(
        jsonrpc="2.0", method="notifications/tools/list_changed"
    )
    message = SessionMessage(message=JSONRPCMessage(notification))
    sends = [
        stream.send(message)
        for transport in list(session_manager._server_instances.values())
        if (stream := getattr(transport, "_write_stream", None)) is not None
    ]
    if sends:
        await asyncio.gather(*sends, return_exceptions=True)


def serve_http(container: Container, port: int, *, code_mode: bool = False) -> None:
    """Run the MCP endpoint on *port* and the management API on ``port + 1``."""
    import uvicorn
    from fastmcp.server import FastMCP
    from fastmcp.server.http import RequestContextMiddleware, StreamableHTTPASGIApp
    from fastmcp.server.providers.fastmcp_provider import FastMCPProvider
    from mcp.server.streamable_http_manager import StreamableHTTPSessionManager
    from starlette.applications import Starlette
    from starlette.middleware import Middleware
    from starlette.routing import Route

    # Skills are always mounted on the inner proxy; SkillsGateMiddleware hides
    # them from clients that didn't ask for them on the /mcp URL. One set of
    # backend subprocesses, per-connection opt-in.
    options = ProxyOptions(name=INNER_PROXY_NAME, skills=True, code_mode=code_mode)
    inner = container.proxy.build(options)

    log.info("Starting HTTP mode — MCP on :%d, API on :%d", port, port + 1)
    outer = FastMCP("panoply")
    provider = FastMCPProvider(inner.server)
    outer.add_provider(provider)

    asgi_app = StreamableHTTPASGIApp(None)
    session_tasks: list[asyncio.Task] = []

    async def launch_session_manager(app: StreamableHTTPASGIApp, mcp: FastMCP) -> None:
        """Start *mcp*'s session manager, wire it to *app*, wait until ready."""
        ready: asyncio.Future = asyncio.get_event_loop().create_future()

        async def run() -> None:
            session_manager = StreamableHTTPSessionManager(
                app=mcp._mcp_server, json_response=False, stateless=False
            )
            app.session_manager = session_manager
            async with mcp._lifespan_manager(), session_manager.run():
                if not ready.done():
                    ready.set_result(None)
                # Stay alive until the task is cancelled on shutdown.
                await asyncio.get_event_loop().create_future()

        session_tasks.append(asyncio.create_task(run()))
        await asyncio.shield(ready)

    @asynccontextmanager
    async def lifespan(app):
        await launch_session_manager(asgi_app, outer)
        try:
            yield
        finally:
            for task in session_tasks:
                task.cancel()
            if session_tasks:
                await asyncio.gather(*session_tasks, return_exceptions=True)

    parent_app = Starlette(
        routes=[Route("/mcp", endpoint=asgi_app, methods=["GET", "POST", "DELETE"])],
        middleware=[Middleware(RequestContextMiddleware)],
        lifespan=lifespan,
    )
    parent_app.state.transport_type = "streamable-http"

    async def run_http() -> None:
        loop = asyncio.get_event_loop()

        async def rebuild_proxy() -> None:
            """Re-read the active config and swap the inner proxy in.

            For anything that changes *which* backends are proxied.  Their
            subprocesses restart as a result — unavoidable when the server set
            changes.
            """
            try:
                rebuilt = container.proxy.build(options)
            except Exception as exc:
                log.error("Config reload failed: %s", exc)
                return
            provider.server = rebuilt.server
            log.info("Config reloaded")
            await broadcast_tools_changed(asgi_app)

        async def flip_tool(server: str, tool: str, enabled: bool) -> None:
            """Show or hide one tool on the live proxy, leaving backends alone."""
            qualified = f"{server}_{tool}"
            current = provider.server
            if enabled:
                current.enable(names={qualified})
            else:
                current.disable(names={qualified})
            await broadcast_tools_changed(asgi_app)

        # The API runs on its own thread, so its callbacks have to hop back
        # onto this loop before touching the running proxy.
        container.events.on_configuration_changed(
            lambda: asyncio.run_coroutine_threadsafe(rebuild_proxy(), loop)
        )
        container.events.on_tool_visibility_changed(
            lambda server, tool, enabled: asyncio.run_coroutine_threadsafe(
                flip_tool(server, tool, enabled), loop
            )
        )

        start_api_thread(container, port, port + 1)
        config = uvicorn.Config(
            parent_app,
            host="127.0.0.1",
            port=port,
            timeout_graceful_shutdown=2,
            lifespan="on",
            ws="websockets-sansio",
            log_config=None,
        )
        await uvicorn.Server(config).serve()

    asyncio.run(run_http())
