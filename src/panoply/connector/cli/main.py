"""``panoply`` — the process entry point."""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence

from panoply.connector.cli.arguments import USAGE, Arguments, UsageError
from panoply.connector.container import Container
from panoply.connector.logs import configure_logging
from panoply.connector.settings import Settings
from panoply.domain.ports.proxy import ProxyOptions

log = logging.getLogger("panoply")


def main(argv: Sequence[str] | None = None, settings: Settings | None = None) -> int:
    """Parse the command line, wire the app, run whatever was asked for.

    *settings* is an injection point: pass one to run against somewhere other
    than the user's real data directory.
    """
    try:
        arguments = Arguments.parse(sys.argv[1:] if argv is None else argv)
    except UsageError as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1

    if arguments.help:
        print(USAGE)
        return 0

    configure_logging()
    container = Container.build(settings or Settings.from_environment())

    # Priority: --config  >  the active preset  >  the default document.
    source = arguments.config or container.configuration.active_source()

    if arguments.command == "mcp":
        from panoply.connector.tui.mcp_manager import MCPManagerApp

        MCPManagerApp(container, source).run()
        return 0

    if arguments.command == "auth":
        from panoply.connector.tui.auth_manager import AuthManagerApp

        AuthManagerApp(container, source).run()
        return 0

    if arguments.command is not None:
        print(f"Error: unknown command '{arguments.command}'", file=sys.stderr)
        print(USAGE, file=sys.stderr)
        return 1

    if arguments.http_port is not None:
        from panoply.connector.http.server import serve_http

        serve_http(
            container,
            arguments.http_port,
            source=arguments.config,
            code_mode=arguments.code_mode,
        )
        return 0

    proxy = container.proxy.build(
        ProxyOptions(name="panoply", code_mode=arguments.code_mode), source
    )
    log.info("Starting stdio mode")
    proxy.server.run(show_banner=False)
    return 0


def run() -> None:
    """Console-script shim."""
    raise SystemExit(main())
