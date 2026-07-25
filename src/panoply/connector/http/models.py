"""Request and response bodies for the management API.

These models *are* the published contract: ``openapi.yaml`` is generated from
them, so a field description here is what an integrator reads.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


class Health(BaseModel):
    """Liveness and the port layout."""

    status: Literal["ok"] = "ok"
    mcp_port: int = Field(description="Port serving `/mcp`.", examples=[7070])
    api_port: int = Field(
        description="Port serving this API — always `mcp_port + 1`.", examples=[7071]
    )


class StatusOk(BaseModel):
    """Returned by writes that have nothing else to say."""

    status: Literal["ok"] = "ok"


class Error(BaseModel):
    """Panoply's own errors. Request-validation failures use FastAPI's 422 instead."""

    error: str = Field(
        description="Human-readable; the status code carries the meaning.",
        examples=["Server 'ghost' not found"],
    )


class Tool(BaseModel):
    """A tool as reported by a backend."""

    name: str = Field(
        description="Bare tool name, server prefix stripped.", examples=["create_issue"]
    )
    description: str = Field(
        description="As reported by the backend; empty string if it gave none.",
        examples=["Create a new issue in a repository."],
    )


class ServerEntry(BaseModel):
    """One backend under ``mcpServers``.

    Either `url` (HTTP/SSE) or `command` (stdio), plus anything else the MCP
    config schema allows — only the fields Panoply itself acts on are listed.
    """

    model_config = ConfigDict(extra="allow")

    url: str | None = Field(default=None, description="Endpoint of an HTTP/SSE backend.")
    command: str | None = Field(
        default=None, description="Executable for a stdio backend."
    )
    args: list[str] | None = None
    env: dict[str, Any] | None = Field(
        default=None,
        description=(
            "Environment for a stdio backend. `${VAR}` placeholders are expanded from "
            "Panoply's own environment when the backend starts; an unset variable is "
            "left verbatim so it fails visibly."
        ),
    )
    auth: str | None = Field(
        default=None,
        description="Set to `oauth` to have Panoply run and cache the OAuth flow.",
    )
    description: str | None = Field(
        default=None,
        description=(
            "One-line summary of what this backend is for. A native MCP field — "
            "Panoply surfaces it through the `load_tools` tool so an agent can pick "
            "an area before searching."
        ),
    )
    enabled: bool | None = Field(
        default=None,
        description=(
            "**Panoply-only.** Absent means enabled; `false` switches the server off. "
            "Never written as `true`."
        ),
    )
    disabledTools: list[str] | None = Field(  # noqa: N815 - wire format is camelCase
        default=None,
        description=(
            "**Panoply-only.** Bare tool names to hide, without the server prefix."
        ),
    )


class Configuration(BaseModel):
    """A configuration document — the standard MCP config schema plus two extras.

    The Panoply-only keys (`enabled`, `disabledTools`) are stripped before an
    entry reaches the MCP client, so they never touch a backend. Unrecognised
    top-level keys are preserved across edits.
    """

    model_config = ConfigDict(
        extra="allow",
        json_schema_extra={
            "example": {
                "mcpServers": {
                    "github": {
                        "url": "https://api.githubcopilot.com/mcp/",
                        "auth": "oauth",
                        "description": "Issues, PRs, commits, code search",
                        "disabledTools": ["delete_repository"],
                    },
                    "filesystem": {
                        "command": "npx",
                        "args": [
                            "-y",
                            "@modelcontextprotocol/server-filesystem",
                            "/home/me",
                        ],
                        "enabled": False,
                    },
                }
            }
        },
    )

    mcpServers: dict[str, ServerEntry] = Field(  # noqa: N815 - wire format
        default_factory=dict, description="Backends, keyed by name."
    )


class ServerToggle(BaseModel):
    enabled: bool = Field(default=True, description="Defaults to `true` if omitted.")


class ToolToggle(BaseModel):
    server: str = Field(examples=["github"])
    tool: str = Field(
        description="Bare name, without the server prefix.",
        examples=["delete_repository"],
    )
    enabled: bool = Field(default=True, description="Defaults to `true` if omitted.")


class Preset(BaseModel):
    """A named pointer to a configuration file."""

    model_config = ConfigDict(extra="allow")

    id: str = Field(description="Server-generated (a UUID).")
    name: str = Field(examples=["work"])
    filePath: str = Field(  # noqa: N815 - wire format
        description="Absolute path to the configuration file.",
        examples=["/Users/me/.panoply/work.json"],
    )


class PresetEnvelope(BaseModel):
    preset: Preset


class PresetInput(BaseModel):
    name: str = Field(examples=["work"])
    filePath: str = Field(examples=["/Users/me/.panoply/work.json"])  # noqa: N815


class PresetPatch(BaseModel):
    """Only the fields present are changed."""

    name: str | None = None
    filePath: str | None = None  # noqa: N815 - wire format


class PresetBook(BaseModel):
    presets: list[Preset]
    activePresetID: str | None = Field(  # noqa: N815 - wire format
        description="`null` when the default configuration is in force."
    )
    activeConfigPath: str = Field(  # noqa: N815 - wire format
        description="Absolute path to the configuration currently in force."
    )


class ActivationResult(BaseModel):
    status: Literal["ok"] = "ok"
    activePresetID: str | None = Field(  # noqa: N815 - wire format
        description="`null` after reverting to the default."
    )


#: Tools per server name. An empty array means "could not be probed" too.
ToolCatalogue = dict[str, list[Tool]]

#: A configuration document passed through verbatim.
RawDocument = dict[str, Any]
