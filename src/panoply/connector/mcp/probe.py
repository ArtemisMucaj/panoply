"""FastMCP implementation of :class:`ToolProbe`."""

from __future__ import annotations

import contextlib
import logging
import socket
import sys
import threading
from pathlib import Path

from fastmcp.server import create_proxy
from mcp import MCPError

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
    """Demote 'Failed to connect' warnings caused by MCPError to DEBUG.

    A backend that is simply down is an expected outcome of probing, not
    something worth a warning on every listing.
    """

    def filter(self, record: logging.LogRecord) -> bool:
        if record.levelno == logging.WARNING and record.exc_info:
            if isinstance(record.exc_info[1], MCPError):
                record.levelno = logging.DEBUG
                record.levelname = "DEBUG"
        return True


logging.getLogger("fastmcp.client.transports.config").addFilter(
    SuppressMcpSessionWarning()
)


_silence_lock = threading.Lock()
_silence_depth = 0
_silence_saved: tuple | None = None


@contextlib.contextmanager
def silence(log_path: Path):
    """Redirect logging and stderr to the Panoply log file while probing.

    Backend libraries write connection noise straight to stderr, which in
    stdio mode is the channel the client is reading.

    ``sys.stderr`` is process-global and probes run concurrently on one event
    loop, so their exits interleave. Overlapping probes therefore share one
    redirection: the first in swaps the stream, the last out restores it. A
    per-probe save/restore would let a later probe "restore" a file an earlier
    one had already closed, leaving ``sys.stderr`` dead for the process.
    """
    global _silence_depth, _silence_saved
    with _silence_lock:
        if _silence_depth == 0:
            log_path.parent.mkdir(parents=True, exist_ok=True)
            log_file = open(log_path, "a")
            handler = logging.StreamHandler(log_file)
            handler.setLevel(logging.DEBUG)
            logging.root.addHandler(handler)
            _silence_saved = (sys.stderr, log_file, handler)
            sys.stderr = log_file
        _silence_depth += 1
    try:
        yield
    finally:
        with _silence_lock:
            _silence_depth -= 1
            if _silence_depth == 0:
                original, log_file, handler = _silence_saved
                _silence_saved = None
                sys.stderr = original
                logging.root.removeHandler(handler)
                log_file.close()


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
