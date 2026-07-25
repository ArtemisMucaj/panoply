"""Panoply — an MCP proxy that fronts many servers with three tools.

Layered domain-first:

``panoply.domain``       the model, its rules, and the ports it needs
``panoply.application``  use cases orchestrating the domain through ports
``panoply.connector``    adapters — FastMCP, Starlette, Textual, the filesystem

Dependencies point inwards only: connector → application → domain.

The version lives only in ``pyproject.toml`` — release-please bumps it there,
and a second copy here would silently drift.
"""
