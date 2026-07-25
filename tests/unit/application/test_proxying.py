"""Unit tests for :class:`ProxyService`."""

from __future__ import annotations

from pathlib import Path

from panoply.application.proxying import ProxyService
from panoply.domain.model.catalog import ServerCatalog
from panoply.domain.ports.proxy import ProxyOptions

from .conftest import DEFAULT_SOURCE


class RecordingFactory:
    def __init__(self) -> None:
        self.calls: list[tuple[ServerCatalog, ProxyOptions]] = []

    def create(self, catalog: ServerCatalog, options: ProxyOptions) -> object:
        self.calls.append((catalog, options))
        return object()


class TestBuild:
    def test_passes_the_active_catalog_to_the_factory(self, configuration) -> None:
        factory = RecordingFactory()
        ProxyService(factory, configuration).build()
        catalog, _ = factory.calls[0]
        assert catalog.names == ("alpha", "beta", "gamma")

    def test_defaults_the_options(self, configuration) -> None:
        factory = RecordingFactory()
        ProxyService(factory, configuration).build()
        _, options = factory.calls[0]
        assert options == ProxyOptions()

    def test_forwards_the_options(self, configuration) -> None:
        factory = RecordingFactory()
        options = ProxyOptions(name="panoply-proxy", skills=True, code_mode=True)
        ProxyService(factory, configuration).build(options)
        assert factory.calls[0][1] is options

    def test_an_explicit_source_wins(self, configuration, catalogs) -> None:
        other = Path("/memory/other.json")
        catalogs.documents[other] = {"mcpServers": {"solo": {"url": "http://s"}}}
        factory = RecordingFactory()
        ProxyService(factory, configuration).build(source=other)
        assert factory.calls[0][0].names == ("solo",)

    def test_returns_what_the_factory_built(self, configuration) -> None:
        factory = RecordingFactory()
        built = ProxyService(factory, configuration).build()
        assert built is not None

    def test_uses_the_default_source_when_none_given(self, configuration) -> None:
        factory = RecordingFactory()
        ProxyService(factory, configuration).build()
        assert configuration.active_source() == DEFAULT_SOURCE
