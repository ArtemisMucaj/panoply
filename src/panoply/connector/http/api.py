"""REST management API.

Runs alongside the MCP endpoint (on ``port + 1``) and is what the desktop app
and the TUIs drive.  Handlers do nothing but translate HTTP to a use case and
back — every rule they appear to enforce lives in the domain.
"""

from __future__ import annotations

import threading
from functools import wraps
from pathlib import Path
from typing import Any, Callable

from starlette.applications import Starlette
from starlette.exceptions import HTTPException
from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from panoply.connector.container import Container
from panoply.domain.errors import NotFound

Handler = Callable[[Request], Any]


async def json_error(request: Request, exc: HTTPException) -> JSONResponse:
    """Render Starlette's own errors (404, 405, …) in the same shape as ours.

    Every response this API can produce is then JSON with the same error key,
    so an integrator never has to sniff the content type.
    """
    return JSONResponse({"error": exc.detail}, status_code=exc.status_code)


def endpoint(handler: Handler) -> Handler:
    """Map errors onto status codes.

    Unknown aggregates are 404, anything the caller could have sent correctly
    is a 400 raised as an ``HTTPException``, and whatever is left is ours: 500.
    """

    @wraps(handler)
    async def wrapper(request: Request) -> JSONResponse:
        try:
            return await handler(request)
        except HTTPException:
            raise  # already carries its status; rendered by json_error
        except NotFound as exc:
            return JSONResponse({"error": str(exc)}, status_code=404)
        except Exception as exc:
            return JSONResponse({"error": str(exc)}, status_code=500)

    return wrapper


async def json_object_body(request: Request) -> dict[str, Any]:
    """Parse the request body, or fail with a 400 the caller can act on."""
    try:
        body = await request.json()
    except Exception as exc:
        raise HTTPException(
            status_code=400, detail="request body must be valid JSON"
        ) from exc
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="request body must be a JSON object")
    return body


def required(body: dict[str, Any], field: str) -> Any:
    if field not in body:
        raise HTTPException(
            status_code=400, detail=f"missing required field '{field}'"
        )
    return body[field]


def create_api_app(container: Container, mcp_port: int) -> Starlette:
    """Build the management API.

    Endpoints
    ---------
    GET  /api/health                       → server status
    GET  /api/tools[?config=PATH]          → probe servers, return tool catalogue
    GET  /api/config[?path=PATH]           → read the configuration document
    PUT  /api/config[?path=PATH]           → overwrite it
    POST /api/servers/{name}/toggle        → body {enabled: bool}
    POST /api/tools/toggle                 → body {server, tool, enabled: bool}
    GET  /api/presets                      → list presets + active
    POST /api/presets                      → create preset
    PATCH/DELETE /api/presets/{id}         → update / remove
    POST /api/presets/{id}/activate        → switch active preset
    POST /api/presets/default/activate     → revert to default
    """
    configuration = container.configuration
    presets = container.preset_service
    discovery = container.discovery
    data_dir = container.settings.data_dir

    def resolve_source(request: Request, param: str = "config") -> Path:
        """Honour an explicit ``?path=`` only inside the data directory.

        Without the containment check this endpoint would read and overwrite
        any JSON file on the machine.
        """
        override = request.query_params.get(param)
        if not override:
            return configuration.active_source()
        try:
            resolved = Path(override).resolve()
            if resolved.parent == data_dir and resolved.suffix == ".json":
                return resolved
        except Exception:
            pass
        raise HTTPException(
            status_code=400,
            detail=f"'{param}' must be a .json file directly inside {data_dir}",
        )

    # ── Status & discovery ────────────────────────────────────────────────────

    async def health(request: Request) -> JSONResponse:
        return JSONResponse(
            {"status": "ok", "mcp_port": mcp_port, "api_port": mcp_port + 1}
        )

    @endpoint
    async def get_tools(request: Request) -> JSONResponse:
        source = resolve_source(request)
        catalogue = await discovery.catalogue(source)
        return JSONResponse(
            {
                name: [tool.to_payload() for tool in tools]
                for name, tools in catalogue.items()
            }
        )

    # ── Configuration ─────────────────────────────────────────────────────────

    @endpoint
    async def config_endpoint(request: Request) -> JSONResponse:
        source = resolve_source(request, param="path")
        if request.method == "GET":
            return JSONResponse(configuration.read_document(source))
        await configuration.replace_document(await json_object_body(request), source)
        return JSONResponse({"status": "ok"})

    @endpoint
    async def toggle_server(request: Request) -> JSONResponse:
        source = resolve_source(request, param="path")
        enabled = (await json_object_body(request)).get("enabled", True)
        await configuration.set_server_enabled(
            request.path_params["name"], enabled, source
        )
        return JSONResponse({"status": "ok"})

    @endpoint
    async def toggle_tool(request: Request) -> JSONResponse:
        source = resolve_source(request, param="path")
        body = await json_object_body(request)
        await configuration.set_tool_enabled(
            required(body, "server"),
            required(body, "tool"),
            body.get("enabled", True),
            source,
        )
        return JSONResponse({"status": "ok"})

    # ── Presets ───────────────────────────────────────────────────────────────

    @endpoint
    async def list_presets(request: Request) -> JSONResponse:
        book = presets.book()
        return JSONResponse(
            {
                **book.to_payload(),
                "activeConfigPath": str(configuration.active_source()),
            }
        )

    @endpoint
    async def create_preset(request: Request) -> JSONResponse:
        body = await json_object_body(request)
        preset = presets.create(required(body, "name"), required(body, "filePath"))
        return JSONResponse({"preset": preset.to_payload()}, status_code=201)

    @endpoint
    async def update_preset(request: Request) -> JSONResponse:
        body = await json_object_body(request)
        preset = presets.update(
            request.path_params["id"],
            name=body.get("name"),
            file_path=body.get("filePath"),
        )
        return JSONResponse({"preset": preset.to_payload()})

    @endpoint
    async def delete_preset(request: Request) -> JSONResponse:
        presets.delete(request.path_params["id"])
        return JSONResponse({"status": "ok"})

    @endpoint
    async def activate_preset(request: Request) -> JSONResponse:
        preset_id = request.path_params.get("id")
        active = presets.activate(None if preset_id == "default" else preset_id)
        return JSONResponse({"status": "ok", "activePresetID": active})

    return Starlette(
        routes=[
            Route("/api/health", health),
            Route("/api/tools", get_tools),
            Route("/api/config", config_endpoint, methods=["GET", "PUT"]),
            Route("/api/servers/{name}/toggle", toggle_server, methods=["POST"]),
            Route("/api/tools/toggle", toggle_tool, methods=["POST"]),
            Route("/api/presets", list_presets, methods=["GET"]),
            Route("/api/presets", create_preset, methods=["POST"]),
            Route("/api/presets/{id}", update_preset, methods=["PATCH"]),
            Route("/api/presets/{id}", delete_preset, methods=["DELETE"]),
            Route("/api/presets/{id}/activate", activate_preset, methods=["POST"]),
        ],
        exception_handlers={HTTPException: json_error},
    )


def start_api_thread(container: Container, mcp_port: int, api_port: int) -> None:
    """Serve the management API from a daemon thread beside the MCP server."""
    import uvicorn

    threading.Thread(
        target=uvicorn.run,
        kwargs={
            "app": create_api_app(container, mcp_port),
            "host": "127.0.0.1",
            "port": api_port,
            "log_level": "error",
        },
        daemon=True,
    ).start()
