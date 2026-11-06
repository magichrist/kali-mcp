"""Unit tests for the tool registry — registration, lookup, duplicates, overwrite."""

from __future__ import annotations

from unittest.mock import patch

from kali_mcp.registry import ToolRegistry
from kali_mcp.tools.base import BaseTool


class DummyTool(BaseTool):
    @property
    def name(self):
        return "dummy"

    @property
    def description(self):
        return "dummy tool"

    def input_schema(self):
        return {"type": "object", "properties": {}}

    def validate(self, arguments):
        pass

    def build_command(self, arguments):
        return ["echo"]

    async def execute(self, arguments):
        return {}


class TestRegistry:
    def test_register_and_get(self):
        reg = ToolRegistry()
        t = DummyTool()
        reg.register(t)
        assert reg.get("dummy") is t

    def test_get_unknown_returns_none(self):
        reg = ToolRegistry()
        assert reg.get("nope") is None

    def test_list_all_and_names(self):
        reg = ToolRegistry()
        reg.register(DummyTool())
        assert len(reg.list_all()) == 1
        assert "dummy" in reg.tool_names()

    def test_overwrite_registration(self):
        reg = ToolRegistry()
        t1, t2 = DummyTool(), DummyTool()
        reg.register(t1)
        reg.register(t2)
        assert reg.get("dummy") is t2

    def test_overwrite_logs_warning(self):
        reg = ToolRegistry()
        reg.register(DummyTool())
        with patch("kali_mcp.registry.logger.warning") as mock_warning:
            reg.register(DummyTool())
            mock_warning.assert_called_once()

    def test_register_multiple_distinct_tools(self):
        reg = ToolRegistry()

        class OtherTool(BaseTool):
            @property
            def name(self):
                return "other"

            @property
            def description(self):
                return "other tool"

            def input_schema(self):
                return {"type": "object", "properties": {}}

            def validate(self, arguments):
                pass

            def build_command(self, arguments):
                return ["echo"]

            async def execute(self, arguments):
                return {}

        reg.register(DummyTool())
        reg.register(OtherTool())
        assert set(reg.tool_names()) == {"dummy", "other"}
        assert len(reg.list_all()) == 2
        assert reg.get("other") is not None
