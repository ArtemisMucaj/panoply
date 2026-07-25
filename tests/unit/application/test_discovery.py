"""Unit tests for :class:`DiscoveryService`."""

from __future__ import annotations

import asyncio
import logging

import pytest

from panoply.application.discovery import PROPAGATE, DiscoveryService
from panoply.domain.model.server import ServerDefinition
from panoply.domain.model.tool import ToolDescriptor

from .conftest import ScriptedProbe


def make_service(probe: ScriptedProbe, configuration, timeout: float = 30) -> DiscoveryService:
    return DiscoveryService(probe, configuration, timeout=timeout)


class TestCatalogue:
    async def test_returns_tools_per_server(self, configuration) -> None:
        probe = ScriptedProbe({"alpha": ["one"], "beta": ["two", "three"]})
        catalogue = await make_service(probe, configuration).catalogue()
        assert catalogue == {
            "alpha": [ToolDescriptor("one")],
            "beta": [ToolDescriptor("two"), ToolDescriptor("three")],
        }

    async def test_skips_disabled_servers(self, configuration) -> None:
        probe = ScriptedProbe()
        catalogue = await make_service(probe, configuration).catalogue()
        assert "gamma" not in catalogue
        assert "gamma" not in probe.calls

    async def test_empty_catalog_probes_nothing(self, configuration, catalogs) -> None:
        catalogs.documents.clear()
        probe = ScriptedProbe()
        assert await make_service(probe, configuration).catalogue() == {}

    async def test_one_failure_does_not_sink_the_rest(self, configuration) -> None:
        probe = ScriptedProbe({"alpha": RuntimeError("boom"), "beta": ["ok"]})
        catalogue = await make_service(probe, configuration).catalogue()
        assert catalogue == {"alpha": [], "beta": [ToolDescriptor("ok")]}

    async def test_slow_server_times_out_to_empty(self, configuration) -> None:
        async def hang() -> list[ToolDescriptor]:
            await asyncio.sleep(10)
            return []

        probe = ScriptedProbe({"alpha": hang, "beta": ["ok"]})
        service = make_service(probe, configuration, timeout=0.05)
        assert (await service.catalogue())["alpha"] == []

    async def test_exotic_base_exception_is_still_contained(
        self, configuration
    ) -> None:
        class Weird(BaseException):
            pass

        probe = ScriptedProbe({"alpha": Weird("weird"), "beta": []})
        assert (await make_service(probe, configuration).catalogue())["alpha"] == []

    async def test_cancellation_is_not_swallowed(self, configuration) -> None:
        """A cancelled probe must stay cancelled.

        Downgrading it to "this server has no tools" would make the task ignore
        its own cancellation: a client that disconnects mid-request, or a
        shutdown, would wait out the full timeout and still get a result.
        """
        probe = ScriptedProbe({"alpha": asyncio.CancelledError()})
        service = make_service(probe, configuration)
        with pytest.raises(asyncio.CancelledError):
            await service.inspect_safely(ServerDefinition("alpha", {"url": "http://a"}))

    def test_shutdown_signals_are_declared_as_propagating(self) -> None:
        """Asserted rather than exercised on purpose.

        Raising `KeyboardInterrupt` or `SystemExit` inside an async test escapes
        `pytest.raises` on Python 3.11 (a `wait_for` internals difference) and
        aborts the whole session — it passed on 3.12 and broke CI. See AGENTS.md.
        """
        assert {SystemExit, KeyboardInterrupt, GeneratorExit} <= set(PROPAGATE)

    async def test_failure_is_logged_with_the_server_name(
        self, configuration, caplog: pytest.LogCaptureFixture
    ) -> None:
        probe = ScriptedProbe({"alpha": ValueError("bad things")})
        with caplog.at_level(logging.WARNING, logger="panoply.discovery"):
            await make_service(probe, configuration).catalogue()
        assert "[alpha]" in caplog.text
        assert "ValueError" in caplog.text
        assert "bad things" in caplog.text


class TestInspect:
    async def test_surfaces_failures_to_the_caller(self, configuration) -> None:
        """Unlike the catalogue, a direct probe must not swallow the error."""
        probe = ScriptedProbe({"alpha": RuntimeError("nope")})
        service = make_service(probe, configuration)
        with pytest.raises(RuntimeError, match="nope"):
            await service.inspect(ServerDefinition("alpha", {"url": "http://a"}))
