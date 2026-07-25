"""Unit tests for the file-backed repositories and their primitives."""

from __future__ import annotations

import asyncio
import json
import os
from pathlib import Path
from unittest.mock import patch

import pytest

from panoply.connector.persistence.catalog_repository import JsonServerCatalogRepository
from panoply.connector.persistence.files import PathLocks, atomic_write_json
from panoply.connector.persistence.preset_repository import JsonPresetRepository
from panoply.connector.settings import Settings
from panoply.domain.errors import ServerNotFound
from panoply.domain.model.catalog import ServerCatalog
from panoply.domain.model.preset import Preset, PresetBook


class TestAtomicWriteJson:
    def test_writes_indented_json(self, tmp_path: Path) -> None:
        target = tmp_path / "out.json"
        atomic_write_json(target, {"a": 1, "b": [2, 3]})
        content = target.read_text()
        assert json.loads(content) == {"a": 1, "b": [2, 3]}
        assert "\n" in content

    def test_overwrites(self, tmp_path: Path) -> None:
        target = tmp_path / "out.json"
        target.write_text('{"old": true}')
        atomic_write_json(target, {"new": True})
        assert json.loads(target.read_text()) == {"new": True}

    def test_creates_missing_parents(self, tmp_path: Path) -> None:
        target = tmp_path / "nested" / "deep" / "out.json"
        atomic_write_json(target, {"a": 1})
        assert target.exists()

    def test_serialisation_failure_leaves_nothing_behind(self, tmp_path: Path) -> None:
        target = tmp_path / "out.json"
        with pytest.raises(TypeError):
            atomic_write_json(target, {"bad": {1, 2, 3}})
        assert not target.exists()
        assert list(tmp_path.glob("*.tmp")) == []

    def test_write_failure_removes_the_temp_file(self, tmp_path: Path) -> None:
        target = tmp_path / "out.json"
        real_fdopen = os.fdopen

        def failing_fdopen(fd, *args, **kwargs):
            handle = real_fdopen(fd, *args, **kwargs)
            handle.close()  # close the fd properly before raising
            raise OSError("write failed")

        with patch(
            "panoply.connector.persistence.files.os.fdopen", side_effect=failing_fdopen
        ):
            with pytest.raises(OSError, match="write failed"):
                atomic_write_json(target, {"a": 1})

        assert not target.exists()
        assert list(tmp_path.glob("*.tmp")) == []

    def test_cleanup_failure_does_not_mask_the_original_error(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from panoply.connector.persistence import files

        def failing_replace(src, dst):
            raise RuntimeError("replace failed")

        def failing_unlink(path):
            raise OSError("unlink failed")

        monkeypatch.setattr(files.os, "replace", failing_replace)
        monkeypatch.setattr(files.os, "unlink", failing_unlink)

        with pytest.raises(RuntimeError, match="replace failed"):
            atomic_write_json(tmp_path / "out.json", {"a": 1})


class TestPathLocks:
    def test_same_path_gets_the_same_lock(self, tmp_path: Path) -> None:
        locks = PathLocks()
        path = tmp_path / "c.json"
        assert locks.for_path(path) is locks.for_path(path)

    def test_different_paths_get_different_locks(self, tmp_path: Path) -> None:
        locks = PathLocks()
        assert locks.for_path(tmp_path / "a.json") is not locks.for_path(
            tmp_path / "b.json"
        )

    def test_paths_are_resolved_before_keying(self, tmp_path: Path) -> None:
        locks = PathLocks()
        assert locks.for_path(tmp_path / "c.json") is locks.for_path(
            tmp_path / "." / "c.json"
        )

    def test_locks_are_asyncio_locks(self, tmp_path: Path) -> None:
        assert isinstance(PathLocks().for_path(tmp_path / "x.json"), asyncio.Lock)


class TestJsonServerCatalogRepository:
    @pytest.fixture
    def repository(self, settings: Settings) -> JsonServerCatalogRepository:
        settings.data_dir.mkdir(parents=True, exist_ok=True)
        return JsonServerCatalogRepository(settings)

    def test_default_source_is_servers_json(self, repository, settings) -> None:
        assert repository.default_source() == settings.data_dir / "servers.json"

    def test_ensure_creates_an_empty_catalog(self, repository) -> None:
        source = repository.ensure(repository.default_source())
        assert json.loads(source.read_text()) == {"mcpServers": {}}

    def test_ensure_leaves_an_existing_file_alone(self, repository) -> None:
        source = repository.default_source()
        source.write_text(json.dumps({"mcpServers": {"a": {"url": "http://a"}}}))
        repository.ensure(source)
        assert "a" in json.loads(source.read_text())["mcpServers"]

    def test_missing_file_loads_as_empty(self, repository) -> None:
        assert len(repository.load(repository.default_source())) == 0

    def test_load_parses_the_document(self, repository, servers_json: Path) -> None:
        assert repository.load(servers_json).names == ("alpha", "beta", "gamma")

    def test_corrupt_json_raises(self, repository) -> None:
        source = repository.default_source()
        source.write_text("{ not json")
        with pytest.raises(json.JSONDecodeError):
            repository.load(source)

    def test_save_round_trips(self, repository, servers_json: Path) -> None:
        catalog = repository.load(servers_json).with_server_enabled("alpha", False)
        repository.save(servers_json, catalog)
        assert repository.load(servers_json).get("alpha").enabled is False

    async def test_update_applies_the_transition(self, repository, servers_json) -> None:
        await repository.update(
            servers_json, lambda catalog: catalog.with_server_enabled("alpha", False)
        )
        assert json.loads(servers_json.read_text())["mcpServers"]["alpha"][
            "enabled"
        ] is False

    async def test_update_writes_nothing_when_the_transition_raises(
        self, repository, servers_json: Path
    ) -> None:
        before = servers_json.read_text()
        with pytest.raises(ServerNotFound):
            await repository.update(
                servers_json, lambda catalog: catalog.with_server_enabled("ghost", False)
            )
        assert servers_json.read_text() == before

    async def test_concurrent_updates_compose(self, repository, servers_json) -> None:
        """Both edits must survive — the second must not read a stale catalog."""
        await asyncio.gather(
            repository.update(
                repository.default_source(),
                lambda catalog: catalog.with_server_enabled("alpha", False),
            ),
            repository.update(
                repository.default_source(),
                lambda catalog: catalog.with_tool_enabled("beta", "extra", False),
            ),
        )
        catalog = repository.load(servers_json)
        assert catalog.get("alpha").enabled is False
        assert set(catalog.get("beta").disabled_tools) == {"noisy", "extra"}

    async def test_write_document_is_verbatim(self, repository) -> None:
        source = repository.default_source()
        document = {"mcpServers": {}, "$schema": "https://example.com/s.json"}
        await repository.write_document(source, document)
        assert json.loads(source.read_text()) == document


class TestJsonPresetRepository:
    @pytest.fixture
    def repository(self, settings: Settings) -> JsonPresetRepository:
        return JsonPresetRepository(settings)

    def test_missing_file_loads_as_empty(self, repository) -> None:
        assert repository.load() == PresetBook.empty()

    def test_save_creates_the_data_dir(self, tmp_path: Path) -> None:
        settings = Settings(data_dir=tmp_path / "nested" / "panoply")
        JsonPresetRepository(settings).save(PresetBook.empty())
        assert settings.presets_path.exists()

    def test_round_trip(self, repository) -> None:
        book = PresetBook((Preset("p1", "work", Path("/tmp/w.json")),), "p1")
        repository.save(book)
        assert repository.load() == book


class TestCatalogRepositoryIsAPort:
    def test_satisfies_the_protocol(self, settings: Settings) -> None:
        from panoply.domain.ports.repositories import ServerCatalogRepository

        assert isinstance(JsonServerCatalogRepository(settings), ServerCatalogRepository)

    def test_empty_catalog_serialises_to_an_empty_document(self) -> None:
        assert ServerCatalog.empty().to_payload() == {"mcpServers": {}}
