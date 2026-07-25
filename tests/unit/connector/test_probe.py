"""Unit tests for :class:`FastMCPToolProbe` and its helpers.

``probe`` opens a real connection, so ``create_proxy`` is stubbed; what is
exercised here is the wiring around it.
"""

from __future__ import annotations

import logging
import socket
import sys
from types import SimpleNamespace

import pytest

from panoply.connector.mcp import probe as probe_module
from panoply.connector.mcp.probe import (
    FastMCPToolProbe,
    SuppressMcpSessionWarning,
    free_port,
    silence,
)
from panoply.connector.settings import Settings
from panoply.domain.model.server import ServerDefinition
from panoply.domain.model.tool import ToolDescriptor

SERVER = ServerDefinition("myserver", {"url": "http://x", "transport": "http"})


class StubTranslator:
    def __init__(self) -> None:
        self.calls: list[tuple[str, int | None]] = []

    def for_server(self, server, *, callback_port=None):
        self.calls.append((server.name, callback_port))
        return SimpleNamespace(mcpServers={server.name: object()})


class TestFreePort:
    def test_is_in_range(self) -> None:
        assert 1 <= free_port() <= 65535

    def test_is_actually_bindable(self) -> None:
        port = free_port()
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
            sock.bind(("127.0.0.1", port))

    def test_does_not_return_a_constant(self) -> None:
        assert len({free_port() for _ in range(5)}) > 1


class TestSuppressMcpSessionWarning:
    def _record(self, exc: BaseException | None) -> logging.LogRecord:
        return logging.LogRecord(
            name="fastmcp.client.transports.config",
            level=logging.WARNING,
            pathname=__file__,
            lineno=1,
            msg="Failed to connect",
            args=(),
            exc_info=(type(exc), exc, None) if exc else None,
        )

    def test_demotes_mcp_errors_to_debug(self) -> None:
        from mcp import McpError
        from mcp.types import ErrorData

        record = self._record(McpError(ErrorData(code=-32000, message="boom")))
        assert SuppressMcpSessionWarning().filter(record) is True
        assert record.levelno == logging.DEBUG
        assert record.levelname == "DEBUG"

    def test_leaves_other_warnings_alone(self) -> None:
        record = self._record(RuntimeError("unrelated"))
        assert SuppressMcpSessionWarning().filter(record) is True
        assert record.levelno == logging.WARNING

    def test_leaves_warnings_without_exceptions_alone(self) -> None:
        record = self._record(None)
        assert SuppressMcpSessionWarning().filter(record) is True
        assert record.levelno == logging.WARNING


class TestSilence:
    def test_redirects_stderr_and_restores_it(self, settings: Settings) -> None:
        original = sys.stderr
        with silence(settings.log_path):
            assert sys.stderr is not original
            print("swallowed", file=sys.stderr)
        assert sys.stderr is original
        assert "swallowed" in settings.log_path.read_text()

    def test_creates_the_log_directory(self, settings: Settings) -> None:
        with silence(settings.log_path):
            pass
        assert settings.log_path.exists()

    def test_removes_its_log_handler(self, settings: Settings) -> None:
        root = logging.getLogger()
        before = list(root.handlers)
        with silence(settings.log_path):
            assert len(root.handlers) == len(before) + 1
        assert list(root.handlers) == before

    def test_cleans_up_on_exception(self, settings: Settings) -> None:
        original = sys.stderr
        before = list(logging.getLogger().handlers)
        with pytest.raises(RuntimeError, match="boom"):
            with silence(settings.log_path):
                raise RuntimeError("boom")
        assert sys.stderr is original
        assert list(logging.getLogger().handlers) == before


class TestProbe:
    @pytest.fixture
    def translator(self) -> StubTranslator:
        return StubTranslator()

    @pytest.fixture
    def probe(self, translator: StubTranslator, settings: Settings) -> FastMCPToolProbe:
        return FastMCPToolProbe(translator, settings)

    def _stub_proxy(self, monkeypatch: pytest.MonkeyPatch, tools, captured=None):
        class FakeProxy:
            async def list_tools(self):
                if isinstance(tools, BaseException):
                    raise tools
                return tools

        def fake_create_proxy(config, *, name: str):
            if captured is not None:
                captured["name"] = name
                captured["config"] = config
            return FakeProxy()

        monkeypatch.setattr(probe_module, "create_proxy", fake_create_proxy)

    async def test_strips_the_server_prefix(
        self, probe, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._stub_proxy(
            monkeypatch,
            [
                SimpleNamespace(name="myserver_alpha", description="first"),
                SimpleNamespace(name="myserver_beta", description=None),
                SimpleNamespace(name="unprefixed", description="c"),
            ],
        )
        assert await probe.probe(SERVER) == [
            ToolDescriptor("alpha", "first"),
            ToolDescriptor("beta", ""),
            ToolDescriptor("unprefixed", "c"),
        ]

    async def test_names_the_proxy_after_the_server(
        self, probe, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        captured: dict = {}
        self._stub_proxy(monkeypatch, [], captured)
        await probe.probe(SERVER)
        assert captured["name"] == "probe_myserver"

    async def test_uses_a_free_callback_port(
        self, probe, translator, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The long-running server may already own the shared OAuth port."""
        self._stub_proxy(monkeypatch, [])
        monkeypatch.setattr(probe_module, "free_port", lambda: 55555)
        await probe.probe(SERVER)
        assert translator.calls == [("myserver", 55555)]

    async def test_uvicorn_bailing_out_becomes_an_oserror(
        self, probe, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """SystemExit must not escape and take the whole process with it."""
        self._stub_proxy(monkeypatch, SystemExit(1))
        with pytest.raises(OSError, match="uvicorn exited"):
            await probe.probe(SERVER)

    async def test_satisfies_the_port(self, probe) -> None:
        from panoply.domain.ports.discovery import ToolProbe

        assert isinstance(probe, ToolProbe)
