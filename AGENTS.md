# AGENTS.md

## What this is

Panoply is an MCP proxy that aggregates multiple MCP servers behind 3 synthetic
tools (`load_tools` → `search_tools` → `call_tool`). Python 3.11+, managed with
**uv**. It was extracted from the Jarvis desktop app, which now embeds it.

## Architecture — three layers, dependencies point inwards

```
src/panoply/
  domain/          # what Panoply IS. No frameworks, no I/O, no clock.
    model/         #   ServerDefinition, ServerCatalog, Preset/PresetBook,
                   #   ToolDescriptor, ${VAR} expansion
    policies/      #   authentication (is this a 401? whose tool is it?), skills
    ports/         #   Protocols the connector implements
    errors.py      #   the errors a use case can raise on a foreseen path
  application/     # use cases, one service per area. Orchestrates the domain
                   # through ports; publishes ConfigurationEvents.
  connector/       # everything that touches the outside world
    persistence/   #   driven: JSON repos, atomic writes, disk credential store
    mcp/           #   driven: FastMCP translator, proxy factory, probe,
                   #   search transform, middleware, skills mount
    http/          #   driving: REST management API + streamable-HTTP MCP host
    cli/           #   driving: argument parsing + entry point
    tui/           #   driving: Textual apps
    container.py   #   composition root — the only module that knows every adapter
    settings.py    #   paths, ports, timeouts, resolved once at start-up
```

**The rule:** `connector → application → domain`, never the reverse. If a use
case seems to need FastMCP, Starlette, or Textual, the missing piece is a port.
A quick check that the layering still holds:

```bash
grep -rE "^(from|import) (fastmcp|starlette|textual|mcp)\b" src/panoply/domain src/panoply/application
# must print nothing
```

### Where the interesting decisions live

- **`ServerCatalog`** is the aggregate. Every edit is a pure transition
  (`with_server_enabled`, `with_tool_enabled`) returning a new catalog.
  `extras` and `malformed` carry unknown top-level keys and non-object server
  entries through a load/save round-trip so hand-written configs survive.
- **`ServerCatalogRepository.update(source, mutate)`** is the unit of work: the
  repository holds the per-file lock, loads, applies the domain transition, and
  writes atomically. A raising *mutate* leaves the file untouched.
- **`ConfigurationEvents`** decouples "config changed" from "proxy reacts".
  A server toggle publishes `configuration_changed` (rebuild + restart
  backends); a tool toggle publishes `tool_visibility_changed` (flip in place,
  backends untouched). `connector/http/server.py` subscribes and hot-swaps.
- **`Settings` + `Container`** replace module-level globals. Nothing reads
  `os.environ` or `Path.home()` behind the container's back, which is what lets
  a test point the whole app at `tmp_path` in one line.
- **`FastMCPProxyFactory`** picks `StatefulProxyClient` for stdio backends (one
  subprocess per frontend session) and `ProxyClient` for HTTP/SSE (fresh
  connection per request). The stateful clients are kept on
  `FastMCPProxyServer.clients` — `new_stateful` reads caches off the instance,
  so letting them be collected would silently break every stdio backend.
- **`PanoplySearchTransform`** subclasses `BM25SearchTransform` and exposes a
  third always-visible tool:
  - `load_tools` — STEP 1. A cheap overview of which backends are proxied and
    what each is for, sourced from the per-server `description` field. Lets an
    agent orient before searching.
  - `search_tools` / `call_tool` — STEPS 2 and 3, with descriptions that spell
    out the workflow and include DO/DON'T examples, so small models stop
    pasting the whole user task into the search query.

## Commands

```bash
# Install deps (no separate install step — uv handles it)
uv sync --group dev

# Run locally
uv run python -m panoply --http 7070     # HTTP: MCP on 7070, management API on 7071
uv run python -m panoply                 # stdio
uv run python -m panoply mcp             # server/tool manager TUI
uv run python -m panoply auth            # OAuth manager TUI

# Run all tests
uv run --group dev pytest tests

# Run one file or one test
uv run --group dev pytest tests/unit/domain/test_catalog.py
uv run --group dev pytest tests/unit/domain/test_catalog.py -k test_name

# Build a standalone binary
bash scripts/build_panoply_binary.sh        # macOS arm64  → dist/panoply
bash scripts/build_panoply_binary_linux.sh  # Linux x86_64 → dist/panoply
```

## Configuration

Panoply reads `~/.panoply/servers.json` (override the whole directory with
`PANOPLY_DATA_DIR`). The format is the standard MCP config schema plus two
Panoply-only keys, which are stripped before the entry reaches FastMCP:

- `enabled: false` — switch a whole server off
- `disabledTools: [...]` — hide individual tools

`description` is a *native* MCP field, so it round-trips untouched and feeds the
`load_tools` overview.

## Testing

- **pytest-asyncio `auto` mode** is on (`asyncio_mode = "auto"`). Do not add
  `@pytest.mark.asyncio` to async tests.
- Tests mirror the layers: `tests/unit/{domain,application,connector}` and
  `tests/integration` (REST API, both TUIs, the CLI).
- `tests/conftest.py` gives you `settings` → `container` → `servers_json`.
  There is no import-time environment hack and no global to monkeypatch — build
  a container and pass it in.
- `tests/unit/application/conftest.py` holds in-memory doubles for every port,
  so the application layer is tested with no filesystem and no FastMCP.
- Never raise `KeyboardInterrupt` from inside an `asyncio.gather` under test —
  it interrupts the whole pytest session rather than failing one test. Assert
  that shutdown signals propagate at the single-call level instead.

## CI

- Every push/PR: pytest + binary builds (macOS arm64, Linux x86_64).
- No lint or typecheck step.
