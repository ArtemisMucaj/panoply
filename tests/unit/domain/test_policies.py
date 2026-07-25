"""Unit tests for the domain policies and the environment expander."""

from __future__ import annotations

from panoply.domain.model.catalog import ServerCatalog
from panoply.domain.model.environment import expand_mapping, expand_placeholders
from panoply.domain.policies.authentication import (
    ToolOwnership,
    is_authentication_failure,
)
from panoply.domain.policies.skills import (
    is_skill_resource,
    is_skill_tool,
    wants_skills,
)


class TestExpandPlaceholders:
    def test_substitutes_known_variable(self) -> None:
        assert expand_placeholders("token=${MY_KEY}", {"MY_KEY": "secret"}) == (
            "token=secret"
        )

    def test_leaves_unknown_variable_untouched(self) -> None:
        assert expand_placeholders("x=${NOPE}", {}) == "x=${NOPE}"

    def test_substitutes_multiple_variables(self) -> None:
        assert expand_placeholders("${A}-${B}", {"A": "1", "B": "2"}) == "1-2"

    def test_no_placeholders_is_pass_through(self) -> None:
        assert expand_placeholders("plain value", {}) == "plain value"

    def test_mapping_leaves_non_strings_alone(self) -> None:
        expanded = expand_mapping({"N": 3, "T": "${A}"}, {"A": "x"})
        assert expanded == {"N": 3, "T": "x"}


class TestIsAuthenticationFailure:
    def test_detects_401(self) -> None:
        assert is_authentication_failure("GitLab API error: 401 Unauthorized")

    def test_detects_the_word(self) -> None:
        assert is_authentication_failure("Request was Unauthorized")

    def test_is_case_insensitive(self) -> None:
        assert is_authentication_failure("UNAUTHORIZED access")

    def test_ignores_other_statuses(self) -> None:
        assert not is_authentication_failure("404 Not Found")
        assert not is_authentication_failure("Internal server error 500")


class TestToolOwnership:
    def _ownership(self) -> ToolOwnership:
        return ToolOwnership.from_catalog(
            ServerCatalog.from_payload(
                {
                    "mcpServers": {
                        "git": {"command": "git-mcp"},
                        "gitlab": {"url": "http://gl", "auth": "oauth"},
                        "off": {"url": "http://o", "enabled": False},
                    }
                }
            )
        )

    def test_longest_prefix_wins(self) -> None:
        owner = self._ownership().owner_of("gitlab_create_issue")
        assert owner is not None and owner.name == "gitlab"

    def test_short_prefix_still_matches(self) -> None:
        owner = self._ownership().owner_of("git_push")
        assert owner is not None and owner.name == "git"

    def test_unmatched_tool_has_no_owner(self) -> None:
        assert self._ownership().owner_of("unknown_tool") is None

    def test_disabled_servers_are_not_indexed(self) -> None:
        assert self._ownership().owner_of("off_thing") is None

    def test_empty_catalog_owns_nothing(self) -> None:
        empty = ToolOwnership.from_catalog(ServerCatalog.empty())
        assert empty.owner_of("any_tool") is None


class TestSkillsPolicy:
    def test_affirmative_values_opt_in(self) -> None:
        assert all(wants_skills(v) for v in ("true", "TRUE", "1", "yes"))

    def test_missing_or_other_values_opt_out(self) -> None:
        assert not any(wants_skills(v) for v in (None, "", "false", "0", "maybe"))

    def test_skill_tools_are_recognised(self) -> None:
        assert is_skill_tool("list_resources")
        assert is_skill_tool("read_resource")
        assert not is_skill_tool("github_create_issue")

    def test_skill_resources_are_recognised(self) -> None:
        assert is_skill_resource("skill://alpha/SKILL.md")
        assert not is_skill_resource("datadog://dashboards")
