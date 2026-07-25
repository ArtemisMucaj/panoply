"""Integration tests for ``panoply auth``.

Runs against a fake credential store so no real token cache is touched.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from textual.widgets import DataTable

from panoply.connector.container import Container
from panoply.connector.tui.auth_manager import AuthManagerApp
from panoply.domain.model.tool import ToolDescriptor

CONFIG = {
    "mcpServers": {
        "atlassian": {
            "url": "https://atlassian.example.com/mcp",
            "transport": "http",
            "auth": "oauth",
        },
        "github": {
            "url": "https://github.example.com/mcp",
            "transport": "http",
            "auth": "oauth",
        },
        "local": {"command": "echo", "args": ["hi"]},
    }
}


class FakeStore:
    def __init__(self, keys: list[str]) -> None:
        self._keys = list(keys)
        self.cleared = False

    def keys(self) -> list[str]:
        return list(self._keys)

    def clear(self) -> None:
        self.cleared = True
        self._keys.clear()


@pytest.fixture
def store(container: Container) -> FakeStore:
    """Only atlassian has a cached token."""
    fake = FakeStore(["https://atlassian.example.com/mcp|token|abc"])
    container.credentials.store = fake
    return fake


@pytest.fixture
def config(container: Container) -> Path:
    path = container.settings.default_catalog_path
    path.write_text(json.dumps(CONFIG, indent=2))
    return path


def rows(app) -> list[list[str]]:
    table = app.query_one(DataTable)
    return [[str(cell) for cell in table.get_row(key)] for key in table.rows]


class TestPopulate:
    async def test_lists_every_server(self, container, config, store) -> None:
        app = AuthManagerApp(container, config)
        async with app.run_test() as pilot:
            await pilot.pause(0.05)
            assert set(app._server_names) == {"atlassian", "github", "local"}

    async def test_shows_cached_token_counts(self, container, config, store) -> None:
        app = AuthManagerApp(container, config)
        async with app.run_test() as pilot:
            await pilot.pause(0.05)
            cells = [cell for row in rows(app) for cell in row]
            assert any("1 token" in cell for cell in cells)
            assert any("none cached" in cell for cell in cells)
            assert any("N/A" in cell for cell in cells)

    async def test_uppercases_the_auth_type(self, container, config, store) -> None:
        app = AuthManagerApp(container, config)
        async with app.run_test() as pilot:
            await pilot.pause(0.05)
            assert len([row for row in rows(app) if "OAUTH" in row]) == 2


class TestLogout:
    async def test_clears_the_store_and_refreshes(
        self, container, config, store
    ) -> None:
        app = AuthManagerApp(container, config)
        async with app.run_test() as pilot:
            await pilot.pause(0.05)
            app.action_logout()
            await pilot.pause(0.05)
            assert store.cleared
            assert set(app._server_names) == {"atlassian", "github", "local"}

    async def test_reports_a_failure(
        self, container, config, store, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def boom() -> None:
            raise RuntimeError("kaboom")

        monkeypatch.setattr(container.credentials, "forget_all", boom)
        app = AuthManagerApp(container, config)
        async with app.run_test() as pilot:
            await pilot.pause(0.05)
            app.action_logout()
            await pilot.pause(0.05)
            status = str(app.query_one("#status").render())
            assert "failed" in status.lower()
            assert "kaboom" in status


class TestLogin:
    async def _select(self, app, pilot, name: str) -> None:
        app.query_one(DataTable).move_cursor(row=app._server_names.index(name))
        await pilot.pause(0.02)

    async def test_a_non_oauth_server_needs_no_login(
        self, container, config, store
    ) -> None:
        app = AuthManagerApp(container, config)
        async with app.run_test() as pilot:
            await pilot.pause(0.05)
            await self._select(app, pilot, "local")
            await app.action_login()
            status = str(app.query_one("#status").render())
            assert "does not use oauth" in status.lower()

    async def test_success_refreshes_the_table(
        self, container, config, store, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        probed: list[str] = []

        async def fake_probe(server):
            probed.append(server.name)
            return [ToolDescriptor("t1"), ToolDescriptor("t2")]

        monkeypatch.setattr(container.credentials.probe, "probe", fake_probe)

        app = AuthManagerApp(container, config)
        async with app.run_test() as pilot:
            await pilot.pause(0.05)
            await self._select(app, pilot, "atlassian")
            await app.action_login()
            for _ in range(40):
                if probed:
                    break
                await pilot.pause(0.05)
            await pilot.pause(0.05)

        assert probed == ["atlassian"]
        assert set(app._server_names) == {"atlassian", "github", "local"}

    async def test_failure_is_reported(
        self, container, config, store, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def fake_probe(server):
            raise RuntimeError("auth denied")

        monkeypatch.setattr(container.credentials.probe, "probe", fake_probe)

        app = AuthManagerApp(container, config)
        async with app.run_test() as pilot:
            await pilot.pause(0.05)
            await self._select(app, pilot, "atlassian")
            await app.action_login()
            for _ in range(40):
                if "Auth failed" in str(app.query_one("#status").render()):
                    break
                await pilot.pause(0.05)
            status = str(app.query_one("#status").render())
            assert "Auth failed" in status
            assert "auth denied" in status

    async def test_login_without_a_selection_is_a_noop(
        self, container, config, store
    ) -> None:
        empty = container.settings.data_dir / "empty.json"
        empty.write_text(json.dumps({"mcpServers": {}}))
        app = AuthManagerApp(container, empty)
        async with app.run_test() as pilot:
            await pilot.pause(0.05)
            await app.action_login()


class TestQuit:
    async def test_exits_cleanly(self, container, config, store) -> None:
        app = AuthManagerApp(container, config)
        async with app.run_test() as pilot:
            await pilot.pause(0.05)
            app.action_quit()
            await pilot.pause(0.05)
            assert not app.is_running
