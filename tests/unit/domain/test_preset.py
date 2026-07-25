"""Unit tests for :class:`Preset` and :class:`PresetBook`."""

from __future__ import annotations

from pathlib import Path

import pytest

from panoply.domain.errors import InvalidConfiguration, PresetNotFound
from panoply.domain.model.preset import Preset, PresetBook


def make_book() -> PresetBook:
    return PresetBook(
        (
            Preset("p1", "work", Path("/tmp/work.json")),
            Preset("p2", "home", Path("/tmp/home.json")),
        ),
        active_id="p1",
    )


class TestPreset:
    def test_round_trip(self) -> None:
        payload = {"id": "p1", "name": "work", "filePath": "/tmp/work.json"}
        assert Preset.from_payload(payload).to_payload() == payload

    def test_unknown_fields_survive(self) -> None:
        payload = {"id": "p1", "name": "w", "filePath": "/f.json", "colour": "red"}
        assert Preset.from_payload(payload).to_payload()["colour"] == "red"

    def test_missing_filePath_falls_back_to_servers_json(
        self,
    ) -> None:
        preset = Preset.from_payload({"id": "p1", "name": "w"})
        assert preset.file_path == Path("servers.json")

    def test_missing_id_and_name_are_empty_strings(self) -> None:
        preset = Preset.from_payload({"filePath": "/f.json"})
        assert preset.id == ""
        assert preset.name == ""

    def test_non_object_is_invalid(self) -> None:
        with pytest.raises(InvalidConfiguration):
            Preset.from_payload("nope")

    def test_renamed_keeps_path(self) -> None:
        preset = Preset("p1", "old", Path("/f.json")).renamed("new")
        assert (preset.name, preset.file_path) == ("new", Path("/f.json"))

    def test_relocated_keeps_name(self) -> None:
        preset = Preset("p1", "w", Path("/a.json")).relocated(Path("/b.json"))
        assert (preset.name, preset.file_path) == ("w", Path("/b.json"))


class TestPresetBook:
    def test_empty_payload_shape(self) -> None:
        assert PresetBook.empty().to_payload() == {"presets": [], "activePresetID": None}

    def test_missing_file_shape_round_trips(self) -> None:
        book = PresetBook.from_payload({"presets": [], "activePresetID": None})
        assert len(book) == 0 and book.active is None

    def test_rejects_non_object(self) -> None:
        with pytest.raises(InvalidConfiguration):
            PresetBook.from_payload([])

    def test_rejects_non_list_presets(self) -> None:
        with pytest.raises(InvalidConfiguration):
            PresetBook.from_payload({"presets": {}})

    def test_active_resolves_to_the_preset(self) -> None:
        assert make_book().active.name == "work"

    def test_active_is_none_when_unset(self) -> None:
        assert PresetBook.empty().active is None

    def test_active_id_pointing_at_nothing_resolves_to_none(self) -> None:
        book = PresetBook((Preset("p1", "w", Path("/f")),), active_id="ghost")
        assert book.active is None

    def test_added_appends(self) -> None:
        book = make_book().added(Preset("p3", "third", Path("/t.json")))
        assert [p.id for p in book] == ["p1", "p2", "p3"]

    def test_replaced_keeps_position(self) -> None:
        book = make_book().replaced(Preset("p1", "renamed", Path("/w.json")))
        assert [p.name for p in book] == ["renamed", "home"]

    def test_replaced_unknown_raises(self) -> None:
        with pytest.raises(PresetNotFound):
            make_book().replaced(Preset("ghost", "x", Path("/x")))

    def test_removed_drops_it(self) -> None:
        assert [p.id for p in make_book().removed("p2")] == ["p1"]

    def test_removing_the_active_one_clears_active(self) -> None:
        assert make_book().removed("p1").active_id is None

    def test_removing_an_inactive_one_keeps_active(self) -> None:
        assert make_book().removed("p2").active_id == "p1"

    def test_removed_unknown_raises(self) -> None:
        with pytest.raises(PresetNotFound):
            make_book().removed("ghost")

    def test_activated_switches(self) -> None:
        assert make_book().activated("p2").active_id == "p2"

    def test_activated_none_reverts_to_default(self) -> None:
        assert make_book().activated(None).active_id is None

    def test_activated_unknown_raises(self) -> None:
        with pytest.raises(PresetNotFound):
            make_book().activated("ghost")

    def test_transitions_do_not_mutate(self) -> None:
        book = make_book()
        book.removed("p1")
        assert book.active_id == "p1"
