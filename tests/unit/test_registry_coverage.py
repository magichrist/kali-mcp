"""Unit tests for the tool registry — registration, lookup, duplicates, overwrite."""

from __future__ import annotations

import pytest
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


class TestVisibility:
    def test_default_visibility_is_agent_callable(self):
        reg = ToolRegistry()
        reg.register(DummyTool())
        assert reg.visibility_of("dummy") == "agent_callable"

    def test_register_with_visibility(self):
        reg = ToolRegistry()
        reg.register(DummyTool(), visibility="internal")
        assert reg.visibility_of("dummy") == "internal"

    def test_visible_tools_agent_callable_default(self):
        reg = ToolRegistry()
        reg.register(DummyTool(), visibility="agent_callable")
        reg.register(DummyTool(), visibility="internal")  # will overwrite same name
        # Use distinct names
        reg2 = ToolRegistry()

        class ToolA(BaseTool):
            @property
            def name(self): return "tool_a"
            @property
            def description(self): return "a"
            def input_schema(self): return {"type": "object", "properties": {}}
            def validate(self, arguments): pass
            def build_command(self, arguments): return ["echo"]
            async def execute(self, arguments): return {}

        class ToolB(BaseTool):
            @property
            def name(self): return "tool_b"
            @property
            def description(self): return "b"
            def input_schema(self): return {"type": "object", "properties": {}}
            def validate(self, arguments): pass
            def build_command(self, arguments): return ["echo"]
            async def execute(self, arguments): return {}

        class ToolC(BaseTool):
            @property
            def name(self): return "tool_c"
            @property
            def description(self): return "c"
            def input_schema(self): return {"type": "object", "properties": {}}
            def validate(self, arguments): pass
            def build_command(self, arguments): return ["echo"]
            async def execute(self, arguments): return {}

        reg2.register(ToolA(), visibility="agent_callable")
        reg2.register(ToolB(), visibility="playbook_selectable")
        reg2.register(ToolC(), visibility="internal")

        names = {t.name for t in reg2.visible_tools("agent_callable")}
        assert names == {"tool_a"}

        names = {t.name for t in reg2.visible_tools("playbook_selectable")}
        assert names == {"tool_a", "tool_b"}

        names = {t.name for t in reg2.visible_tools("internal")}
        assert names == {"tool_a", "tool_b", "tool_c"}

    def test_hidden_tool_not_visible(self):
        reg = ToolRegistry()

        class HiddenTool(BaseTool):
            @property
            def name(self): return "hidden_tool"
            @property
            def description(self): return "hidden"
            def input_schema(self): return {"type": "object", "properties": {}}
            def validate(self, arguments): pass
            def build_command(self, arguments): return ["echo"]
            async def execute(self, arguments): return {}

        reg.register(HiddenTool(), visibility="hidden")
        assert reg.visible_tools("agent_callable") == []
        assert reg.visible_tool_names("agent_callable") == []
        # get() still works regardless of visibility
        assert reg.get("hidden_tool") is not None

    def test_set_visibility(self):
        reg = ToolRegistry()
        reg.register(DummyTool())
        assert reg.set_visibility("dummy", "internal") is True
        assert reg.visibility_of("dummy") == "internal"
        assert reg.set_visibility("nope", "internal") is False

    def test_invalid_visibility_rejected(self):
        reg = ToolRegistry()
        with pytest.raises(ValueError, match="invalid visibility"):
            reg.register(DummyTool(), visibility="bogus")

    def test_set_visibility_invalid_rejected(self):
        reg = ToolRegistry()
        reg.register(DummyTool())
        with pytest.raises(ValueError, match="invalid visibility"):
            reg.set_visibility("dummy", "bogus")

    def test_get_definition_returns_metadata(self):
        reg = ToolRegistry()
        reg.register(DummyTool(), metadata={"category": "recon"})
        defn = reg.get_definition("dummy")
        assert defn is not None
        assert defn.visibility == "agent_callable"
        assert defn.metadata == {"category": "recon"}
