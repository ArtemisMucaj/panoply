# Panoply

Your agent knows about 200 tools. It uses 5. The other 195 are just burning context on every single request.

Panoply fixes that. It proxies all your MCP servers behind a single endpoint and exposes just **3 tools** to the agent — `load_tools`, `search_tools`, and `call_tool`. The agent calls `load_tools` to see which providers are available, describes what it wants in plain language to `search_tools`, gets back the top matching tools with full schemas, and calls the right one with `call_tool`. You can connect 10 servers and 300 tools; the agent still sees 3.

For agents that need to do more in fewer round-trips, Panoply also ships **Code Mode**: instead of searching and calling tools one at a time, the agent writes a small sandboxed Python script that batches multiple tool calls in a single step.

## Install

Requires Python 3.11+ and [uv](https://docs.astral.sh/uv/).

```bash
uv run python -m panoply --http 7070
```

Or build a standalone binary:

```bash
bash scripts/build_panoply_binary.sh        # macOS arm64  → dist/panoply
bash scripts/build_panoply_binary_linux.sh  # Linux x86_64 → dist/panoply
```

The prebuilt macOS release binary is signed with a Developer ID and notarized
by Apple, so it runs without a Gatekeeper exception.

## Connecting your agent

```json
{
  "mcp": {
    "panoply": {
      "type": "http",
      "url": "http://127.0.0.1:7070/mcp"
    }
  }
}
```

The port is configurable. The management API runs alongside it on `PORT + 1`.

Clients that want agent skills re-exposed as tools opt in per connection with
`http://127.0.0.1:7070/mcp?skills=true`; everyone else gets the minimal endpoint.

## Configuration

Panoply reads `~/.panoply/servers.json` — the standard MCP config schema, plus
a few optional keys per server:

```json
{
  "mcpServers": {
    "github": {
      "url": "https://api.githubcopilot.com/mcp/",
      "auth": "oauth",
      "description": "Issues, PRs, commits, code search",
      "disabledTools": ["delete_repository"]
    },
    "filesystem": {
      "command": "npx",
      "args": ["-y", "@modelcontextprotocol/server-filesystem", "/home/me"],
      "enabled": false
    }
  }
}
```

- `description` — a one-line summary shown by `load_tools` so the agent can pick
  an area before searching. (A native MCP field.)
- `enabled: false` — switch a server off without deleting it.
- `disabledTools` — hide individual tools.

`${VAR}` placeholders inside a server's `env` are expanded from the environment.
Set `PANOPLY_DATA_DIR` to move the whole data directory somewhere else.

## Commands

```
panoply                    # stdio MCP server
panoply --http PORT        # HTTP MCP server + management API on PORT+1
panoply --code-mode        # swap tool search for the sandboxed code transform
panoply mcp                # TUI: browse and toggle servers and tools
panoply auth               # TUI: manage OAuth logins and cached tokens
panoply --config PATH      # use a specific config file
```

Preset activation and server/tool toggles hot-swap the active config live —
connected clients keep their sessions.

## Management API

Running with `--http PORT` also serves a REST API on `PORT + 1` for reading and
editing the catalog, probing backends, and switching presets. Edits apply to the
running proxy immediately — connected clients keep their sessions.

It is documented in **[openapi.yaml](openapi.yaml)** — generated from the code,
so it can't drift — which is what to generate a client from. A running server
also serves it at `/openapi.json`, with browsable docs at
`http://127.0.0.1:PORT+1/docs`. In short:

| | |
|---|---|
| `GET /api/health` | liveness and the port layout |
| `GET /api/tools` | probe every enabled backend for its real tool list |
| `GET` / `PUT /api/config` | read or replace the configuration document |
| `POST /api/servers/{name}/toggle` | enable or disable a whole server |
| `POST /api/tools/toggle` | show or hide one tool, without restarting backends |
| `GET` / `POST /api/presets` … | manage presets and activate one |

It binds `127.0.0.1` and has **no authentication** — it is a local control
plane. Don't expose it to a network.

## Architecture

Three layers with dependencies pointing inwards — `connector → application →
domain`. See [AGENTS.md](AGENTS.md).
