"""Unit tests for :class:`ConfigurationService`."""

from __future__ import annotations

from pathlib import Path

import pytest

from panoply.domain.errors import ServerNotFound
from panoply.domain.model.preset import Preset, PresetBook

from .conftest import DEFAULT_SOURCE, InMemoryCatalogRepository, InMemoryPresetRepository

PRESET_SOURCE = Path("/memory/work.json")


class TestActiveSource:
    def test_defaults_when_no_preset_is_active(self, configuration) -> None:
        assert configuration.active_source() == DEFAULT_SOURCE

    def test_creates_the_default_document_on_first_run(
        self, catalogs: InMemoryCatalogRepository, configuration
    ) -> None:
        catalogs.documents.clear()
        assert configuration.active_source() == DEFAULT_SOURCE
        assert catalogs.documents[DEFAULT_SOURCE] == {"mcpServers": {}}

    def test_active_preset_wins(
        self,
        catalogs: InMemoryCatalogRepository,
        presets: InMemoryPresetRepository,
        configuration,
    ) -> None:
        catalogs.documents[PRESET_SOURCE] = {"mcpServers": {}}
        presets.book = PresetBook((Preset("p1", "work", PRESET_SOURCE),), "p1")
        assert configuration.active_source() == PRESET_SOURCE

    def test_preset_pointing_at_a_missing_file_falls_back(
        self, presets: InMemoryPresetRepository, configuration
    ) -> None:
        presets.book = PresetBook((Preset("p1", "work", Path("/gone.json")),), "p1")
        assert configuration.active_source() == DEFAULT_SOURCE

    def test_dangling_active_id_falls_back(
        self, presets: InMemoryPresetRepository, configuration
    ) -> None:
        presets.book = PresetBook((Preset("p1", "w", PRESET_SOURCE),), "bogus")
        assert configuration.active_source() == DEFAULT_SOURCE

    def test_resolve_honours_an_explicit_source(self, configuration) -> None:
        assert configuration.resolve(PRESET_SOURCE) == PRESET_SOURCE


class TestReading:
    def test_load_catalog_reads_the_active_source(self, configuration) -> None:
        assert configuration.load_catalog().names == ("alpha", "beta", "gamma")

    def test_read_document_is_verbatim(self, configuration, catalogs) -> None:
        assert configuration.read_document() == catalogs.documents[DEFAULT_SOURCE]


class TestServerToggle:
    async def test_disabling_writes_the_flag(self, configuration) -> None:
        await configuration.set_server_enabled("alpha", False)
        assert configuration.load_catalog().get("alpha").enabled is False

    async def test_enabling_removes_the_flag(self, configuration) -> None:
        await configuration.set_server_enabled("gamma", True)
        assert "enabled" not in configuration.load_catalog().get("gamma").settings

    async def test_publishes_a_configuration_change(self, configuration, events) -> None:
        await configuration.set_server_enabled("alpha", False)
        assert events.changes == 1

    async def test_unknown_server_raises_and_writes_nothing(
        self, configuration, catalogs, events
    ) -> None:
        before = dict(catalogs.documents[DEFAULT_SOURCE])
        with pytest.raises(ServerNotFound):
            await configuration.set_server_enabled("ghost", False)
        assert catalogs.documents[DEFAULT_SOURCE] == before
        assert events.changes == 0


class TestToolToggle:
    async def test_disabling_appends(self, configuration) -> None:
        await configuration.set_tool_enabled("alpha", "destructive", False)
        assert configuration.load_catalog().get("alpha").disabled_tools == (
            "destructive",
        )

    async def test_enabling_removes(self, configuration) -> None:
        await configuration.set_tool_enabled("beta", "noisy", True)
        assert configuration.load_catalog().get("beta").disabled_tools == ()

    async def test_publishes_tool_visibility_not_a_reload(
        self, configuration, events
    ) -> None:
        """The backend set is unchanged, so subprocesses must not restart."""
        await configuration.set_tool_enabled("alpha", "bad", False)
        assert events.tool_changes == [("alpha", "bad", False)]
        assert events.changes == 0


class TestReplaceDocument:
    async def test_stores_the_body_verbatim(self, configuration, catalogs) -> None:
        document = {"mcpServers": {"solo": {"url": "http://solo"}}, "note": "hi"}
        await configuration.replace_document(document)
        assert catalogs.documents[DEFAULT_SOURCE] == document

    async def test_publishes_a_configuration_change(self, configuration, events) -> None:
        await configuration.replace_document({"mcpServers": {}})
        assert events.changes == 1
