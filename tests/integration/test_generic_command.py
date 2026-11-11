"""Integration tests for the generic_command tool (full execution)."""

from __future__ import annotations

import json
import os


def parse_response(result: dict) -> dict:
    """Extract the JSON payload from an MCP tool response."""
    return json.loads(result["content"][0]["text"])


async def test_basic_echo():
    from kmcp.tools.generic_command import GenericCommandTool

    t = GenericCommandTool()
    result = await t.safe_execute({"command": "echo hello"})
    data = parse_response(result)
    assert data["success"] is True
    assert data["stdout"].strip() == "hello"
    assert result["isError"] is False


async def test_pipe():
    from kmcp.tools.generic_command import GenericCommandTool

    t = GenericCommandTool()
    result = await t.safe_execute({"command": "echo abc | tr a-z A-Z"})
    assert parse_response(result)["stdout"].strip() == "ABC"


async def test_command_substitution():
    from kmcp.tools.generic_command import GenericCommandTool

    t = GenericCommandTool()
    result = await t.safe_execute({"command": "echo $(echo nested)"})
    assert parse_response(result)["stdout"].strip() == "nested"


async def test_glob_expansion():
    from kmcp.tools.generic_command import GenericCommandTool

    t = GenericCommandTool()
    result = await t.safe_execute({"command": "ls /etc/hos*"})
    assert "hosts" in parse_response(result)["stdout"]


async def test_integer_and_string_timeouts():
    from kmcp.tools.generic_command import GenericCommandTool

    t = GenericCommandTool()
    assert parse_response(await t.safe_execute({"command": "echo ok", "timeout": 60}))["success"]
    assert parse_response(await t.safe_execute({"command": "echo ok", "timeout": "30"}))["success"]
    assert parse_response(await t.safe_execute({"command": "echo ok"}))["success"]


async def test_empty_command_rejected():
    from kmcp.tools.generic_command import GenericCommandTool

    t = GenericCommandTool()
    assert (await t.safe_execute({"command": ""}))["isError"] is True
    assert (await t.safe_execute({}))["isError"] is True


async def test_cwd():
    from kmcp.tools.generic_command import GenericCommandTool

    t = GenericCommandTool()
    result = await t.safe_execute({"command": "pwd", "cwd": "/tmp"})
    assert parse_response(result)["stdout"].strip() == os.path.realpath("/tmp")
