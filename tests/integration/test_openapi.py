"""The committed spec must be what the app actually generates.

``openapi.yaml`` is an artifact of ``panoply.connector.http``; these tests are
what stop it from being a stale one. The generator lives in ``scripts/`` rather
than the package — it is tooling, and keeping it there keeps PyYAML out of the
runtime dependencies — so it is loaded by path.
"""

from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest
import yaml
from starlette.testclient import TestClient

from panoply.connector.container import Container
from panoply.connector.http.api import create_api_app

REPO_ROOT = Path(__file__).resolve().parents[2]
SPEC_PATH = REPO_ROOT / "openapi.yaml"
GENERATOR = REPO_ROOT / "scripts" / "dump_openapi.py"


def load_generator():
    spec = importlib.util.spec_from_file_location("dump_openapi", GENERATOR)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture(scope="module")
def generator():
    return load_generator()


@pytest.fixture(scope="module")
def spec() -> dict:
    return yaml.safe_load(SPEC_PATH.read_text())


@pytest.fixture
def client(container: Container, servers_json: Path) -> TestClient:
    with TestClient(create_api_app(container, mcp_port=7070)) as client:
        yield client


class TestCommittedSpecIsCurrent:
    def test_matches_what_the_app_generates(self, generator) -> None:
        """If this fails: uv run python scripts/dump_openapi.py"""
        assert SPEC_PATH.read_text() == generator.render()

    def test_the_check_flag_agrees(self, generator) -> None:
        assert generator.main(["--check"]) == 0

    def test_generation_is_deterministic(self, generator) -> None:
        """Two runs must not differ, or every commit would churn the file."""
        assert generator.render() == generator.render()

    def test_carries_the_do_not_edit_header(self) -> None:
        assert SPEC_PATH.read_text().startswith("# Generated from the FastAPI app")


class TestSpecShape:
    def test_documents_every_route(self, spec: dict, container: Container) -> None:
        from starlette.routing import Route

        app = create_api_app(container, mcp_port=7070)
        implemented = {
            (route.path, method)
            for route in app.routes
            if isinstance(route, Route) and route.include_in_schema
            for method in (route.methods or set())
            if method not in {"HEAD", "OPTIONS"}
        }
        documented = {
            (path, method.upper())
            for path, item in spec["paths"].items()
            for method in item
        }
        assert implemented == documented

    def test_operation_ids_are_hand_written(self, spec: dict) -> None:
        """FastAPI's defaults (``health_api_health_get``) become the method names
        in a generated client, so every route sets its own."""
        ids = [
            operation["operationId"]
            for item in spec["paths"].values()
            for operation in item.values()
        ]
        assert len(ids) == len(set(ids))
        assert all("_api_" not in name for name in ids), ids

    def test_every_ref_resolves(self, spec: dict) -> None:
        def refs(node):
            if isinstance(node, dict):
                for key, value in node.items():
                    yield value if key == "$ref" else None
                    if key != "$ref":
                        yield from refs(value)
            elif isinstance(node, list):
                for item in node:
                    yield from refs(item)

        for ref in filter(None, refs(spec)):
            target = spec
            for part in ref.removeprefix("#/").split("/"):
                assert part in target, f"dangling $ref: {ref}"
                target = target[part]

    def test_reading_the_config_is_not_serialised_through_the_model(
        self, spec: dict
    ) -> None:
        """A response_model here would stamp every absent field in as null,
        which would break the documented verbatim read-back."""
        schema = spec["paths"]["/api/config"]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
        assert schema == {"$ref": "#/components/schemas/Configuration"}


class TestDocumentedShapesAreReal:
    """Assert live responses against what the spec promises."""

    def _required(self, spec: dict, name: str) -> set[str]:
        return set(spec["components"]["schemas"][name]["required"])

    def test_health(self, client: TestClient, spec: dict) -> None:
        body = client.get("/api/health").json()
        assert self._required(spec, "Health") <= set(body)
        assert body["api_port"] == body["mcp_port"] + 1

    def test_preset_book(self, client: TestClient, spec: dict) -> None:
        body = client.get("/api/presets").json()
        assert self._required(spec, "PresetBook") <= set(body)

    def test_created_preset(self, client, spec: dict, data_dir: Path) -> None:
        target = data_dir / "work.json"
        target.write_text('{"mcpServers": {}}')
        response = client.post(
            "/api/presets", json={"name": "work", "filePath": str(target)}
        )
        assert response.status_code == 201
        assert self._required(spec, "Preset") <= set(response.json()["preset"])

    def test_activation_result(self, client: TestClient, spec: dict) -> None:
        body = client.post("/api/presets/default/activate").json()
        assert self._required(spec, "ActivationResult") <= set(body)

    def test_panoply_errors_use_the_error_schema(
        self, client: TestClient, spec: dict
    ) -> None:
        body = client.post(
            "/api/servers/ghost/toggle", json={"enabled": False}
        ).json()
        assert self._required(spec, "Error") <= set(body)

    def test_validation_errors_use_the_documented_422(
        self, client: TestClient, spec: dict
    ) -> None:
        response = client.post("/api/tools/toggle", json={})
        assert response.status_code == 422
        documented = spec["paths"]["/api/tools/toggle"]["post"]["responses"]["422"]
        assert documented["content"]["application/json"]["schema"] == {
            "$ref": "#/components/schemas/HTTPValidationError"
        }
        # The documented shape is a list of per-field failures, not our error key.
        assert set(response.json()) == {"detail"}
        assert {"loc", "msg", "type"} <= set(response.json()["detail"][0])

    def test_tool_catalogue(self, client: TestClient, container: Container) -> None:
        from panoply.domain.model.tool import ToolDescriptor

        async def fake_probe(server):
            return [ToolDescriptor("create_issue", "Create an issue.")]

        container.discovery.probe.probe = fake_probe
        body = client.get("/api/tools").json()
        assert set(body["alpha"][0]) == {"name", "description"}
