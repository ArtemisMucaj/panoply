"""Panoply — an MCP proxy that fronts many servers with three tools.

Layered domain-first:

``panoply.domain``       the model, its rules, and the ports it needs
``panoply.application``  use cases orchestrating the domain through ports
``panoply.connector``    adapters — FastMCP, Starlette, Textual, the filesystem

Dependencies point inwards only: connector → application → domain.
"""

__version__ = "0.1.0"
