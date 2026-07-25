"""Unit tests for :class:`PresetService`."""

from __future__ import annotations

import itertools
from pathlib import Path

import pytest

from panoply.application.presets import PresetService
from panoply.domain.errors import PresetNotFound


@pytest.fixture
def service(presets, events) -> PresetService:
    counter = itertools.count(1)
    return PresetService(presets, events, identifiers=lambda: f"id-{next(counter)}")


class TestCreate:
    def test_returns_a_preset_with_a_generated_id(self, service: PresetService) -> None:
        preset = service.create("work", "/tmp/work.json")
        assert (preset.id, preset.name, preset.file_path) == (
            "id-1",
            "work",
            Path("/tmp/work.json"),
        )

    def test_appears_in_the_book(self, service: PresetService) -> None:
        service.create("work", "/tmp/work.json")
        assert [p.name for p in service.book()] == ["work"]

    def test_does_not_publish(self, service: PresetService, events) -> None:
        """A new preset changes nothing until it is activated."""
        service.create("work", "/tmp/work.json")
        assert events.changes == 0


class TestUpdate:
    def test_renames(self, service: PresetService) -> None:
        created = service.create("work", "/tmp/work.json")
        assert service.update(created.id, name="renamed").name == "renamed"

    def test_rename_alone_does_not_publish(self, service: PresetService, events) -> None:
        created = service.create("work", "/tmp/work.json")
        service.activate(created.id)
        events.changes = 0
        service.update(created.id, name="renamed")
        assert events.changes == 0

    def test_repointing_the_active_preset_publishes(
        self, service: PresetService, events
    ) -> None:
        created = service.create("work", "/tmp/work.json")
        service.activate(created.id)
        events.changes = 0
        service.update(created.id, file_path="/tmp/other.json")
        assert events.changes == 1

    def test_repointing_an_inactive_preset_does_not_publish(
        self, service: PresetService, events
    ) -> None:
        created = service.create("work", "/tmp/work.json")
        service.update(created.id, file_path="/tmp/other.json")
        assert events.changes == 0

    def test_unknown_preset_raises(self, service: PresetService) -> None:
        with pytest.raises(PresetNotFound):
            service.update("ghost", name="x")


class TestDelete:
    def test_removes_it(self, service: PresetService) -> None:
        created = service.create("work", "/tmp/work.json")
        service.delete(created.id)
        assert len(service.book()) == 0

    def test_deleting_the_active_one_publishes(
        self, service: PresetService, events
    ) -> None:
        created = service.create("work", "/tmp/work.json")
        service.activate(created.id)
        events.changes = 0
        service.delete(created.id)
        assert events.changes == 1

    def test_deleting_an_inactive_one_does_not_publish(
        self, service: PresetService, events
    ) -> None:
        created = service.create("work", "/tmp/work.json")
        service.delete(created.id)
        assert events.changes == 0

    def test_unknown_preset_raises(self, service: PresetService) -> None:
        with pytest.raises(PresetNotFound):
            service.delete("ghost")


class TestActivate:
    def test_sets_the_active_id(self, service: PresetService) -> None:
        created = service.create("work", "/tmp/work.json")
        assert service.activate(created.id) == created.id

    def test_none_reverts_to_the_default(self, service: PresetService) -> None:
        created = service.create("work", "/tmp/work.json")
        service.activate(created.id)
        assert service.activate(None) is None

    def test_always_publishes(self, service: PresetService, events) -> None:
        created = service.create("work", "/tmp/work.json")
        service.activate(created.id)
        service.activate(None)
        assert events.changes == 2

    def test_unknown_preset_raises(self, service: PresetService) -> None:
        with pytest.raises(PresetNotFound):
            service.activate("ghost")
