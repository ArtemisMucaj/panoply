"""Connector layer — everything that touches the outside world.

Driven adapters (persistence, MCP clients, the credential store) implement the
domain's ports; driving adapters (CLI, HTTP, TUI) call the application's use
cases.  Frameworks live here and nowhere else.
"""

from panoply.connector.container import Container
from panoply.connector.settings import Settings

__all__ = ["Container", "Settings"]
