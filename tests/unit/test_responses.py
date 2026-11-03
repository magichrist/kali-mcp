"""Unit tests for standardized MCP response builders."""

from __future__ import annotations

import json

from kali_mcp.models import ExecutionResult, ToolError, utc_now_iso
from kali_mcp.responses import error_response, error_response_from_exception, success_response


def _result() -> ExecutionResult:
    ts = utc_now_iso()
    return ExecutionResult(
        tool="test",
        command="echo",
        stdout="ok",
        stderr="",
        exit_code=0,
        success=True,
        timed_out=False,
        duration=0.01,
        start_time=ts,
        end_time=ts,
    )


def test_success_response_shape():
    sr = success_response(_result())
    assert sr["isError"] is False
    assert sr["content"][0]["type"] == "text"
    parsed = json.loads(sr["content"][0]["text"])
    assert parsed["tool"] == "test"


def test_error_response_shape():
    er = error_response(ToolError(error="fail", details="details"))
    assert er["isError"] is True
    parsed = json.loads(er["content"][0]["text"])
    assert parsed["error"] == "fail"


def test_error_response_from_exception():
    er = error_response_from_exception(RuntimeError("boom"))
    assert er["isError"] is True
