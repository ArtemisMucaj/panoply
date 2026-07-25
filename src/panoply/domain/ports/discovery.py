"""Port for asking a backend server what tools it has."""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from panoply.domain.model.server import ServerDefinition
from panoply.domain.model.tool import ToolDescriptor


@runtime_checkable
class ToolProbe(Protocol):
    """Connects to one backend and lists its tools.

    Implementations open a real connection, so they double as the trigger for
    an OAuth handshake: probing a server with expired credentials is what
    makes the client exchange its refresh token.
    """

    async def probe(self, server: ServerDefinition) -> list[ToolDescriptor]: ...
