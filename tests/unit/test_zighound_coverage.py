"""Coverage-focused tests for ``kmcp.tools.zighound`` (ZigHoundTool).

Covers schema, validate, build_command (scan/c2/agent/extra_args branches),
execute success and both error paths, using mocking to avoid real subprocesses.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

from kmcp.models import ExecutionResult
from kmcp.tools.zighound import ZighoundTool

COMMAND = "zighound scan --target 127.0.0.1"


def _result(stdout='{"ok": true}', exit_code=0):
    return ExecutionResult(
        tool="zighound",
        command=COMMAND,
        stdout=stdout,
        stderr="",
        exit_code=exit_code,
        success=exit_code == 0,
        timed_out=False,
        duration=0.1,
        start_time="2026-01-01T00:00:00+00:00",
        end_time="2026-01-01T00:00:01+00:00",
    )


class TestSchemaAndMetadata:
    def test_name_description_default_timeout(self) -> None:
        tool = ZighoundTool()
        assert tool.name == "zighound"
        assert "ZigHound" in tool.description
        assert tool.default_timeout == 600

    def test_input_schema_shape(self) -> None:
        tool = ZighoundTool()
        schema = tool.input_schema()
        assert schema["type"] == "object"
        props = schema["properties"]
        assert "command" in props
        assert schema["required"] == ["command"]
        for prop in props.values():
            assert "type" in prop
            assert prop["type"] in ("string", "integer", "boolean")


class TestValidate:
    def test_validate_is_noop_and_accepts(self) -> None:
        tool = ZighoundTool()
        tool.validate({"command": "scan", "target": "127.0.0.1"})
        tool.validate({"command": "agent"})
        tool.validate({})  # validate does nothing


class TestBuildCommand:
    def test_scan_minimal(self) -> None:
        cmd = ZighoundTool().build_command({"command": "scan", "target": "127.0.0.0/24"})
        assert cmd == ["zighound", "scan", "--target", "127.0.0.0/24"]

    def test_scan_full(self) -> None:
        cmd = ZighoundTool().build_command(
            {
                "command": "scan",
                "target": "127.0.0.0/24",
                "ports": "22,80,443",
                "stealth": True,
                "jitter": 500,
            }
        )
        assert cmd == [
            "zighound",
            "scan",
            "--target",
            "127.0.0.0/24",
            "--ports",
            "22,80,443",
            "--stealth",
            "--jitter",
            "500",
        ]

    def test_scan_no_optional_flags(self) -> None:
        # stealth False, jitter 0, ports empty -> none appended
        cmd = ZighoundTool().build_command(
            {
                "command": "scan",
                "target": "127.0.0.0/24",
                "stealth": False,
                "jitter": 0,
                "ports": "",
            }
        )
        assert cmd == ["zighound", "scan", "--target", "127.0.0.0/24"]

    def test_c2_listen(self) -> None:
        cmd = ZighoundTool().build_command({"command": "c2", "port": 443, "psk": "secret"})
        assert cmd == ["zighound", "c2", "listen", "--port", "443", "--psk", "secret"]

    def test_c2_no_optional(self) -> None:
        cmd = ZighoundTool().build_command({"command": "c2"})
        assert cmd == ["zighound", "c2", "listen"]

    def test_agent_full(self) -> None:
        cmd = ZighoundTool().build_command(
            {
                "command": "agent",
                "host": "127.0.0.1",
                "port": 443,
                "psk": "secret",
                "jitter": 100,
                "install": True,
            }
        )
        assert cmd == [
            "zighound",
            "agent",
            "--host",
            "127.0.0.1",
            "--port",
            "443",
            "--psk",
            "secret",
            "--jitter",
            "100",
            "--install",
        ]

    def test_agent_no_optional(self) -> None:
        cmd = ZighoundTool().build_command({"command": "agent", "host": "127.0.0.1"})
        assert cmd == ["zighound", "agent", "--host", "127.0.0.1"]

    def test_other_command(self) -> None:
        # unknown command still emitted verbatim (evasion etc.)
        cmd = ZighoundTool().build_command({"command": "evasion"})
        assert cmd == ["zighound", "evasion"]

    def test_extra_args_split(self) -> None:
        cmd = ZighoundTool().build_command(
            {"command": "scan", "target": "127.0.0.0/24", "extra_args": "--foo bar --baz"}
        )
        assert "--foo" in cmd and "bar" in cmd and "--baz" in cmd


class TestExecute:
    async def test_execute_success(self) -> None:
        tool = ZighoundTool()
        with patch(
            "kmcp.tools.zighound.engine.execute", new=AsyncMock(return_value=_result())
        ) as m:
            result = await tool.execute({"command": "scan", "target": "127.0.0.1"})
            assert result["isError"] is False
            assert "content" in result
            m.assert_awaited_once()
            args = m.await_args.args
            assert args[0] == ["zighound", "scan", "--target", "127.0.0.1"]
            assert m.await_args.kwargs["timeout"] == 600  # timeout == default_timeout

    async def test_execute_uses_provided_timeout(self) -> None:
        tool = ZighoundTool()
        with patch(
            "kmcp.tools.zighound.engine.execute", new=AsyncMock(return_value=_result())
        ) as m:
            await tool.execute({"command": "scan", "target": "127.0.0.1", "timeout": 120})
            assert m.await_args.kwargs["timeout"] == 120

    async def test_execute_validation_error_path(self) -> None:
        tool = ZighoundTool()
        # validate() is a no-op; force it to raise ValueError to hit the branch.
        with patch.object(tool, "validate", side_effect=ValueError("bad input")):
            result = await tool.execute({"command": "scan", "target": "127.0.0.1"})
            assert result["isError"] is True
            assert "Validation error" in result["content"][0]["text"]

    async def test_execute_generic_exception_path(self) -> None:
        tool = ZighoundTool()
        with patch.object(tool, "validate", side_effect=RuntimeError("boom")):
            result = await tool.execute({"command": "scan", "target": "127.0.0.1"})
            assert result["isError"] is True
            assert "Execution failed" in result["content"][0]["text"]
