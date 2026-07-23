"""Quick smoke tests for the MCP server components."""

import asyncio
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))


def test_config():
    from config import config
    assert config.port == 8399
    assert config.default_timeout == 300
    print("PASS: config")


def test_models():
    from models import ExecutionResult, utc_now_iso
    r = ExecutionResult(
        tool="test", command="echo hi", stdout="hi", stderr="",
        exit_code=0, success=True, timed_out=False,
        duration=0.1, start_time=utc_now_iso(), end_time=utc_now_iso(),
    )
    d = r.to_dict()
    assert d["tool"] == "test"
    assert d["success"] is True
    print("PASS: models")


def test_validation():
    from validation import validate_required, validate_ip, validate_domain, validate_url
    try:
        validate_required({}, "missing")
        assert False, "Should have raised"
    except ValueError:
        pass
    validate_ip("10.0.0.1")
    validate_domain("example.com")
    validate_url("https://example.com")
    print("PASS: validation")


def test_registry():
    from registry import ToolRegistry
    from tools.base import BaseTool
    class Dummy(BaseTool):
        @property
        def name(self): return "dummy"
        @property
        def description(self): return "test"
        def input_schema(self): return {}
        def validate(self, a): pass
        def build_command(self, a): return ["echo"]
        async def execute(self, a): return {"content": [{"type": "text", "text": "ok"}], "isError": False}
    reg = ToolRegistry()
    reg.register(Dummy())
    assert reg.get("dummy") is not None
    assert "dummy" in reg.tool_names()
    print("PASS: registry")


def test_tools_import():
    from tools import ALL_TOOLS
    assert len(ALL_TOOLS) >= 17
    names = [t.name for t in ALL_TOOLS]
    assert "generic_command" in names
    assert "nmap" in names
    print(f"PASS: tools import ({len(ALL_TOOLS)} tools)")


async def test_execution():
    from execution import engine
    result = await engine.execute(["echo", "hello"], tool="test")
    assert result.success
    assert result.stdout.strip() == "hello"
    assert result.exit_code == 0
    assert result.duration >= 0
    print("PASS: execution engine")


async def test_generic_command():
    from tools.generic_command import GenericCommandTool
    tool = GenericCommandTool()
    result = await tool.execute({"command": "echo test123"})
    assert result["isError"] is False
    print("PASS: generic_command")


async def test_nmap_validation():
    from tools.nmap import NmapTool
    tool = NmapTool()
    # Should reject empty target
    result = await tool.execute({"target": ""})
    assert result["isError"] is True
    # Should accept valid IP
    result = await tool.execute({"target": "127.0.0.1"})
    assert "content" in result
    print("PASS: nmap validation")


def main():
    test_config()
    test_models()
    test_validation()
    test_registry()
    test_tools_import()
    asyncio.run(test_execution())
    asyncio.run(test_generic_command())
    asyncio.run(test_nmap_validation())
    print("\nAll tests passed!")


if __name__ == "__main__":
    main()
