"""``panoply mcp`` — browse and toggle servers and their tools."""

from __future__ import annotations

import asyncio
from pathlib import Path

from textual import work
from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import Footer, Header, Static, Tree

from panoply.connector.container import Container
from panoply.domain.errors import PanoplyError
from panoply.domain.model.catalog import ServerCatalog
from panoply.domain.model.server import ServerDefinition

SERVER = "server"
TOOL = "tool"
HINT = "hint"


class MCPManagerApp(App[None]):
    """Servers and tools shown with [✓]/[ ] toggle state.

    The tree is populated from the config immediately and tool lists are
    filled in by background probes, so a slow backend never blocks the UI.
    Changes are written back on quit.
    """

    TITLE = "Panoply Manager"
    CSS = """
    Screen {
        layout: vertical;
        background: $background;
    }
    Tree {
        height: 1fr;
        border: solid $accent;
        margin: 0 1;
    }
    #status {
        height: 1;
        background: $boost;
        padding: 0 2;
        color: $text-muted;
    }
    """
    BINDINGS = [
        Binding("q", "quit_save", "Save & Quit"),
        Binding("space", "toggle_item", "Toggle", priority=True),
        Binding("r", "refresh", "Re-probe"),
    ]

    def __init__(self, container: Container, source: Path) -> None:
        super().__init__()
        self.container = container
        self.source = source
        self.catalog = ServerCatalog.empty()
        self.disabled_tools: dict[str, set[str]] = {}

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        yield Tree("Servers & Tools")
        yield Static("Loading…", id="status")
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.catalog = self.container.catalogs.load(self.source)
        except (PanoplyError, ValueError) as exc:
            self._set_status(f"Config parse error: {exc}")
            return
        self._populate_tree()
        self._probe_all()

    # ── Tree ──────────────────────────────────────────────────────────────────

    def _populate_tree(self) -> None:
        tree = self.query_one(Tree)
        self.disabled_tools = {}

        for server in sorted(self.catalog, key=lambda s: s.name):
            self.disabled_tools[server.name] = set(server.disabled_tools)
            mark = "[✓]" if server.enabled else "[ ]"
            node = tree.root.add(
                f"{mark} {server.name}",
                data={
                    "type": SERVER,
                    "name": server.name,
                    "enabled": server.enabled,
                    "probed_tools": [],
                },
            )
            node.allow_expand = True
            node.add_leaf(
                "  ⟳ probing…" if server.enabled else "  (server disabled)",
                data={"type": HINT},
            )

        tree.root.expand()
        count = len(self.catalog)
        self._set_status(
            f"Probing {count} server(s)…" if count else "No servers configured."
        )

    def _update_server_tools(self, server_name: str, tools: list[str]) -> None:
        """Replace a server's placeholder children with actual tool nodes."""
        tree = self.query_one(Tree)
        for node in tree.root.children:
            if not node.data or node.data.get("name") != server_name:
                continue
            node.data["probed_tools"] = tools

            for child in list(node.children):
                child.remove()

            disabled = self.disabled_tools.get(server_name, set())
            for tool in tools:
                enabled = tool not in disabled
                mark = "  [✓]" if enabled else "  [ ]"
                node.add_leaf(
                    f"{mark} {tool}",
                    data={
                        "type": TOOL,
                        "name": tool,
                        "server": server_name,
                        "enabled": enabled,
                    },
                )

            if tools and node.data.get("enabled", True):
                node.expand()
            break

    # ── Background probing ────────────────────────────────────────────────────

    @work
    async def _probe_all(self) -> None:
        """Probe all enabled servers in the background (in the app event loop)."""
        tree = self.query_one(Tree)
        pending: list[ServerDefinition] = [
            server
            for node in tree.root.children
            if (data := node.data)
            and data.get("type") == SERVER
            and data.get("enabled", True)
            and (server := self.catalog.find(data["name"])) is not None
        ]

        total = len(pending)
        if total == 0:
            self._set_status("No enabled servers.")
            return

        done = 0

        async def probe_one(server: ServerDefinition) -> None:
            nonlocal done
            tools = await self.container.discovery.inspect_safely(server)
            if not self.is_running:
                return
            self._update_server_tools(server.name, [tool.name for tool in tools])
            done += 1
            self._set_status(
                f"Probing… {done}/{total} done"
                if done < total
                else "All servers probed.  [Space] toggle  [q] save & quit  [r] re-probe"
            )

        await asyncio.gather(*(probe_one(server) for server in pending))

    # ── Actions ───────────────────────────────────────────────────────────────

    def action_toggle_item(self) -> None:
        cursor = self.query_one(Tree).cursor_node
        if not cursor or not cursor.data:
            return
        data = cursor.data

        if data.get("type") == SERVER:
            data["enabled"] = not data["enabled"]
            mark = "[✓]" if data["enabled"] else "[ ]"
            cursor.label = f"{mark} {data['name']}"

        elif data.get("type") == TOOL:
            parent = cursor.parent
            if parent and parent.data and not parent.data.get("enabled", True):
                self._set_status("Enable the server first before toggling its tools.")
                return
            data["enabled"] = not data["enabled"]
            mark = "  [✓]" if data["enabled"] else "  [ ]"
            cursor.label = f"{mark} {data['name']}"
            disabled = self.disabled_tools.get(data.get("server", ""))
            if disabled is not None:
                if data["enabled"]:
                    disabled.discard(data["name"])
                else:
                    disabled.add(data["name"])

    def action_quit_save(self) -> None:
        self._save()
        self.exit()

    def action_refresh(self) -> None:
        """Re-probe all servers and refresh the tree."""
        tree = self.query_one(Tree)
        for node in tree.root.children:
            data = node.data
            if data and data.get("type") == SERVER and data.get("enabled", True):
                for child in list(node.children):
                    child.remove()
                node.add_leaf("  ⟳ probing…", data={"type": HINT})
                data["probed_tools"] = []
        self._set_status("Re-probing…")
        self._probe_all()

    # ── Persistence ───────────────────────────────────────────────────────────

    def _save(self) -> None:
        """Fold the tree's toggle state back into the catalog and store it.

        Tool state is only written for servers that were actually probed —
        otherwise a backend that was unreachable this session would look like
        a server with no tools and lose its disabled list.

        Refuses to write when the status bar shows a parse error, so a
        malformed config is never overwritten with an empty catalog.
        """
        status_text = str(self.query_one("#status", Static).render())
        if status_text.startswith("Config parse error:"):
            self._set_status("Refusing to save — config parse error.")
            return

        catalog = self.catalog
        for node in self.query_one(Tree).root.children:
            data = node.data
            if not data or data.get("type") != SERVER:
                continue
            server = catalog.find(data["name"])
            if server is None:
                continue

            server = server.with_enabled(data["enabled"])
            if data.get("probed_tools"):
                server = server.with_disabled_tools(
                    self.disabled_tools.get(server.name, set())
                )
            catalog = catalog.with_server(server)

        self.catalog = catalog
        self.container.catalogs.save(self.source, catalog)

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)
