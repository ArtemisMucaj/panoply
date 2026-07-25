"""REST management API.

Runs alongside the MCP endpoint (on ``port + 1``) and is what the desktop app
and the TUIs drive.  Handlers do nothing but translate HTTP to a use case and
back — every rule they appear to enforce lives in the domain.

``openapi.yaml`` is **generated from this module** (``scripts/dump_openapi.py``),
so the docstrings and models here are the published contract. FastAPI also
serves it live at ``/openapi.json``, with browsable docs at ``/docs``.
"""

from __future__ import annotations

import threading
from importlib.metadata import PackageNotFoundError, version
from pathlib import Path
from typing import Annotated

from fastapi import FastAPI, HTTPException, Path as PathParam, Query, Request
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from panoply.connector.container import Container
from panoply.connector.http.models import (
    ActivationResult,
    Configuration,
    Error,
    Health,
    PresetBook,
    PresetEnvelope,
    PresetInput,
    PresetPatch,
    RawDocument,
    ServerToggle,
    StatusOk,
    ToolCatalogue,
    ToolToggle,
)
from panoply.domain.errors import NotFound, PanoplyError

DESCRIPTION = """\
The REST API for driving a running Panoply MCP proxy — read and edit the server
catalog, probe backends for their real tool lists, and switch between presets.

## Where it runs

Panoply started with `--http PORT` serves two things:

| Port | What |
|---|---|
| `PORT` | the MCP endpoint, at `/mcp` (Streamable HTTP; not described here) |
| `PORT + 1` | **this API**, under `/api` |

Both bind `127.0.0.1` only. There is **no authentication and no CORS** — the
API is a local control plane, so anything reaching it is already on the
machine. Do not expose it to a network.

## Live changes

Edits take effect immediately on the running proxy; clients keep their MCP
sessions and are told to re-read the tool list. Two grades of change:

- **Tool toggles** flip a tool's visibility in place. Backend subprocesses keep
  running.
- **Everything else** (server toggle, config write, preset activation) changes
  *which* backends are proxied, so the proxy is rebuilt and stdio backends
  restart.

## Error model

| Status | Body | Meaning |
|---|---|---|
| `422` | `{"detail": [...]}` | request validation — a missing or ill-typed field. FastAPI's standard shape. |
| `400` | `{"error": "..."}` | rejected by Panoply — currently only a `path`/`config` outside the data directory. |
| `404` | `{"error": "..."}` | no such server, preset, or route. |
| `405` | `{"error": "..."}` | wrong method for that route. |
| `500` | `{"error": "..."}` | Panoply failed — unreadable config on disk, failed write. |

A `4xx` is worth surfacing to a user; a `500` means retrying the same request
will not help.
"""

TAGS = [
    {"name": "Status", "description": "Liveness and port discovery."},
    {"name": "Configuration", "description": "Reading and editing the server catalog."},
    {
        "name": "Discovery",
        "description": "Asking the backends what tools they actually have.",
    },
    {"name": "Presets", "description": "Named configurations and which one is active."},
]

BAD_PATH = {"model": Error, "description": "The `path`/`config` override was rejected."}
NOT_FOUND = {"model": Error, "description": "No such server or preset."}
FAILED = {"model": Error, "description": "Panoply failed; retrying will not help."}

#: Routes that take a path override but address no named aggregate.
SOURCED = {400: BAD_PATH, 500: FAILED}
#: Routes that also address a server by name.
SOURCED_NAMED = {400: BAD_PATH, 404: NOT_FOUND, 500: FAILED}
#: Preset routes, which take no path override.
NAMED = {404: NOT_FOUND, 500: FAILED}

# Parameter aliases must live at module scope: ``from __future__ import
# annotations`` turns every annotation into a string, and FastAPI can only
# resolve those against module globals.
ConfigQuery = Annotated[
    str | None,
    Query(
        description=(
            "Operate on a specific configuration file instead of the active one. "
            "Must resolve to a `.json` file directly inside Panoply's data "
            "directory; anything else is a 400."
        ),
        examples=["/Users/me/.panoply/work.json"],
    ),
]
ServerName = Annotated[
    str,
    PathParam(
        description="Server name, as it appears under `mcpServers`.",
        examples=["github"],
    ),
]
PresetId = Annotated[
    str, PathParam(description="Preset id, as returned when it was created.")
]
ActivatedPresetId = Annotated[
    str,
    PathParam(
        description="A preset id, or the literal `default` to revert.",
        examples=["default"],
    ),
]


def api_version() -> str:
    """Version for ``info.version``, or a placeholder in a frozen binary."""
    try:
        return version("panoply")
    except PackageNotFoundError:  # pragma: no cover - only in a PyInstaller build
        return "0.0.0+unknown"


def create_api_app(container: Container, mcp_port: int) -> FastAPI:
    """Build the management API."""
    configuration = container.configuration
    presets = container.preset_service
    discovery = container.discovery
    data_dir = container.settings.data_dir.resolve()

    app = FastAPI(
        title="Panoply Management API",
        description=DESCRIPTION,
        version=api_version(),
        openapi_tags=TAGS,
        servers=[{"url": "http://127.0.0.1:7071", "description": "Default (MCP on 7070)"}],
    )

    # ── Errors ────────────────────────────────────────────────────────────────
    # Registered per exception type rather than on bare ``Exception`` so a
    # genuinely unexpected bug still surfaces as a traceback instead of being
    # flattened into a tidy 500.

    def as_error(status_code: int, message: str) -> JSONResponse:
        return JSONResponse({"error": message}, status_code=status_code)

    @app.exception_handler(NotFound)
    async def _not_found(request: Request, exc: NotFound) -> JSONResponse:
        return as_error(404, str(exc))

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(
        request: Request, exc: StarletteHTTPException
    ) -> JSONResponse:
        """Render our 400s and Starlette's own 404/405 in one shape."""
        return as_error(exc.status_code, exc.detail)

    @app.exception_handler(PanoplyError)
    @app.exception_handler(ValueError)  # includes json.JSONDecodeError
    @app.exception_handler(OSError)
    async def _failed(request: Request, exc: Exception) -> JSONResponse:
        return as_error(500, str(exc))

    # ── Shared parameters ─────────────────────────────────────────────────────

    def resolve_source(override: str | None, param: str) -> Path:
        """Honour an explicit override only inside the data directory.

        Without the containment check these endpoints would read and overwrite
        any JSON file on the machine.
        """
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

    @app.get(
        "/api/health",
        operation_id="getHealth",
        tags=["Status"],
        summary="Liveness and port layout",
    )
    async def health() -> Health:
        """Cheap and dependency-free — it does not read the config or touch a
        backend. Poll this to decide whether Panoply is up."""
        return Health(mcp_port=mcp_port, api_port=mcp_port + 1)

    @app.get(
        "/api/tools",
        tags=["Discovery"],
        operation_id="probeTools",
        summary="Probe every enabled backend for its tool list",
        responses=SOURCED,
    )
    async def probe_tools(config: ConfigQuery = None) -> ToolCatalogue:
        """Opens a real connection to each **enabled** server in parallel and
        returns the tools it reports, with the `servername_` prefix stripped.

        This is deliberately not the proxy's own tool list: through the proxy an
        agent only ever sees the three synthetic tools, whereas a management UI
        needs the real per-server catalogue to render enable/disable controls.

        A backend that is unreachable, slow (30s cap), or failing yields an
        **empty array** rather than failing the whole request — so an empty list
        means "could not be probed" as well as "has no tools". Expect this call
        to take as long as your slowest backend.

        Disabled servers are omitted entirely.
        """
        catalogue = await discovery.catalogue(resolve_source(config, "config"))
        return {
            name: [tool.to_payload() for tool in tools]
            for name, tools in catalogue.items()
        }

    # ── Configuration ─────────────────────────────────────────────────────────

    @app.get(
        "/api/config",
        tags=["Configuration"],
        operation_id="getConfig",
        summary="Read the configuration document",
        # Documented via ``responses`` rather than ``response_model``: serialising
        # through the model would stamp every absent optional field into the
        # payload as null, which is the opposite of returning it verbatim.
        responses={
            200: {"model": Configuration, "description": "The configuration document."},
            **SOURCED,
        },
        # Only the ``responses`` entry above may supply the 200 schema.
        response_model=None,
    )
    async def get_config(path: ConfigQuery = None) -> RawDocument:
        """Returns the active configuration verbatim, exactly as stored —
        including any keys Panoply itself does not interpret."""
        return configuration.read_document(resolve_source(path, "path"))

    @app.put(
        "/api/config",
        tags=["Configuration"],
        operation_id="replaceConfig",
        summary="Replace the configuration document",
        responses=SOURCED,
    )
    async def replace_config(
        document: Configuration, request: Request, path: ConfigQuery = None
    ) -> StatusOk:
        """Overwrites the whole document with the request body, written
        atomically (temp file plus rename), then rebuilds the proxy.

        The body is stored **verbatim**: it is validated against the schema, but
        what lands on disk is the exact JSON you sent — Panoply does not
        normalise, reorder, or drop unknown keys, so an editor that manages the
        file itself keeps full control.

        This replaces rather than merges. Read the document first if you intend
        to change one field.
        """
        await configuration.replace_document(
            await request.json(), resolve_source(path, "path")
        )
        return StatusOk()

    @app.post(
        "/api/servers/{name}/toggle",
        tags=["Configuration"],
        operation_id="toggleServer",
        summary="Enable or disable a whole server",
        responses=SOURCED_NAMED,
    )
    async def toggle_server(
        name: ServerName, body: ServerToggle, path: ConfigQuery = None
    ) -> StatusOk:
        """Disabling writes `"enabled": false` onto the entry; enabling removes
        the key entirely, since enabled is the default and a minimal config is
        easier to hand-edit.

        Rebuilds the proxy: a disabled server's backend process is stopped and
        its tools disappear.
        """
        await configuration.set_server_enabled(
            name, body.enabled, resolve_source(path, "path")
        )
        return StatusOk()

    @app.post(
        "/api/tools/toggle",
        tags=["Configuration"],
        operation_id="toggleTool",
        summary="Show or hide a single tool",
        responses=SOURCED_NAMED,
    )
    async def toggle_tool(body: ToolToggle, path: ConfigQuery = None) -> StatusOk:
        """Adds or removes the tool from its server's `disabledTools`. Idempotent
        in both directions: disabling twice appends once, and enabling a tool
        that was never disabled changes nothing.

        Unlike every other write, this **does not rebuild the proxy** — the tool
        is flipped on the live server and backend processes are untouched. Use it
        in preference to editing `disabledTools` through `PUT /api/config`, which
        would restart every backend.

        The tool name is the bare name as returned by `GET /api/tools`, without
        the server prefix.
        """
        await configuration.set_tool_enabled(
            body.server, body.tool, body.enabled, resolve_source(path, "path")
        )
        return StatusOk()

    # ── Presets ───────────────────────────────────────────────────────────────

    @app.get(
        "/api/presets",
        tags=["Presets"],
        operation_id="listPresets",
        summary="List presets and the active configuration",
        responses={500: FAILED},
    )
    async def list_presets() -> PresetBook:
        """`activeConfigPath` is the file currently in force. It follows the
        active preset, and falls back to the default `servers.json` when no
        preset is active — or when the active one points at a file that has since
        been deleted."""
        book = presets.book()
        return PresetBook(
            **book.to_payload(),
            activeConfigPath=str(configuration.active_source()),
        )

    @app.post(
        "/api/presets",
        tags=["Presets"],
        operation_id="createPreset",
        summary="Create a preset",
        status_code=201,
        responses={500: FAILED},
    )
    async def create_preset(body: PresetInput) -> PresetEnvelope:
        """Registers a name and a file path; the id is generated. Creating a
        preset does not activate it, and the file is not required to exist yet."""
        preset = presets.create(body.name, body.filePath)
        return PresetEnvelope(preset=preset.to_payload())

    @app.patch(
        "/api/presets/{id}",
        tags=["Presets"],
        operation_id="updatePreset",
        summary="Rename a preset or repoint it",
        responses=NAMED,
    )
    async def update_preset(id: PresetId, body: PresetPatch) -> PresetEnvelope:
        """Only the fields present in the body are changed.

        Repointing the **active** preset rebuilds the proxy; renaming never does.
        """
        preset = presets.update(id, name=body.name, file_path=body.filePath)
        return PresetEnvelope(preset=preset.to_payload())

    @app.delete(
        "/api/presets/{id}",
        tags=["Presets"],
        operation_id="deletePreset",
        summary="Delete a preset",
        responses=NAMED,
    )
    async def delete_preset(id: PresetId) -> StatusOk:
        """The configuration file itself is left on disk — only the pointer is
        removed. Deleting the active preset reverts to the default configuration
        and rebuilds the proxy."""
        presets.delete(id)
        return StatusOk()

    @app.post(
        "/api/presets/{id}/activate",
        tags=["Presets"],
        operation_id="activatePreset",
        summary="Switch the active preset",
        responses=NAMED,
    )
    async def activate_preset(id: ActivatedPresetId) -> ActivationResult:
        """Makes this preset's file the active configuration and rebuilds the
        proxy. No request body.

        Pass the literal id **`default`** to deactivate whatever is active and
        fall back to `servers.json`; `activePresetID` then comes back `null`.
        """
        active = presets.activate(None if id == "default" else id)
        return ActivationResult(activePresetID=active)

    return app


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
