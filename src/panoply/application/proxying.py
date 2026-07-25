"""Use case for assembling the proxy that fronts the catalog."""

from __future__ import annotations

import logging
from pathlib import Path

from panoply.application.configuration import ConfigurationService
from panoply.domain.ports.proxy import ProxyFactory, ProxyOptions, ProxyServer

log = logging.getLogger("panoply.proxy")


class ProxyService:
    """Builds a proxy from whichever catalog is currently active."""

    def __init__(
        self, factory: ProxyFactory, configuration: ConfigurationService
    ) -> None:
        self.factory = factory
        self.configuration = configuration

    def build(
        self,
        options: ProxyOptions | None = None,
        source: Path | None = None,
    ) -> ProxyServer:
        resolved = self.configuration.resolve(source)
        catalog = self.configuration.load_catalog(resolved)
        names = catalog.names
        log.info(
            "Loading config %s — %d server(s): %s",
            resolved,
            len(names),
            ", ".join(names) or "(none)",
        )
        return self.factory.create(catalog, options or ProxyOptions())
