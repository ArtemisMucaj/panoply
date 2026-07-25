"""Command-line parsing, kept separate from anything it starts.

Hand-rolled rather than argparse so ``--config`` can precede the subcommand
and the error messages stay stable for the desktop app that shells out here.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from pathlib import Path

USAGE = """Usage: panoply [--config PATH] [COMMAND] [OPTIONS]

Commands:
  mcp               Browse and toggle MCP servers and tools (TUI)
  auth              Manage OAuth authentication for MCP servers (TUI)

Options:
  --config PATH     Use a specific config file
  --http PORT       Run as an HTTP server on PORT (management UI)
  --code-mode       Enable code mode transform
  --help, -h        Show this message and exit

With no command or options, runs as a stdio MCP server.

HTTP mode:
  MCP endpoint:     http://HOST:PORT/mcp           (no skills)
                    http://HOST:PORT/mcp?skills=true (skills mounted)
  Management API:   http://HOST:(PORT+1)/api/...
  Preset activation, server toggles, and tool toggles hot-swap the
  active config live — connected clients keep their sessions."""

MIN_PORT = 1
MAX_PORT = 65534


class UsageError(Exception):
    """The command line doesn't make sense; the message is user-facing."""


@dataclass(frozen=True)
class Arguments:
    """A parsed command line."""

    command: str | None = None
    config: Path | None = None
    http_port: int | None = None
    code_mode: bool = False
    help: bool = False

    @classmethod
    def parse(cls, argv: Sequence[str]) -> Arguments:
        argv = list(argv)
        config: Path | None = None
        http_port: int | None = None
        positional: list[str] = []

        index = 0
        while index < len(argv):
            argument = argv[index]
            if argument == "--config":
                config = _require_path(argv, index)
                index += 2
            elif argument == "--http":
                http_port = _require_port(argv, index)
                index += 2
            elif not argument.startswith("-"):
                positional.append(argument)
                index += 1
            else:
                index += 1

        command = positional[0] if positional else None
        wants_help = command == "help" or "--help" in argv or "-h" in argv
        return cls(
            command=None if command == "help" else command,
            config=config,
            http_port=http_port,
            code_mode="--code-mode" in argv,
            help=wants_help,
        )


def _require_path(argv: list[str], index: int) -> Path:
    if index + 1 >= len(argv):
        raise UsageError("--config requires a path argument")
    path = Path(argv[index + 1])
    if not path.exists():
        raise UsageError(f"config file not found: {argv[index + 1]}")
    return path


def _require_port(argv: list[str], index: int) -> int:
    value = argv[index + 1] if index + 1 < len(argv) else ""
    if not value.isdigit():
        raise UsageError(f"--http requires a port number ({MIN_PORT}..{MAX_PORT})")
    port = int(value)
    if not MIN_PORT <= port <= MAX_PORT:
        raise UsageError(
            f"port must be between {MIN_PORT} and {MAX_PORT}, got {port}"
        )
    return port
