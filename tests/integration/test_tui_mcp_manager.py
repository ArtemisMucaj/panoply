"""Integration tests for ``panoply mcp``.

Drives the Textual app through ``run_test``/``Pilot`` with the probe stubbed,
so the app never opens a socket.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from panoply.connector.container import Container
from panoply.connector.tui.mcp_manager import MCPManagerApp
from panoply.domain.model.tool import ToolDescriptor

CONFIG = {
    "mcpServers": {
        "alpha": {"url": "http://alpha", "transport": "http"},
        "beta": {
            "url": "http://beta",
            "transport": "http",
            "disabledTools": ["tool_b"],
        },
        "gamma": {"url": "http://gamma", "transport": "http", "enabled": False},
    }
}


@pytest.fixture
def stub_probe(container: Container, monkeypatch: pytest.MonkeyPatch):
    async def fake_probe(server):
        return [ToolDescriptor("tool_a", "first"), ToolDescriptor("tool_b", "second")]

    monkeypatch.setattr(container.discovery.probe, "probe", fake_probe)


@pytest.fixture
def config(container: Container) -> Path:
    path = container.settings.default_catalog_path
    path.write_text(json.dumps(CONFIG, indent=2))
    return path


async def await_probe(pilot, attempts: int = 40) -> None:
    """Wait until every ``probing…`` placeholder has been replaced.

    Fails loudly with the names still in flight rather than letting a test
    pass against a half-populated tree.
    """
    tree = pilot.app.query_one("Tree")
    still_probing: list[str] = []
    for _ in range(attempts):
        still_probing = [
            data["name"]
            for node in tree.root.children
            if (data := node.data)
            and data.get("type") == "server"
            and data.get("enabled", True)
            and any("probing" in str(child.label) for child in node.children)
        ]
        if not still_probing:
            return
        await pilot.pause(0.05)
    raise AssertionError(
        f"probing did not finish within ~{attempts * 0.05:.2f}s: {still_probing}"
    )


def node_for(app, name: str):
    return next(
        node
        for node in app.query_one("Tree").root.children
        if node.data and node.data.get("name") == name
    )


class TestLoading:
    async def test_every_server_appears(self, container, config, stub_probe) -> None:
        app = MCPManagerApp(container, config)
        async with app.run_test() as pilot:
            await pilot.pause(0.05)
            names = {
                node.data["name"]
                for node in app.query_one("Tree").root.children
                if node.data and node.data.get("type") == "server"
            }
            assert names == {"alpha", "beta", "gamma"}

    async def test_enabled_state_reflects_the_config(
        self, container, config, stub_probe
    ) -> None:
        app = MCPManagerApp(container, config)
        async with app.run_test() as pilot:
            await pilot.pause(0.05)
            states = {
                node.data["name"]: node.data["enabled"]
                for node in app.query_one("Tree").root.children
                if node.data and node.data.get("type") == "server"
            }
            assert states == {"alpha": True, "beta": True, "gamma": False}

    async def test_probing_replaces_the_placeholder(
        self, container, config, stub_probe
    ) -> None:
        app = MCPManagerApp(container, config)
        async with app.run_test() as pilot:
            await await_probe(pilot)
            labels = [str(c.label) for c in node_for(app, "alpha").children]
            assert any("tool_a" in label for label in labels)
            assert any("tool_b" in label for label in labels)

    async def test_disabled_servers_are_not_probed(
        self, container, config, stub_probe
    ) -> None:
        app = MCPManagerApp(container, config)
        async with app.run_test() as pilot:
            await pilot.pause(0.05)
            labels = [str(c.label) for c in node_for(app, "gamma").children]
            assert any("server disabled" in label for label in labels)

    async def test_already_disabled_tools_show_as_off(
        self, container, config, stub_probe
    ) -> None:
        app = MCPManagerApp(container, config)
        async with app.run_test() as pilot:
            await await_probe(pilot)
            states = {
                child.data["name"]: child.data["enabled"]
                for child in node_for(app, "beta").children
            }
            assert states == {"tool_a": True, "tool_b": False}

    async def test_a_probe_failure_leaves_that_server_empty(
        self, container, config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        async def angry_probe(server):
            if server.name == "alpha":
                raise RuntimeError("nope")
            return [ToolDescriptor("only_beta_tool")]

        monkeypatch.setattr(container.discovery.probe, "probe", angry_probe)

        app = MCPManagerApp(container, config)
        async with app.run_test() as pilot:
            await await_probe(pilot)
            assert list(node_for(app, "alpha").children) == []
            labels = [str(c.label) for c in node_for(app, "beta").children]
            assert any("only_beta_tool" in label for label in labels)

    async def test_a_corrupt_config_does_not_crash_the_app(
        self, container, stub_probe
    ) -> None:
        bad = container.settings.data_dir / "bad.json"
        bad.write_text("{ not json")
        app = MCPManagerApp(container, bad)
        async with app.run_test() as pilot:
            await pilot.pause(0.1)
            # The parse-error status is preserved — the app refuses to overwrite
            # a malformed config with an empty catalog.
            status = str(app.query_one("#status").render())
            assert status.startswith("Config parse error:")


class TestToggling:
    async def test_disabling_a_server_is_saved(
        self, container, config, stub_probe
    ) -> None:
        app = MCPManagerApp(container, config)
        async with app.run_test() as pilot:
            await await_probe(pilot)
            tree = app.query_one("Tree")
            alpha = node_for(app, "alpha")
            tree.select_node(alpha)
            await pilot.pause(0.02)
            app.action_toggle_item()
            await pilot.pause(0.02)
            assert alpha.data["enabled"] is False
            app.action_quit_save()
            await pilot.pause(0.05)

        assert json.loads(config.read_text())["mcpServers"]["alpha"]["enabled"] is False

    async def test_re_enabling_removes_the_flag(
        self, container, config, stub_probe
    ) -> None:
        app = MCPManagerApp(container, config)
        async with app.run_test() as pilot:
            await pilot.pause(0.05)
            tree = app.query_one("Tree")
            tree.select_node(node_for(app, "gamma"))
            await pilot.pause(0.02)
            app.action_toggle_item()
            await pilot.pause(0.02)
            app.action_quit_save()
            await pilot.pause(0.05)

        assert "enabled" not in json.loads(config.read_text())["mcpServers"]["gamma"]

    async def test_saving_without_changes_preserves_the_config(
        self, container, config, stub_probe
    ) -> None:
        before = json.loads(config.read_text())
        app = MCPManagerApp(container, config)
        async with app.run_test() as pilot:
            await await_probe(pilot)
            app.action_quit_save()
            await pilot.pause(0.05)
        assert json.loads(config.read_text()) == before

    async def test_disabling_a_tool_is_saved(self, container, config, stub_probe) -> None:
        app = MCPManagerApp(container, config)
        async with app.run_test() as pilot:
            await await_probe(pilot)
            tree = app.query_one("Tree")
            tool = node_for(app, "alpha").children[0]
            tree.select_node(tool)
            await pilot.pause(0.02)
            app.action_toggle_item()
            await pilot.pause(0.02)
            assert tool.data["enabled"] is False
            assert "tool_a" in app.disabled_tools["alpha"]
            app.action_quit_save()
            await pilot.pause(0.05)

        saved = json.loads(config.read_text())
        assert saved["mcpServers"]["alpha"]["disabledTools"] == ["tool_a"]

    async def test_toggling_a_tool_back_on_removes_it(
        self, container, config, stub_probe
    ) -> None:
        app = MCPManagerApp(container, config)
        async with app.run_test() as pilot:
            await await_probe(pilot)
            tree = app.query_one("Tree")
            tool = node_for(app, "alpha").children[0]
            tree.select_node(tool)
            await pilot.pause(0.02)
            app.action_toggle_item()
            await pilot.pause(0.02)
            app.action_toggle_item()
            await pilot.pause(0.02)
            assert tool.data["name"] not in app.disabled_tools["alpha"]

    async def test_tools_of_a_disabled_server_cannot_be_toggled(
        self, container, config, stub_probe
    ) -> None:
        app = MCPManagerApp(container, config)
        async with app.run_test() as pilot:
            await await_probe(pilot)
            tree = app.query_one("Tree")
            alpha = node_for(app, "alpha")
            tool = alpha.children[0]
            alpha.data["enabled"] = False

            tree.select_node(tool)
            await pilot.pause(0.02)
            before = tool.data["enabled"]
            app.action_toggle_item()
            await pilot.pause(0.02)

            assert tool.data["enabled"] == before
            assert "Enable the server first" in str(app.query_one("#status").render())

    async def test_toggling_with_no_cursor_is_a_noop(
        self, container, stub_probe
    ) -> None:
        empty = container.settings.data_dir / "empty.json"
        empty.write_text(json.dumps({"mcpServers": {}}))
        app = MCPManagerApp(container, empty)
        async with app.run_test() as pilot:
            await pilot.pause(0.05)
            app.action_toggle_item()

    async def test_a_server_removed_under_us_is_skipped_on_save(
        self, container, config, stub_probe
    ) -> None:
        from panoply.domain.model.catalog import ServerCatalog

        app = MCPManagerApp(container, config)
        async with app.run_test() as pilot:
            await await_probe(pilot)
            app.catalog = ServerCatalog(
                tuple(s for s in app.catalog if s.name != "alpha"),
                app.catalog.extras,
                app.catalog.malformed,
            )
            app.action_quit_save()
            await pilot.pause(0.05)

        saved = json.loads(config.read_text())
        assert "alpha" not in saved["mcpServers"]
        assert "beta" in saved["mcpServers"]

    async def test_an_unprobed_server_keeps_its_disabled_tools(
        self, container, config, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A backend that was down this session must not lose its tool state."""

        async def failing_probe(server):
            raise RuntimeError("unreachable")

        monkeypatch.setattr(container.discovery.probe, "probe", failing_probe)

        app = MCPManagerApp(container, config)
        async with app.run_test() as pilot:
            await await_probe(pilot)
            app.action_quit_save()
            await pilot.pause(0.05)

        saved = json.loads(config.read_text())
        assert saved["mcpServers"]["beta"]["disabledTools"] == ["tool_b"]


class TestRefresh:
    async def test_re_probing_repopulates_the_tree(
        self, container, config, stub_probe
    ) -> None:
        app = MCPManagerApp(container, config)
        async with app.run_test() as pilot:
            await await_probe(pilot)
            alpha = node_for(app, "alpha")
            assert alpha.data["probed_tools"]

            app.action_refresh()
            assert alpha.data["probed_tools"] == []
            await await_probe(pilot)
            assert alpha.data["probed_tools"]
