"""Ports for the running proxy.

The domain describes the proxy as "something that serves a catalog and can
hide individual tools".  Which MCP library provides it is a connector detail.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol, runtime_checkable

from panoply.domain.model.catalog import ServerCatalog


@dataclass(frozen=True)
class ProxyOptions:
    """How one proxy instance should be assembled."""

    name: str = "panoply"
    #: Mount the skills provider and expose its resources as tools.
    skills: bool = False
    #: Swap tool search for the sandboxed code-execution transform.
    code_mode: bool = False


@runtime_checkable
class ProxyServer(Protocol):
    """A built proxy whose tool visibility can be changed while it runs."""

    def enable_tool(self, qualified_name: str) -> None: ...

    def disable_tool(self, qualified_name: str) -> None: ...


@runtime_checkable
class ProxyFactory(Protocol):
    def create(self, catalog: ServerCatalog, options: ProxyOptions) -> ProxyServer: ...
