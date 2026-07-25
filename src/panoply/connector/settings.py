"""Everything Panoply needs to know about the machine it runs on.

Resolved once at start-up and passed down; nothing reads the environment
behind the container's back, which is what makes a test able to point the
whole app at a temp directory.
"""

from __future__ import annotations

import os
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path

DATA_DIR_ENV = "PANOPLY_DATA_DIR"
DEFAULT_DATA_DIR = Path.home() / ".panoply"

#: Where agent skills are looked for, in precedence order.
DEFAULT_SKILL_DIRS = (
    Path.home() / ".agents" / "skills",
    Path.home() / ".claude" / "skills",
)


@dataclass(frozen=True)
class Settings:
    """Paths, ports and timeouts for one Panoply process."""

    data_dir: Path = DEFAULT_DATA_DIR
    skill_dirs: tuple[Path, ...] = field(default=DEFAULT_SKILL_DIRS)

    #: Fixed port the long-running server's OAuth callbacks land on.
    oauth_callback_port: int = 9876
    oauth_client_name: str = "Panoply Proxy"

    #: Seconds a backend gets to complete its initial handshake.  Without a
    #: cap, one unreachable server (an SSL handshake hanging behind a
    #: corporate proxy) blocks the entire tools/list response indefinitely.
    backend_init_timeout: float = 10.0
    probe_timeout: float = 30.0
    refresh_timeout: float = 5.0

    #: How many tools ``search_tools`` returns per query.
    search_results: int = 5

    @classmethod
    def from_environment(cls, environment: Mapping[str, str] | None = None) -> Settings:
        env = os.environ if environment is None else environment
        override = env.get(DATA_DIR_ENV)
        return cls(data_dir=Path(override) if override else DEFAULT_DATA_DIR)

    @property
    def presets_path(self) -> Path:
        return self.data_dir / "presets.json"

    @property
    def default_catalog_path(self) -> Path:
        return self.data_dir / "servers.json"

    @property
    def log_path(self) -> Path:
        return self.data_dir / "panoply.log"

    def existing_skill_dirs(self) -> list[Path]:
        return [directory for directory in self.skill_dirs if directory.is_dir()]
