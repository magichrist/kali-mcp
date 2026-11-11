"""Integration tests for safe_execute error handling guarantees."""

from __future__ import annotations

import json


def parse_response(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


async def test_nonzero_exit_is_not_mcp_error():
    """A command failing must still be a well-formed tool response."""
    from kmcp.tools.generic_command import GenericCommandTool

    result = await GenericCommandTool().safe_execute({"command": "exit 42"})
    data = parse_response(result)
    assert data["exit_code"] == 42
    assert data["success"] is False
    assert result["isError"] is False  # tool itself ran fine


async def test_stdout_preserved_on_failure():
    from kmcp.tools.generic_command import GenericCommandTool

    result = await GenericCommandTool().safe_execute({"command": "echo partial && exit 1"})
    data = parse_response(result)
    assert data["stdout"].strip() == "partial"
    assert data["exit_code"] == 1


async def test_command_not_found():
    from kmcp.tools.generic_command import GenericCommandTool

    result = await GenericCommandTool().safe_execute({"command": "totally_fake_command_xyz"})
    assert parse_response(result)["success"] is False
