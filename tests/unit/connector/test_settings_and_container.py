"""Unit tests for :class:`Settings`, the container, and the CLI parser."""

from __future__ import annotations

from pathlib import Path

import pytest

from panoply.connector.cli.arguments import Arguments, UsageError
from panoply.connector.container import Container
from panoply.connector.settings import DEFAULT_DATA_DIR, Settings


class TestSettings:
    def test_defaults_to_the_home_directory(self) -> None:
        assert Settings.from_environment({}).data_dir == DEFAULT_DATA_DIR

    def test_environment_override(self, tmp_path: Path) -> None:
        settings = Settings.from_environment({"PANOPLY_DATA_DIR": str(tmp_path)})
        assert settings.data_dir == tmp_path

    def test_derived_paths(self, tmp_path: Path) -> None:
        settings = Settings(data_dir=tmp_path)
        assert settings.presets_path == tmp_path / "presets.json"
        assert settings.default_catalog_path == tmp_path / "servers.json"
        assert settings.log_path == tmp_path / "panoply.log"

    def test_missing_skill_dirs_are_filtered_out(self, tmp_path: Path) -> None:
        present = tmp_path / "skills"
        present.mkdir()
        settings = Settings(
            data_dir=tmp_path, skill_dirs=(present, tmp_path / "nowhere")
        )
        assert settings.existing_skill_dirs() == [present]


class TestContainer:
    def test_creates_the_data_directory(self, tmp_path: Path) -> None:
        settings = Settings(data_dir=tmp_path / "fresh", skill_dirs=())
        Container.build(settings)
        assert settings.data_dir.is_dir()

    def test_wires_every_use_case(self, container: Container) -> None:
        assert container.configuration and container.preset_service
        assert container.discovery and container.credentials and container.proxy

    def test_services_share_one_event_bus(self, container: Container) -> None:
        """Otherwise a config edit would never reach the running proxy."""
        assert container.configuration.events is container.events
        assert container.preset_service.events is container.events

    def test_stays_inside_its_data_directory(self, container: Container) -> None:
        active = container.configuration.active_source()
        assert active.parent == container.settings.data_dir


class TestArguments:
    def test_no_arguments_means_stdio(self) -> None:
        arguments = Arguments.parse([])
        assert arguments.command is None
        assert arguments.http_port is None
        assert arguments.code_mode is False

    def test_subcommand(self) -> None:
        assert Arguments.parse(["mcp"]).command == "mcp"

    def test_http_port(self) -> None:
        assert Arguments.parse(["--http", "7070"]).http_port == 7070

    def test_code_mode_flag(self) -> None:
        assert Arguments.parse(["--code-mode"]).code_mode is True

    def test_config_before_the_subcommand(self, tmp_path: Path) -> None:
        config = tmp_path / "servers.json"
        config.write_text("{}")
        arguments = Arguments.parse(["--config", str(config), "mcp"])
        assert arguments.config == config
        assert arguments.command == "mcp"

    def test_the_config_path_is_not_mistaken_for_a_subcommand(
        self, tmp_path: Path
    ) -> None:
        config = tmp_path / "servers.json"
        config.write_text("{}")
        assert Arguments.parse(["--config", str(config)]).command is None

    def test_missing_config_file_is_a_usage_error(self, tmp_path: Path) -> None:
        with pytest.raises(UsageError, match="not found"):
            Arguments.parse(["--config", str(tmp_path / "nope.json")])

    def test_config_without_a_value_is_a_usage_error(self) -> None:
        with pytest.raises(UsageError, match="requires a path"):
            Arguments.parse(["--config"])

    @pytest.mark.parametrize("value", ["", "abc", "-1"])
    def test_a_non_numeric_port_is_a_usage_error(self, value: str) -> None:
        argv = ["--http", value] if value else ["--http"]
        with pytest.raises(UsageError, match="requires a port number"):
            Arguments.parse(argv)

    @pytest.mark.parametrize("port", ["0", "65535", "99999"])
    def test_an_out_of_range_port_is_a_usage_error(self, port: str) -> None:
        with pytest.raises(UsageError, match="between"):
            Arguments.parse(["--http", port])

    @pytest.mark.parametrize("argv", [["--help"], ["-h"], ["help"]])
    def test_help_in_all_its_spellings(self, argv: list[str]) -> None:
        arguments = Arguments.parse(argv)
        assert arguments.help is True
        assert arguments.command is None
