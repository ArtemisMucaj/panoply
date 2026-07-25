"""Mounting agent skills onto the proxy."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import Sequence

from fastmcp.server import FastMCP

log = logging.getLogger("panoply.skills")


def mount_skills(server: FastMCP, roots: Sequence[Path]) -> None:
    """Expose the skills under *roots* as resources on *server*.

    The provider goes on a dedicated inner server so the resulting
    ``list_resources`` / ``read_resource`` tools are scoped strictly to
    skills — mounted directly they would also surface every other resource on
    the proxy (``datadog://``, ``exa://``, …).
    """
    from fastmcp.server.providers.fastmcp_provider import FastMCPProvider
    from fastmcp.server.providers.skills import SkillsDirectoryProvider
    from fastmcp.server.transforms import ResourcesAsTools

    skills_server = FastMCP("skills")
    skills_server.add_provider(SkillsDirectoryProvider(roots=list(roots)))
    skills_server.add_transform(ResourcesAsTools(skills_server))
    server.add_provider(FastMCPProvider(skills_server))
    log.info("Skills mounted from: %s", ", ".join(str(root) for root in roots))
