"""FastMCP implementation of :class:`ToolProbe`."""

from __future__ import annotations

import contextlib
import logging
import socket
import sys
from pathlib import Path

from fastmcp.server import create_proxy
from mcp import McpError

from panoply.connector.mcp.translator import MCPConfigTranslator
from panoply.connector.settings import Settings
from panoply.domain.model.server import ServerDefinition
from panoply.domain.model.tool import ToolDescriptor


def free_port() -> int:
    """Return an available TCP port on localhost."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as sock:
        sock.bind(("127.0.0.1", 0))
        return sock.getsockname()[1]


class SuppressMcpSessionWarning(logging.Filter):
    """Demote 'Failed to connect' warnings caused by McpError to DEBUG.

    A backend that is simply down is an expected outcome of probing, not
    something worth a warning on every listing.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno == logging.WARNING and record.exc_info:
            if isinstance(record.exc_info[1], McpError):
                record.levelno = logging.DEBUG
                record.levelname = "DEBUG"
        return True


logging.getLogger("fastmcp.client.transports.config").addFilter(
    SuppressMcpSessionWarning()
)


@contextlib.contextmanager
def silence(log_path: Path):
    """Redirect logging and stderr to the Panoply log file while probing.

    Backend libraries write connection noise straight to stderr, which in
    stdio mode is the channel the client is reading.
    """
    log_path.parent.mkdir(parents=True, exist_ok=True)
    with open(log_path, "a") as log_file:
        old_stderr = sys.stderr
        sys.stderr = log_file
        handler = logging.StreamHandler(log_file)
        handler.setLevel(logging.DEBUG)
        logging.root.addHandler(handler)
        try:
            yield
        finally:
            sys.stderr = old_stderr
            logging.root.removeHandler(handler)


class FastMCPToolProbe:
    """Opens a throwaway connection to one backend and lists its tools."""

    def __init__(self, translator: MCPConfigTranslator, settings: Settings) -> None:
        self.translator = translator
        self.settings = settings

    async def probe(self, server: ServerDefinition) -> list[ToolDescriptor]:
        # A free port rather than the shared OAuth callback port, so probing
        # works even while the main server owns that port.
        config = self.translator.for_server(server, callback_port=free_port())
        proxy = create_proxy(config, name=f"probe_{server.name}")

        with silence(self.settings.log_path):
            try:
                tools = await proxy.list_tools()
            except SystemExit as exc:
                raise OSError(f"probe: uvicorn exited ({exc.code})") from exc

        prefix = f"{server.name}_"
        return [
            ToolDescriptor(tool.name.removeprefix(prefix), tool.description or "")
            for tool in tools
        ]
