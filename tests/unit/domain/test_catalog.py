"""Unit tests for :class:`ServerCatalog`."""

from __future__ import annotations

import pytest

from panoply.domain.errors import InvalidConfiguration, ServerNotFound
from panoply.domain.model.catalog import ServerCatalog

PAYLOAD = {
    "mcpServers": {
        "alpha": {"url": "http://a", "description": "A things"},
        "beta": {"command": "echo", "args": ["hi"], "disabledTools": ["noisy"]},
        "gamma": {"url": "http://g", "enabled": False, "disabledTools": ["hidden"]},
    }
}


@pytest.fixture
def catalog() -> ServerCatalog:
    return ServerCatalog.from_payload(PAYLOAD)


class TestFromPayload:
    def test_reads_every_server(self, catalog: ServerCatalog) -> None:
        assert catalog.names == ("alpha", "beta", "gamma")

    def test_empty_payload(self) -> None:
        assert len(ServerCatalog.from_payload({})) == 0

    def test_rejects_non_object_document(self) -> None:
        with pytest.raises(InvalidConfiguration):
            ServerCatalog.from_payload(["nope"])

    def test_rejects_non_object_servers_key(self) -> None:
        with pytest.raises(InvalidConfiguration):
            ServerCatalog.from_payload({"mcpServers": []})

    def test_keeps_malformed_entries_aside(self) -> None:
        catalog = ServerCatalog.from_payload(
            {"mcpServers": {"bad": "not-a-dict", "ok": {"url": "http://o"}}}
        )
        assert catalog.names == ("ok",)
        assert catalog.malformed == {"bad": "not-a-dict"}


class TestRoundTrip:
    def test_payload_survives(self, catalog: ServerCatalog) -> None:
        assert catalog.to_payload() == PAYLOAD

    def test_unknown_top_level_keys_survive(self) -> None:
        payload = {"mcpServers": {}, "$schema": "https://example.com/s.json"}
        assert ServerCatalog.from_payload(payload).to_payload() == payload

    def test_malformed_entries_survive(self) -> None:
        payload = {"mcpServers": {"ok": {"url": "http://o"}, "bad": 7}}
        assert ServerCatalog.from_payload(payload).to_payload() == payload


class TestLookup:
    def test_get_returns_the_server(self, catalog: ServerCatalog) -> None:
        assert catalog.get("alpha").url == "http://a"

    def test_get_raises_for_unknown(self, catalog: ServerCatalog) -> None:
        with pytest.raises(ServerNotFound, match="not found"):
            catalog.get("ghost")

    def test_find_returns_none_for_unknown(self, catalog: ServerCatalog) -> None:
        assert catalog.find("ghost") is None

    def test_contains(self, catalog: ServerCatalog) -> None:
        assert "alpha" in catalog
        assert "ghost" not in catalog

    def test_enabled_servers_excludes_disabled(self, catalog: ServerCatalog) -> None:
        assert [s.name for s in catalog.enabled_servers] == ["alpha", "beta"]


class TestProjections:
    def test_disabled_tool_names_are_qualified(self, catalog: ServerCatalog) -> None:
        assert catalog.disabled_tool_names() == {"beta_noisy"}

    def test_disabled_servers_contribute_no_tool_names(
        self, catalog: ServerCatalog
    ) -> None:
        """gamma is off, so its own disabled tools are irrelevant."""
        assert "gamma_hidden" not in catalog.disabled_tool_names()

    def test_descriptions_default_to_blank(self, catalog: ServerCatalog) -> None:
        assert catalog.descriptions() == {"alpha": "A things", "beta": ""}

    def test_descriptions_skip_disabled_servers(self, catalog: ServerCatalog) -> None:
        assert "gamma" not in catalog.descriptions()

    def test_transport_entries_drop_disabled_servers(
        self, catalog: ServerCatalog
    ) -> None:
        assert set(catalog.transport_entries()) == {"alpha", "beta"}

    def test_transport_entries_strip_extras(self, catalog: ServerCatalog) -> None:
        assert catalog.transport_entries()["beta"] == {"command": "echo", "args": ["hi"]}

    def test_transport_payload_keeps_top_level_extras(self) -> None:
        catalog = ServerCatalog.from_payload({"mcpServers": {}, "note": "hi"})
        assert catalog.transport_payload() == {"mcpServers": {}, "note": "hi"}


class TestTransitions:
    def test_disable_server(self, catalog: ServerCatalog) -> None:
        updated = catalog.with_server_enabled("alpha", False)
        assert updated.get("alpha").enabled is False

    def test_enable_server_removes_the_key(self, catalog: ServerCatalog) -> None:
        updated = catalog.with_server_enabled("gamma", True)
        assert "enabled" not in updated.get("gamma").settings

    def test_toggle_preserves_order(self, catalog: ServerCatalog) -> None:
        assert catalog.with_server_enabled("alpha", False).names == catalog.names

    def test_toggle_unknown_server_raises(self, catalog: ServerCatalog) -> None:
        with pytest.raises(ServerNotFound):
            catalog.with_server_enabled("ghost", False)

    def test_disable_tool(self, catalog: ServerCatalog) -> None:
        updated = catalog.with_tool_enabled("alpha", "destructive", False)
        assert updated.get("alpha").disabled_tools == ("destructive",)

    def test_enable_tool_unknown_server_raises(self, catalog: ServerCatalog) -> None:
        with pytest.raises(ServerNotFound):
            catalog.with_tool_enabled("ghost", "x", False)

    def test_original_is_untouched(self, catalog: ServerCatalog) -> None:
        catalog.with_server_enabled("alpha", False)
        assert catalog.get("alpha").enabled is True
