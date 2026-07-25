"""Integration tests for the CLI entry point.

``main`` is driven with an injected :class:`Settings` so nothing reaches the
real data directory, and each long-running mode is stubbed at its boundary.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from panoply.connector.cli.main import main, run
from panoply.connector.settings import Settings


class TestHelp:
    @pytest.mark.parametrize("argv", [["--help"], ["-h"], ["help"]])
    def test_prints_usage_and_exits_zero(
        self, argv: list[str], settings: Settings, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(argv, settings) == 0
        assert "Usage: panoply" in capsys.readouterr().out

    def test_help_does_not_create_a_data_directory(
        self, settings: Settings, capsys
    ) -> None:
        main(["--help"], settings)
        assert not settings.data_dir.exists()


class TestUsageErrors:
    def test_a_missing_config_file_exits_one(
        self, settings: Settings, tmp_path: Path, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--config", str(tmp_path / "nope.json")], settings) == 1
        assert "config file not found" in capsys.readouterr().err

    def test_a_bad_port_exits_one(
        self, settings: Settings, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["--http", "abc"], settings) == 1
        assert "port number" in capsys.readouterr().err

    def test_an_unknown_command_exits_one(
        self, settings: Settings, capsys: pytest.CaptureFixture[str]
    ) -> None:
        assert main(["wat"], settings) == 1
        assert "unknown command" in capsys.readouterr().err


class TestStdioMode:
    def test_builds_a_proxy_and_runs_it(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        built: list = []

        class FakeProxy:
            server = type("Server", (), {"run": lambda self, **kw: built.append(kw)})()

        monkeypatch.setattr(
            "panoply.application.proxying.ProxyService.build",
            lambda self, options=None, source=None: built.append(options) or FakeProxy(),
        )
        assert main([], settings) == 0
        assert built[0].name == "panoply"
        assert built[1] == {"show_banner": False}

    def test_code_mode_reaches_the_proxy_options(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: list = []

        class FakeProxy:
            server = type("Server", (), {"run": lambda self, **kw: None})()

        monkeypatch.setattr(
            "panoply.application.proxying.ProxyService.build",
            lambda self, options=None, source=None: captured.append(options)
            or FakeProxy(),
        )
        main(["--code-mode"], settings)
        assert captured[0].code_mode is True


class TestHttpMode:
    def test_hands_the_port_to_the_host(
        self, settings: Settings, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}

        def fake_serve(container, port, *, code_mode=False):
            captured.update(port=port, code_mode=code_mode)

        monkeypatch.setattr("panoply.connector.http.server.serve_http", fake_serve)
        assert main(["--http", "7070"], settings) == 0
        assert captured == {"port": 7070, "code_mode": False}


class TestTuiCommands:
    @pytest.mark.parametrize(
        ("command", "attribute"),
        [("mcp", "MCPManagerApp"), ("auth", "AuthManagerApp")],
    )
    def test_launches_the_right_app(
        self,
        settings: Settings,
        monkeypatch: pytest.MonkeyPatch,
        command: str,
        attribute: str,
    ) -> None:
        launched: list = []
        module = (
            "panoply.connector.tui.mcp_manager"
            if command == "mcp"
            else "panoply.connector.tui.auth_manager"
        )

        class FakeApp:
            def __init__(self, container, source) -> None:
                launched.append(source)

            def run(self) -> None:
                launched.append("ran")

        monkeypatch.setattr(f"{module}.{attribute}", FakeApp)
        assert main([command], settings) == 0
        assert launched[1] == "ran"

    def test_an_explicit_config_wins_over_the_active_preset(
        self, settings: Settings, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        chosen = tmp_path / "custom.json"
        chosen.write_text(json.dumps({"mcpServers": {}}))
        launched: list[Path] = []

        class FakeApp:
            def __init__(self, container, source) -> None:
                launched.append(source)

            def run(self) -> None:
                pass

        monkeypatch.setattr(
            "panoply.connector.tui.mcp_manager.MCPManagerApp", FakeApp
        )
        main(["--config", str(chosen), "mcp"], settings)
        assert launched == [chosen]


class TestModuleEntryPoint:
    def test_run_raises_system_exit(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("panoply.connector.cli.main.main", lambda: 3)
        with pytest.raises(SystemExit) as caught:
            run()
        assert caught.value.code == 3
