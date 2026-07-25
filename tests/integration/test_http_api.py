"""Integration tests for the REST management API.

Every route is driven end-to-end through Starlette's ``TestClient`` against a
real container backed by a temp directory.  Only the probe is stubbed, so no
sockets are opened to real MCP servers.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from starlette.testclient import TestClient

from panoply.connector.container import Container
from panoply.connector.http.api import create_api_app
from panoply.domain.model.tool import ToolDescriptor


@pytest.fixture
def client(container: Container, servers_json: Path) -> TestClient:
    with TestClient(create_api_app(container, mcp_port=7070)) as client:
        yield client


@pytest.fixture
def stub_probe(container: Container, monkeypatch: pytest.MonkeyPatch):
    """Two deterministic tools per server, no network."""

    async def fake_probe(server):
        return [
            ToolDescriptor(f"{server.name}_tool1", "first"),
            ToolDescriptor(f"{server.name}_tool2", "second"),
        ]

    monkeypatch.setattr(container.discovery.probe, "probe", fake_probe)


@pytest.fixture
def recorded_events(container: Container):
    """Capture what the API publishes — this is the proxy hot-swap contract."""
    reloads: list[None] = []
    tool_toggles: list[tuple[str, str, bool]] = []
    container.events.on_configuration_changed(lambda: reloads.append(None))
    container.events.on_tool_visibility_changed(
        lambda server, tool, enabled: tool_toggles.append((server, tool, enabled))
    )
    return reloads, tool_toggles


class TestHealth:
    def test_reports_both_ports(self, client: TestClient) -> None:
        response = client.get("/api/health")
        assert response.status_code == 200
        assert response.json() == {
            "status": "ok",
            "mcp_port": 7070,
            "api_port": 7071,
        }


class TestTools:
    def test_returns_tools_for_enabled_servers(self, client, stub_probe) -> None:
        response = client.get("/api/tools")
        assert response.status_code == 200
        body = response.json()
        # gamma is disabled in the fixture
        assert set(body) == {"alpha", "beta"}
        assert body["alpha"][0] == {"name": "alpha_tool1", "description": "first"}

    def test_an_unreadable_config_is_a_500(self, client, servers_json: Path) -> None:
        servers_json.write_text("{ not json")
        assert client.get("/api/tools").status_code == 500


class TestConfig:
    def test_get_returns_the_document(self, client, servers_json: Path) -> None:
        response = client.get("/api/config")
        assert response.status_code == 200
        assert response.json() == json.loads(servers_json.read_text())

    def test_put_overwrites_it(self, client, servers_json: Path) -> None:
        document = {"mcpServers": {"solo": {"url": "http://solo"}}}
        response = client.put("/api/config", json=document)
        assert response.status_code == 200
        assert response.json() == {"status": "ok"}
        assert json.loads(servers_json.read_text()) == document

    def test_a_path_outside_the_data_dir_is_rejected(
        self, client, tmp_path: Path
    ) -> None:
        outside = tmp_path / "evil.json"
        outside.write_text("{}")
        response = client.get(f"/api/config?path={outside}")
        assert response.status_code == 400
        assert "must be a .json file" in response.json()["error"]

    def test_a_path_inside_the_data_dir_is_accepted(self, client, data_dir: Path) -> None:
        alternative = data_dir / "alt.json"
        alternative.write_text(json.dumps({"mcpServers": {"x": {"url": "http://x"}}}))
        response = client.get(f"/api/config?path={alternative}")
        assert response.status_code == 200
        assert response.json() == {"mcpServers": {"x": {"url": "http://x"}}}

    def test_a_non_json_file_is_rejected(self, client, data_dir: Path) -> None:
        other = data_dir / "alt.txt"
        other.write_text("not json")
        assert client.get(f"/api/config?path={other}").status_code == 400

    def test_corrupt_json_is_a_500(self, client, servers_json: Path) -> None:
        servers_json.write_text("{ not json")
        response = client.get("/api/config")
        assert response.status_code == 500
        assert "error" in response.json()


class TestServerToggle:
    def test_disabling_writes_the_flag(self, client, servers_json: Path) -> None:
        response = client.post("/api/servers/alpha/toggle", json={"enabled": False})
        assert response.status_code == 200
        document = json.loads(servers_json.read_text())
        assert document["mcpServers"]["alpha"]["enabled"] is False

    def test_enabling_removes_the_flag(self, client, servers_json: Path) -> None:
        response = client.post("/api/servers/gamma/toggle", json={"enabled": True})
        assert response.status_code == 200
        assert "enabled" not in json.loads(servers_json.read_text())["mcpServers"]["gamma"]

    def test_unknown_server_is_a_404(self, client: TestClient) -> None:
        response = client.post("/api/servers/ghost/toggle", json={"enabled": False})
        assert response.status_code == 404
        assert "not found" in response.json()["error"]

    def test_a_missing_body_is_a_400(self, client: TestClient) -> None:
        """The caller can fix this by sending a body, so it isn't a 500."""
        response = client.post("/api/servers/alpha/toggle")
        assert response.status_code == 400
        assert response.json()["error"] == "request body must be valid JSON"

    def test_a_corrupt_config_is_a_500(self, client, servers_json: Path) -> None:
        servers_json.write_text("{ not json")
        response = client.post("/api/servers/alpha/toggle", json={"enabled": False})
        assert response.status_code == 500


class TestToolToggle:
    def test_disabling_appends_to_the_list(self, client, servers_json: Path) -> None:
        response = client.post(
            "/api/tools/toggle",
            json={"server": "alpha", "tool": "destructive", "enabled": False},
        )
        assert response.status_code == 200
        document = json.loads(servers_json.read_text())
        assert document["mcpServers"]["alpha"]["disabledTools"] == ["destructive"]

    def test_enabling_the_last_one_removes_the_key(
        self, client, servers_json: Path
    ) -> None:
        response = client.post(
            "/api/tools/toggle",
            json={"server": "beta", "tool": "noisy", "enabled": True},
        )
        assert response.status_code == 200
        assert "disabledTools" not in json.loads(servers_json.read_text())["mcpServers"]["beta"]

    def test_enabling_a_tool_that_was_never_disabled_changes_nothing(
        self, client, servers_json: Path
    ) -> None:
        before = json.loads(servers_json.read_text())
        client.post(
            "/api/tools/toggle",
            json={"server": "alpha", "tool": "never", "enabled": True},
        )
        assert json.loads(servers_json.read_text()) == before

    def test_disabling_twice_is_idempotent(self, client, servers_json: Path) -> None:
        payload = {"server": "alpha", "tool": "dupe", "enabled": False}
        client.post("/api/tools/toggle", json=payload)
        client.post("/api/tools/toggle", json=payload)
        document = json.loads(servers_json.read_text())
        assert document["mcpServers"]["alpha"]["disabledTools"] == ["dupe"]

    def test_unknown_server_is_a_404(self, client: TestClient) -> None:
        response = client.post(
            "/api/tools/toggle", json={"server": "ghost", "tool": "t", "enabled": False}
        )
        assert response.status_code == 404

    def test_a_body_missing_keys_names_the_field(self, client: TestClient) -> None:
        response = client.post("/api/tools/toggle", json={})
        assert response.status_code == 400
        assert response.json()["error"] == "missing required field 'server'"


class TestPresets:
    def test_listing_starts_empty(self, client, data_dir: Path) -> None:
        body = client.get("/api/presets").json()
        assert body["presets"] == []
        assert body["activePresetID"] is None
        assert body["activeConfigPath"] == str(data_dir / "servers.json")

    def test_creating_returns_201(self, client, data_dir: Path) -> None:
        preset_file = data_dir / "work.json"
        preset_file.write_text('{"mcpServers": {}}')
        response = client.post(
            "/api/presets", json={"name": "work", "filePath": str(preset_file)}
        )
        assert response.status_code == 201
        preset = response.json()["preset"]
        assert preset["name"] == "work" and preset["id"]
        listing = client.get("/api/presets").json()
        assert any(p["id"] == preset["id"] for p in listing["presets"])

    def test_creating_without_a_path_names_the_field(self, client: TestClient) -> None:
        response = client.post("/api/presets", json={"name": "only"})
        assert response.status_code == 400
        assert response.json()["error"] == "missing required field 'filePath'"

    def test_updating_renames(self, client, data_dir: Path) -> None:
        created = self._create(client, data_dir, "a")
        response = client.patch(f"/api/presets/{created['id']}", json={"name": "renamed"})
        assert response.status_code == 200
        assert response.json()["preset"]["name"] == "renamed"

    def test_updating_an_unknown_preset_is_a_404(self, client: TestClient) -> None:
        assert client.patch("/api/presets/nope", json={"name": "x"}).status_code == 404

    def test_updating_with_a_corrupt_body_is_a_400(self, client, data_dir) -> None:
        created = self._create(client, data_dir, "p")
        response = client.patch(
            f"/api/presets/{created['id']}",
            content=b"{ not json",
            headers={"content-type": "application/json"},
        )
        assert response.status_code == 400

    def test_deleting(self, client, data_dir: Path) -> None:
        created = self._create(client, data_dir, "d")
        assert client.delete(f"/api/presets/{created['id']}").status_code == 200
        listing = client.get("/api/presets").json()
        assert all(p["id"] != created["id"] for p in listing["presets"])

    def test_deleting_an_unknown_preset_is_a_404(self, client: TestClient) -> None:
        assert client.delete("/api/presets/nope").status_code == 404

    def test_deleting_the_active_one_reverts_to_default(
        self, client, data_dir: Path
    ) -> None:
        created = self._create(client, data_dir, "d")
        client.post(f"/api/presets/{created['id']}/activate")
        client.delete(f"/api/presets/{created['id']}")
        assert client.get("/api/presets").json()["activePresetID"] is None

    def test_activating(self, client, data_dir: Path) -> None:
        created = self._create(client, data_dir, "x")
        response = client.post(f"/api/presets/{created['id']}/activate")
        assert response.status_code == 200
        assert response.json()["activePresetID"] == created["id"]
        assert client.get("/api/presets").json()["activePresetID"] == created["id"]

    def test_activating_changes_the_active_config_path(
        self, client, data_dir: Path
    ) -> None:
        created = self._create(client, data_dir, "x")
        client.post(f"/api/presets/{created['id']}/activate")
        assert client.get("/api/presets").json()["activeConfigPath"] == created[
            "filePath"
        ]

    def test_activating_an_unknown_preset_is_a_404(self, client: TestClient) -> None:
        assert client.post("/api/presets/missing/activate").status_code == 404

    def test_activating_default_clears_the_active_one(
        self, client, data_dir: Path
    ) -> None:
        created = self._create(client, data_dir, "x")
        client.post(f"/api/presets/{created['id']}/activate")
        response = client.post("/api/presets/default/activate")
        assert response.status_code == 200
        assert response.json()["activePresetID"] is None

    @staticmethod
    def _create(client: TestClient, data_dir: Path, name: str) -> dict:
        path = data_dir / f"{name}.json"
        path.write_text('{"mcpServers": {}}')
        return client.post(
            "/api/presets", json={"name": name, "filePath": str(path)}
        ).json()["preset"]


class TestHotSwapNotifications:
    """What the API publishes is what keeps the live proxy in step."""

    def test_server_toggle_asks_for_a_reload(self, client, recorded_events) -> None:
        reloads, tool_toggles = recorded_events
        client.post("/api/servers/alpha/toggle", json={"enabled": False})
        assert len(reloads) == 1
        assert tool_toggles == []

    def test_tool_toggle_avoids_a_reload(self, client, recorded_events) -> None:
        """Flipping one tool must not restart every backend subprocess."""
        reloads, tool_toggles = recorded_events
        client.post(
            "/api/tools/toggle", json={"server": "alpha", "tool": "bad", "enabled": False}
        )
        assert reloads == []
        assert tool_toggles == [("alpha", "bad", False)]

    def test_config_put_asks_for_a_reload(self, client, recorded_events) -> None:
        reloads, _ = recorded_events
        client.put("/api/config", json={"mcpServers": {}})
        assert len(reloads) == 1

    def test_preset_activation_asks_for_a_reload(
        self, client, recorded_events, data_dir: Path
    ) -> None:
        reloads, _ = recorded_events
        created = TestPresets._create(client, data_dir, "p")
        client.post(f"/api/presets/{created['id']}/activate")
        client.post("/api/presets/default/activate")
        assert len(reloads) == 2

    def test_deleting_the_active_preset_asks_for_a_reload(
        self, client, recorded_events, data_dir: Path
    ) -> None:
        reloads, _ = recorded_events
        created = TestPresets._create(client, data_dir, "p")
        client.post(f"/api/presets/{created['id']}/activate")
        reloads.clear()
        client.delete(f"/api/presets/{created['id']}")
        assert len(reloads) == 1

    def test_deleting_an_inactive_preset_does_not(
        self, client, recorded_events, data_dir: Path
    ) -> None:
        reloads, _ = recorded_events
        created = TestPresets._create(client, data_dir, "p")
        client.delete(f"/api/presets/{created['id']}")
        assert reloads == []

    def test_a_failed_toggle_does_not(self, client, recorded_events) -> None:
        reloads, _ = recorded_events
        client.post("/api/servers/ghost/toggle", json={"enabled": False})
        assert reloads == []

    def test_a_broken_subscriber_does_not_break_the_request(
        self, client, container: Container
    ) -> None:
        def explode() -> None:
            raise RuntimeError("subscriber is on fire")

        container.events.on_configuration_changed(explode)
        response = client.post("/api/servers/alpha/toggle", json={"enabled": False})
        assert response.status_code == 200


class TestErrorModel:
    """Every response is JSON with the same error key — including Starlette's own."""

    def test_an_unknown_route_is_json(self, client: TestClient) -> None:
        response = client.get("/api/nope")
        assert response.status_code == 404
        assert response.headers["content-type"].startswith("application/json")
        assert response.json() == {"error": "Not Found"}

    def test_a_wrong_method_is_json(self, client: TestClient) -> None:
        response = client.delete("/api/config")
        assert response.status_code == 405
        assert response.json() == {"error": "Method Not Allowed"}

    def test_a_non_object_body_is_rejected(self, client: TestClient) -> None:
        response = client.put("/api/config", json=[1, 2, 3])
        assert response.status_code == 400
        assert response.json()["error"] == "request body must be a JSON object"

    def test_server_side_failures_stay_500(self, client, servers_json: Path) -> None:
        """A corrupt file on disk is ours to fix, not the caller's."""
        servers_json.write_text("{ not json")
        assert client.get("/api/config").status_code == 500


class TestRoundTrip:
    def test_toggles_leave_a_readable_config(self, client: TestClient) -> None:
        client.post("/api/servers/alpha/toggle", json={"enabled": False})
        client.post(
            "/api/tools/toggle", json={"server": "alpha", "tool": "bad", "enabled": False}
        )
        body = client.get("/api/config").json()
        assert body["mcpServers"]["alpha"]["enabled"] is False
        assert body["mcpServers"]["alpha"]["disabledTools"] == ["bad"]
