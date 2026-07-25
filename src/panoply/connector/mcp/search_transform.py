"""Panoply's search transform: a three-step tool-discovery workflow."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Annotated, Any

from fastmcp.server.context import Context
from fastmcp.server.transforms import GetToolNext
from fastmcp.server.transforms.search import BM25SearchTransform
from fastmcp.tools.base import Tool, ToolResult
from fastmcp.utilities.versions import VersionSpec


class PanoplySearchTransform(BM25SearchTransform):
    """BM25 tool search fronted by a cheap "what is even here?" overview.

    Adds a third always-visible synthetic tool, ``load_tools``, in front of
    the usual ``search_tools`` / ``call_tool`` pair.  ``load_tools`` returns an
    overview of which backend servers are proxied and what each one is for, so
    an agent can orient itself before searching — the server-level analog of
    how skills always expose their one-line descriptions.

    The synthetic-tool descriptions are rewritten to make the workflow
    explicit (load → search → call) and to include examples that stop small
    models from pasting their whole task into the search query.

    Args:
        server_descriptions: ``{server_name: description}`` for the enabled
            servers, from :meth:`ServerCatalog.descriptions`.  Rendered by
            ``load_tools``.  Other args are forwarded to ``BM25SearchTransform``.
    """

    def __init__(
        self,
        *,
        server_descriptions: dict[str, str] | None = None,
        **kwargs: Any,
    ) -> None:
        super().__init__(**kwargs)
        self._server_descriptions = server_descriptions or {}
        self._load_tool_name = "load_tools"

    # ── Transform interface ──────────────────────────────────────────────────

    async def transform_tools(self, tools: Sequence[Tool]) -> Sequence[Tool]:
        """Expose load_tools alongside the pinned + search/call tools."""
        base = list(await super().transform_tools(tools))
        return [self._make_load_tool(), *base]

    async def get_tool(
        self, name: str, call_next: GetToolNext, *, version: VersionSpec | None = None
    ) -> Tool | None:
        """Intercept the load_tools name; delegate everything else."""
        if name == self._load_tool_name:
            return self._make_load_tool()
        return await super().get_tool(name, call_next, version=version)

    # ── Synthetic tools ──────────────────────────────────────────────────────

    def _make_load_tool(self) -> Tool:
        transform = self

        async def load_tools() -> str:
            """STEP 1 OF 3 — Call this FIRST to see which tool providers exist.

            Returns the list of connected servers (tool providers) and a short
            description of what each one is for. It does NOT execute anything or
            fetch external data — it only lists the capabilities reachable
            through this proxy so you can aim your next search.

            Workflow:
              1. load_tools()           → see which providers/areas are available
              2. search_tools(query)    → find a specific tool by keyword
              3. call_tool(name, args)  → execute it

            Call this once at the start when you are unsure what tools exist,
            then pick the relevant area and search within it.
            """
            return transform._render_server_overview()

        return Tool.from_function(fn=load_tools, name=self._load_tool_name)

    def _make_search_tool(self) -> Tool:
        transform = self

        async def search_tools(
            query: Annotated[
                str,
                (
                    "Short keyword or phrase describing the capability you need. "
                    "Use keywords only — do NOT paste the full user request here. "
                    "Examples: 'create github issue', 'read file', 'send email', 'list commits'."
                ),
            ],
            ctx: Context = None,  # type: ignore[assignment]  # ty:ignore[invalid-parameter-default]
        ) -> str | list[dict[str, Any]]:
            """STEP 2 OF 3 — Find a tool by keyword before calling it.

            Search the available tool catalog using a short keyword or phrase.
            Returns matching tool names and their parameter schemas.

            If you do not yet know what providers exist, call `load_tools`
            first for an overview, then search within the relevant area.

            IMPORTANT: This tool discovers tools — it does not execute them.
            After finding the right tool here, use `call_tool` to run it.

            DO pass a concise keyword or phrase:
              query="create github issue"
              query="read file contents"
              query="send slack message"
              query="list git commits"

            DO NOT paste the full user task or request as the query:
              WRONG: query="Can you create a GitHub issue titled 'Login bug' with body '...'"
              RIGHT: query="create github issue"
            """
            hidden = await transform._get_visible_tools(ctx)
            results = await transform._search(hidden, query)
            return await transform._render_results(results)

        return Tool.from_function(fn=search_tools, name=self._search_tool_name)

    def _make_call_tool(self) -> Tool:
        transform = self

        async def call_tool(
            name: Annotated[
                str,
                (
                    "Exact name of the tool to execute, as returned by search_tools. "
                    "Example: 'github_create_issue', 'filesystem_read_file'."
                ),
            ],
            arguments: Annotated[
                dict[str, Any] | None,
                (
                    "Arguments for the tool as a key/value dict. "
                    "Use the parameter schema returned by search_tools to build this. "
                    'Example: {"title": "Login bug", "body": "Steps to reproduce..."}.'
                ),
            ] = None,
            ctx: Context = None,  # type: ignore[assignment]  # ty:ignore[invalid-parameter-default]
        ) -> ToolResult:
            """STEP 3 OF 3 — Execute a tool discovered via search_tools.

            Call any tool by its exact name with the required arguments.
            The tool name and parameter schema come from a prior search_tools call.

            Workflow:
              1. Call load_tools to see which providers are available.
              2. Call search_tools with keywords to find the right tool.
              3. Call call_tool with the tool name and arguments to run it.

            Examples:
              name="github_create_issue",
                arguments={"title": "Login bug", "body": "Steps to reproduce..."}

              name="filesystem_read_file",
                arguments={"path": "/home/user/notes.txt"}

              name="slack_send_message",
                arguments={"channel": "#general", "text": "Deploy complete"}
            """
            if name in {
                transform._call_tool_name,
                transform._search_tool_name,
                transform._load_tool_name,
            }:
                raise ValueError(
                    f"'{name}' is a synthetic search tool and cannot be called via call_tool"
                )
            return await ctx.fastmcp.call_tool(name, arguments)

        return Tool.from_function(fn=call_tool, name=self._call_tool_name)

    # ── Rendering ────────────────────────────────────────────────────────────

    def _render_server_overview(self) -> str:
        """Render the configured servers + descriptions as a compact overview."""
        servers = self._server_descriptions
        if not servers:
            return (
                "No tool providers are currently configured. "
                "Use search_tools with a keyword to look for a tool anyway."
            )
        lines = [
            "Tool providers reachable through this proxy. Pick the relevant "
            "area, then call search_tools with a keyword to find a specific tool:",
            "",
        ]
        for name, description in servers.items():
            lines.append(f"- {name}: {description}" if description else f"- {name}")
        return "\n".join(lines)
