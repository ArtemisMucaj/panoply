"""Unit tests for :class:`PanoplySearchTransform`."""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from panoply.connector.mcp.search_transform import PanoplySearchTransform


class TestSyntheticToolDescriptions:
    def test_is_a_bm25_transform(self) -> None:
        from fastmcp.server.transforms.search import BM25SearchTransform

        assert issubclass(PanoplySearchTransform, BM25SearchTransform)

    def test_load_tool_is_named_and_labelled_step_one(self) -> None:
        tool = PanoplySearchTransform()._make_load_tool()
        assert tool.name == "load_tools"
        assert "STEP 1" in tool.description
        assert "FIRST" in tool.description

    def test_search_tool_is_labelled_step_two(self) -> None:
        assert "STEP 2" in PanoplySearchTransform()._make_search_tool().description

    def test_call_tool_is_labelled_step_three(self) -> None:
        assert "STEP 3" in PanoplySearchTransform()._make_call_tool().description

    def test_search_tool_warns_against_pasting_the_whole_task(self) -> None:
        description = PanoplySearchTransform()._make_search_tool().description
        assert "DO NOT" in description or "WRONG" in description


class TestToolExposure:
    async def test_all_three_tools_are_visible(self) -> None:
        transform = PanoplySearchTransform(
            server_descriptions={"github": "Issues and PRs"}
        )
        names = [tool.name for tool in await transform.transform_tools([])]
        assert {"load_tools", "search_tools", "call_tool"} <= set(names)

    async def test_load_tools_comes_first(self) -> None:
        transform = PanoplySearchTransform(server_descriptions={"x": "y"})
        names = [tool.name for tool in await transform.transform_tools([])]
        assert names[0] == "load_tools"

    async def test_get_tool_intercepts_load_tools(self) -> None:
        transform = PanoplySearchTransform(server_descriptions={"x": "y"})
        call_next = AsyncMock(return_value=None)
        tool = await transform.get_tool("load_tools", call_next)
        assert tool is not None and tool.name == "load_tools"
        call_next.assert_not_called()

    async def test_get_tool_delegates_everything_else(self) -> None:
        transform = PanoplySearchTransform(server_descriptions={"x": "y"})
        call_next = AsyncMock(return_value=None)
        await transform.get_tool("some_backend_tool", call_next)
        call_next.assert_called_once()


class TestServerOverview:
    def test_lists_servers_with_their_descriptions(self) -> None:
        transform = PanoplySearchTransform(
            server_descriptions={"github": "Issues and PRs", "gmail": ""}
        )
        text = transform._render_server_overview()
        assert "- github: Issues and PRs" in text
        assert "- gmail" in text
        # gmail has no description, so no dangling colon
        assert "- gmail:" not in text

    def test_empty_overview_points_at_search(self) -> None:
        text = PanoplySearchTransform(server_descriptions={})._render_server_overview()
        assert "search_tools" in text

    async def test_the_tool_returns_the_overview(self) -> None:
        transform = PanoplySearchTransform(
            server_descriptions={"github": "Issues and PRs"}
        )
        assert "github: Issues and PRs" in await transform._make_load_tool().fn()


class TestCallToolGuard:
    @pytest.mark.parametrize("name", ["load_tools", "search_tools", "call_tool"])
    async def test_synthetic_tools_cannot_be_invoked_through_call_tool(
        self, name: str
    ) -> None:
        transform = PanoplySearchTransform(server_descriptions={"x": "y"})
        with pytest.raises(ValueError, match="synthetic search tool"):
            await transform._make_call_tool().fn(name=name, ctx=None)
