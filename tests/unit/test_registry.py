"""Unit tests for the tool registry."""

from __future__ import annotations

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


def test_register_and_get():
    reg = ToolRegistry()
    t = DummyTool()
    reg.register(t)
    assert reg.get("dummy") is t


def test_get_unknown_returns_none():
    reg = ToolRegistry()
    assert reg.get("nope") is None


def test_list_all_and_names():
    reg = ToolRegistry()
    reg.register(DummyTool())
    assert len(reg.list_all()) == 1
    assert "dummy" in reg.tool_names()


def test_overwrite_registration():
    reg = ToolRegistry()
    t1, t2 = DummyTool(), DummyTool()
    reg.register(t1)
    reg.register(t2)
    assert reg.get("dummy") is t2
