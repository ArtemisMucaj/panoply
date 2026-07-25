"""Domain layer — what Panoply is, expressed without any framework.

Nothing under ``panoply.domain`` may import FastMCP, Starlette, Textual, or
touch the filesystem, the network, or the clock.  It holds the model (servers,
catalogs, presets, tools), the policies that decide things about them, and the
ports through which the outside world is reached.
"""
