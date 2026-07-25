"""Unit tests for :class:`ServerDefinition`."""

from __future__ import annotations

from panoply.domain.model.server import ServerDefinition


class TestEnabled:
    def test_absent_key_means_enabled(self) -> None:
        assert ServerDefinition("a", {"url": "http://a"}).enabled is True

    def test_explicit_false_disables(self) -> None:
        assert ServerDefinition("a", {"enabled": False}).enabled is False

    def test_explicit_true_stays_enabled(self) -> None:
        assert ServerDefinition("a", {"enabled": True}).enabled is True


class TestDescription:
    def test_strips_whitespace(self) -> None:
        assert ServerDefinition("a", {"description": "  hi  "}).description == "hi"

    def test_missing_is_empty(self) -> None:
        assert ServerDefinition("a", {}).description == ""

    def test_non_string_is_empty(self) -> None:
        assert ServerDefinition("a", {"description": 42}).description == ""


class TestDisabledTools:
    def test_reads_list(self) -> None:
        server = ServerDefinition("a", {"disabledTools": ["x", "y"]})
        assert server.disabled_tools == ("x", "y")

    def test_missing_is_empty(self) -> None:
        assert ServerDefinition("a", {}).disabled_tools == ()

    def test_qualified_names_are_prefixed(self) -> None:
        server = ServerDefinition("beta", {"disabledTools": ["noisy"]})
        assert server.qualified_disabled_tools() == {"beta_noisy"}


class TestTransportSettings:
    def test_strips_non_standard_keys(self) -> None:
        server = ServerDefinition(
            "a", {"url": "http://a", "enabled": True, "disabledTools": ["x"]}
        )
        assert server.transport_settings == {"url": "http://a"}

    def test_keeps_description(self) -> None:
        """``description`` is a native MCP field, so it must survive."""
        server = ServerDefinition("a", {"url": "http://a", "description": "d"})
        assert server.transport_settings == {"url": "http://a", "description": "d"}


class TestToolNaming:
    def test_qualify(self) -> None:
        assert ServerDefinition("git", {}).qualify("push") == "git_push"

    def test_owns_matches_prefix(self) -> None:
        assert ServerDefinition("git", {}).owns("git_push") is True

    def test_owns_rejects_other_server(self) -> None:
        assert ServerDefinition("git", {}).owns("gitlab_push") is False


class TestTransitions:
    def test_enabling_drops_the_key(self) -> None:
        server = ServerDefinition("a", {"url": "u", "enabled": False}).with_enabled(True)
        assert "enabled" not in server.settings

    def test_disabling_writes_false(self) -> None:
        server = ServerDefinition("a", {"url": "u"}).with_enabled(False)
        assert server.settings["enabled"] is False

    def test_disabling_a_tool_appends(self) -> None:
        server = ServerDefinition("a", {}).with_tool_enabled("x", False)
        assert server.settings["disabledTools"] == ["x"]

    def test_disabling_twice_is_idempotent(self) -> None:
        server = ServerDefinition("a", {}).with_tool_enabled("x", False)
        server = server.with_tool_enabled("x", False)
        assert server.settings["disabledTools"] == ["x"]

    def test_enabling_the_last_tool_drops_the_key(self) -> None:
        server = ServerDefinition("a", {"disabledTools": ["x"]})
        assert "disabledTools" not in server.with_tool_enabled("x", True).settings

    def test_enabling_an_absent_tool_is_a_noop(self) -> None:
        server = ServerDefinition("a", {"url": "u"})
        assert server.with_tool_enabled("never", True).settings == {"url": "u"}

    def test_with_disabled_tools_sorts(self) -> None:
        server = ServerDefinition("a", {}).with_disabled_tools({"b", "a"})
        assert server.settings["disabledTools"] == ["a", "b"]

    def test_with_empty_disabled_tools_drops_the_key(self) -> None:
        server = ServerDefinition("a", {"disabledTools": ["x"]})
        assert "disabledTools" not in server.with_disabled_tools(set()).settings

    def test_transitions_do_not_mutate_the_original(self) -> None:
        original = ServerDefinition("a", {"url": "u"})
        original.with_enabled(False)
        assert original.settings == {"url": "u"}
