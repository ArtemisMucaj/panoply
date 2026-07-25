"""Composition root.

The one place that knows every concrete adapter.  Everything else receives
what it needs, which is why a test can build the whole application against a
temp directory in one line.
"""

from __future__ import annotations

from dataclasses import dataclass

from panoply.application.configuration import ConfigurationService
from panoply.application.credentials import CredentialsService
from panoply.application.discovery import DiscoveryService
from panoply.application.events import ConfigurationEvents
from panoply.application.presets import PresetService
from panoply.application.proxying import ProxyService
from panoply.connector.mcp.probe import FastMCPToolProbe
from panoply.connector.mcp.proxy_factory import FastMCPProxyFactory
from panoply.connector.mcp.translator import MCPConfigTranslator
from panoply.connector.persistence.catalog_repository import JsonServerCatalogRepository
from panoply.connector.persistence.credential_store import DiskCredentialStore
from panoply.connector.persistence.preset_repository import JsonPresetRepository
from panoply.connector.settings import Settings


@dataclass(frozen=True)
class Container:
    """The wired application: settings, ports and use cases."""

    settings: Settings
    events: ConfigurationEvents
    catalogs: JsonServerCatalogRepository
    presets: JsonPresetRepository
    credential_store: DiskCredentialStore
    configuration: ConfigurationService
    preset_service: PresetService
    discovery: DiscoveryService
    credentials: CredentialsService
    proxy: ProxyService

    @classmethod
    def build(cls, settings: Settings | None = None) -> Container:
        settings = settings or Settings.from_environment()
        settings.data_dir.mkdir(parents=True, exist_ok=True)

        events = ConfigurationEvents()
        catalogs = JsonServerCatalogRepository(settings)
        presets = JsonPresetRepository(settings)
        credential_store = DiskCredentialStore(settings)

        translator = MCPConfigTranslator(credential_store, settings)
        probe = FastMCPToolProbe(translator, settings)

        configuration = ConfigurationService(catalogs, presets, events)
        credentials = CredentialsService(
            credential_store, probe, refresh_timeout=settings.refresh_timeout
        )
        return cls(
            settings=settings,
            events=events,
            catalogs=catalogs,
            presets=presets,
            credential_store=credential_store,
            configuration=configuration,
            preset_service=PresetService(presets, events),
            discovery=DiscoveryService(
                probe, configuration, timeout=settings.probe_timeout
            ),
            credentials=credentials,
            proxy=ProxyService(
                FastMCPProxyFactory(translator, credentials, settings), configuration
            ),
        )
