"""Shared fixtures.

Isolation is structural rather than a monkeypatch dance: every test builds its
own :class:`Container` from a :class:`Settings` pointing at ``tmp_path``, so
nothing can reach the real ``~/.panoply``.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from panoply.connector.container import Container
from panoply.connector.settings import Settings

SERVERS = {
    "mcpServers": {
        "alpha": {
            "url": "https://alpha.example.com/mcp",
            "transport": "http",
        },
        "beta": {
            "command": "echo",
            "args": ["hello"],
            "disabledTools": ["noisy"],
        },
        "gamma": {
            "url": "https://gamma.example.com/mcp",
            "transport": "http",
            "enabled": False,
        },
    }
}


@pytest.fixture
def settings(tmp_path: Path) -> Settings:
    """Settings rooted in an isolated data dir with no skill directories."""
    return Settings(data_dir=tmp_path / "panoply", skill_dirs=())


@pytest.fixture
def data_dir(settings: Settings) -> Path:
    settings.data_dir.mkdir(parents=True, exist_ok=True)
    return settings.data_dir


@pytest.fixture
def container(settings: Settings) -> Container:
    return Container.build(settings)


@pytest.fixture
def servers_json(container: Container) -> Path:
    """A pre-populated default catalog: two enabled servers and one disabled."""
    path = container.settings.default_catalog_path
    path.write_text(json.dumps(SERVERS, indent=2))
    return path
