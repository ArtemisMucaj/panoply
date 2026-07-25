"""``panoply auth`` — manage OAuth authentication for proxied servers."""

from __future__ import annotations

from pathlib import Path

from textual.app import App, ComposeResult
from textual.binding import Binding
from textual.widgets import DataTable, Footer, Header, Static

from panoply.connector.container import Container
from panoply.domain.errors import PanoplyError
from panoply.domain.model.catalog import ServerCatalog


class AuthManagerApp(App[None]):
    """Lists every configured server and its auth state.

    For OAuth servers the user can trigger a login (which opens a browser) or
    clear every cached token.
    """

    TITLE = "Panoply Auth Manager"
    CSS = """
    Screen {
        layout: vertical;
    }
    DataTable {
        height: 1fr;
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
        Binding("q", "quit", "Quit"),
        Binding("l", "login", "Login"),
        Binding("x", "logout", "Clear Tokens"),
    ]

    def __init__(self, container: Container, source: Path) -> None:
        super().__init__()
        self.container = container
        self.source = source
        self.catalog = ServerCatalog.empty()
        self._server_names: list[str] = []

    # ── Lifecycle ─────────────────────────────────────────────────────────────

    def compose(self) -> ComposeResult:
        yield Header()
        yield DataTable(zebra_stripes=True, cursor_type="row")
        yield Static("", id="status")
        yield Footer()

    def on_mount(self) -> None:
        try:
            self.catalog = self.container.catalogs.load(self.source)
        except (PanoplyError, ValueError):
            self.catalog = ServerCatalog.empty()
        self._populate_table()

    # ── Table ─────────────────────────────────────────────────────────────────

    def _populate_table(self) -> None:
        table = self.query_one(DataTable)
        if not table.columns:
            table.add_columns("Server", "Auth Type", "Token Files")

        servers = sorted(self.catalog, key=lambda s: s.name)
        self._server_names = [server.name for server in servers]

        for server in servers:
            auth = server.settings.get("auth", "")
            if server.uses_oauth:
                count = self.container.credentials.cached_token_count(server)
                status = f"{count} token(s) cached" if count else "none cached"
            else:
                status = "N/A"
            table.add_row(
                server.name, auth.upper() if auth else "—", status, key=server.name
            )

        self._set_status("[l] Login (OAuth)  [x] Clear all tokens  [q] Quit")

    def _refresh_table(self) -> None:
        table = self.query_one(DataTable)
        table.clear(columns=False)
        self._server_names = []
        self._populate_table()

    # ── Actions ───────────────────────────────────────────────────────────────

    def _selected_server(self):
        row = self.query_one(DataTable).cursor_row
        if 0 <= row < len(self._server_names):
            return self.catalog.find(self._server_names[row])
        return None

    async def action_login(self) -> None:
        server = self._selected_server()
        if server is None:
            return

        if not server.uses_oauth:
            self._set_status(f"'{server.name}' does not use OAuth — no login needed.")
            return

        self._set_status(
            f"Starting OAuth for '{server.name}'… complete the flow in your browser."
        )

        async def do_login() -> None:
            try:
                tools = await self.container.credentials.authenticate(server)
            except Exception as exc:
                self._set_status(f"✗ Auth failed for '{server.name}': {exc}")
                return
            self._set_status(
                f"✓ Authenticated '{server.name}' — {len(tools)} tool(s) available."
            )
            self._refresh_table()

        self.run_worker(do_login())

    def action_logout(self) -> None:
        """Wipe all cached OAuth tokens."""
        try:
            self.container.credentials.forget_all()
        except Exception as exc:
            self._set_status(f"✗ Failed to clear tokens: {exc}")
            return

        self._set_status("✓ All OAuth tokens cleared.")
        self._refresh_table()

    def action_quit(self) -> None:
        self.exit()

    # ── Helpers ───────────────────────────────────────────────────────────────

    def _set_status(self, message: str) -> None:
        self.query_one("#status", Static).update(message)
