"""Integration tests for the python_command tool."""

from __future__ import annotations

import json


def parse_response(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


async def test_basic_print():
    from kali_mcp.tools.python_command import PythonCommandTool

    t = PythonCommandTool()
    result = await t.safe_execute({"code": "print(2 + 2)"})
    data = parse_response(result)
    assert data["stdout"].strip() == "4"
    assert data["success"] is True


async def test_multiline_with_import():
    from kali_mcp.tools.python_command import PythonCommandTool

    t = PythonCommandTool()
    result = await t.safe_execute({"code": "import math\nprint(math.sqrt(144))"})
    assert parse_response(result)["stdout"].strip() == "12.0"


async def test_stderr_and_stdout_both_captured():
    from kali_mcp.tools.python_command import PythonCommandTool

    t = PythonCommandTool()
    result = await t.safe_execute(
        {"code": "import sys\nprint('err', file=sys.stderr)\nprint('out')"}
    )
    data = parse_response(result)
    assert "err" in data["stderr"]
    assert data["stdout"].strip() == "out"


async def test_syntax_error_nonzero_exit():
    from kali_mcp.tools.python_command import PythonCommandTool

    t = PythonCommandTool()
    result = await t.safe_execute({"code": "def foo("})
    assert parse_response(result)["exit_code"] != 0


async def test_empty_code_rejected():
    from kali_mcp.tools.python_command import PythonCommandTool

    t = PythonCommandTool()
    assert (await t.safe_execute({"code": ""}))["isError"] is True


async def test_integer_timeout():
    from kali_mcp.tools.python_command import PythonCommandTool

    t = PythonCommandTool()
    result = await t.safe_execute({"code": "print('ok')", "timeout": 60})
    assert parse_response(result)["success"] is True
