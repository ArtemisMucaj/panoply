"""Tests for the skills mount — provider wiring and duplicate handling."""

from __future__ import annotations

from pathlib import Path

from fastmcp import FastMCP
from fastmcp.server.providers.skills import SkillsDirectoryProvider

from panoply.connector.mcp.skills import mount_skills
from panoply.connector.settings import DEFAULT_SKILL_DIRS


def make_skill(parent: Path, name: str, description: str, body: str) -> None:
    skill_dir = parent / name
    skill_dir.mkdir()
    (skill_dir / "SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n{body}"
    )


class TestDefaultSkillDirs:
    def test_agents_then_claude(self) -> None:
        assert DEFAULT_SKILL_DIRS == (
            Path.home() / ".agents" / "skills",
            Path.home() / ".claude" / "skills",
        )


class TestSkillsProvider:
    async def test_skills_are_listed_as_resources(self, tmp_path: Path) -> None:
        make_skill(tmp_path, "alpha-skill", "Does alpha", "# Alpha")
        make_skill(tmp_path, "beta-skill", "Does beta", "# Beta")

        server = FastMCP("test")
        server.add_provider(SkillsDirectoryProvider(roots=tmp_path))

        uris = {str(r.uri) for r in await server._list_resources()}
        assert "skill://alpha-skill/SKILL.md" in uris
        assert "skill://beta-skill/SKILL.md" in uris

    async def test_the_first_root_wins_for_duplicate_names(
        self, tmp_path: Path
    ) -> None:
        first, second = tmp_path / "d1", tmp_path / "d2"
        first.mkdir()
        second.mkdir()
        make_skill(first, "shared", "From d1", "# From d1")
        make_skill(second, "shared", "From d2", "# From d2")
        make_skill(first, "only-in-d1", "Only d1", "# d1")
        make_skill(second, "only-in-d2", "Only d2", "# d2")

        server = FastMCP("test")
        server.add_provider(SkillsDirectoryProvider(roots=[first, second]))

        uris = [
            str(r.uri)
            for r in await server._list_resources()
            if str(r.uri).endswith("/SKILL.md")
        ]
        assert sorted(uris) == [
            "skill://only-in-d1/SKILL.md",
            "skill://only-in-d2/SKILL.md",
            "skill://shared/SKILL.md",
        ]
        result = await server.read_resource("skill://shared/SKILL.md")
        assert "From d1" in result.contents[0].content


class TestMountSkills:
    async def test_resources_are_exposed_as_tools(self, tmp_path: Path) -> None:
        """The mount scopes list_resources / read_resource to skills only."""
        make_skill(tmp_path, "alpha-skill", "Does alpha", "# Alpha")

        server = FastMCP("test")
        mount_skills(server, [tmp_path])

        names = {tool.name for tool in await server._list_tools()}
        assert {"list_resources", "read_resource"} <= names
