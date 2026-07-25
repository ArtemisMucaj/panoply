"""The published contract must match the app that serves it.

``openapi.yaml`` is what other projects integrate against, so it is checked
here the same way code is: every route documented, every documented route real,
and the response shapes asserted against live responses rather than trusted.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml
from starlette.routing import Route
from starlette.testclient import TestClient

from panoply.connector.container import Container
from panoply.connector.http.api import create_api_app

SPEC_PATH = Path(__file__).resolve().parents[2] / "openapi.yaml"
IGNORED_METHODS = {"HEAD", "OPTIONS"}


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text())


@pytest.fixture
def client(container: Container, servers_json: Path) -> TestClient:
    with TestClient(create_api_app(container, mcp_port=7070)) as client:
        yield client


def documented_operations(spec: dict) -> set[tuple[str, str]]:
    return {
        (path, method.upper())
        for path, item in spec["paths"].items()
        for method in item
        if method.lower() in {"get", "put", "post", "patch", "delete"}
    }


def implemented_operations(container: Container) -> set[tuple[str, str]]:
    app = create_api_app(container, mcp_port=7070)
    return {
        (route.path, method)
        for route in app.routes
        if isinstance(route, Route)
        for method in (route.methods or set())
        if method not in IGNORED_METHODS
    }


class TestSpecIsWellFormed:
    def test_parses(self, spec: dict) -> None:
        assert spec["openapi"].startswith("3.")
        assert spec["info"]["title"] == "Panoply Management API"

    def test_every_ref_resolves(self, spec: dict) -> None:
        def refs(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    if key == "$ref":
                        yield value
                    else:
                        yield from refs(value)
            elif isinstance(node, list):
                for item in node:
                    yield from refs(item)

        for ref in refs(spec):
            assert ref.startswith("#/"), f"external $ref not allowed: {ref}"
            target = spec
            for part in ref.removeprefix("#/").split("/"):
                assert part in target, f"dangling $ref: {ref}"
                target = target[part]

    def test_every_operation_has_an_id(self, spec: dict) -> None:
        ids = [
            operation["operationId"]
            for item in spec["paths"].values()
            for method, operation in item.items()
            if method.lower() in {"get", "put", "post", "patch", "delete"}
        ]
        assert len(ids) == len(set(ids)), "operationIds must be unique"


class TestSpecMatchesTheApp:
    def test_no_undocumented_routes(self, container: Container, spec: dict) -> None:
        missing = implemented_operations(container) - documented_operations(spec)
        assert not missing, f"routes missing from openapi.yaml: {sorted(missing)}"

    def test_no_documented_routes_that_do_not_exist(
        self, container: Container, spec: dict
    ) -> None:
        extra = documented_operations(spec) - implemented_operations(container)
        assert not extra, f"openapi.yaml documents routes that do not exist: {sorted(extra)}"


class TestDocumentedShapesAreReal:
    """Assert live responses against what the spec promises."""

    def _required(self, spec: dict, schema_name: str) -> set[str]:
        return set(spec["components"]["schemas"][schema_name]["required"])

    def test_health(self, client: TestClient, spec: dict) -> None:
        body = client.get("/api/health").json()
        assert self._required(spec, "Health") <= set(body)
        assert body["api_port"] == body["mcp_port"] + 1

    def test_preset_book(self, client: TestClient, spec: dict) -> None:
        body = client.get("/api/presets").json()
        assert self._required(spec, "PresetBook") <= set(body)

    def test_created_preset(self, client: TestClient, spec: dict, data_dir: Path) -> None:
        target = data_dir / "work.json"
        target.write_text(json.dumps({"mcpServers": {}}))
        response = client.post(
            "/api/presets", json={"name": "work", "filePath": str(target)}
        )
        assert response.status_code == 201
        assert self._required(spec, "PresetEnvelope") <= set(response.json())
        assert self._required(spec, "Preset") <= set(response.json()["preset"])

    def test_activation_result(self, client: TestClient, spec: dict) -> None:
        body = client.post("/api/presets/default/activate").json()
        assert self._required(spec, "ActivationResult") <= set(body)
        assert body["activePresetID"] is None

    def test_status_ok(self, client: TestClient, spec: dict) -> None:
        body = client.post("/api/servers/alpha/toggle", json={"enabled": False}).json()
        assert self._required(spec, "StatusOk") <= set(body)

    @pytest.mark.parametrize(
        ("method", "path", "payload", "status"),
        [
            ("post", "/api/servers/ghost/toggle", {"enabled": False}, 404),
            ("post", "/api/tools/toggle", {}, 400),
            ("get", "/api/nope", None, 404),
        ],
    )
    def test_errors_all_use_the_documented_shape(
        self, client: TestClient, spec: dict, method, path, payload, status
    ) -> None:
        response = getattr(client, method)(path, **({"json": payload} if payload is not None else {}))
        assert response.status_code == status
        assert response.headers["content-type"].startswith("application/json")
        assert self._required(spec, "Error") <= set(response.json())

    def test_tool_catalogue(self, client: TestClient, container: Container) -> None:
        from panoply.domain.model.tool import ToolDescriptor

        async def fake_probe(server):
            return [ToolDescriptor("create_issue", "Create an issue.")]

        container.discovery.probe.probe = fake_probe
        body = client.get("/api/tools").json()
        assert set(body["alpha"][0]) == {"name", "description"}
