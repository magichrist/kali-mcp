"""Unit tests for core data models."""

from __future__ import annotations

from kali_mcp.models import ExecutionResult, ToolError, utc_now_iso


def _result(**overrides) -> ExecutionResult:
    ts = utc_now_iso()
    defaults = dict(
        tool="test",
        command="echo hi",
        stdout="hi\n",
        stderr="",
        exit_code=0,
        success=True,
        timed_out=False,
        duration=0.123,
        start_time=ts,
        end_time=ts,
    )
    defaults.update(overrides)
    return ExecutionResult(**defaults)


def test_utc_now_iso():
    ts = utc_now_iso()
    assert "T" in ts
    assert ts.endswith("Z") or "+" in ts


def test_execution_result_to_dict():
    d = _result().to_dict()
    assert d["tool"] == "test"
    assert d["stdout"] == "hi\n"
    assert d["success"] is True
    assert d["duration"] == 0.123


def test_tool_error_to_dict():
    d = ToolError(error="bad", details="oops").to_dict()
    assert d["error"] == "bad"
    assert d["details"] == "oops"
    assert d["success"] is False


def test_tool_error_without_details_omits_key():
    d = ToolError(error="bad").to_dict()
    assert "details" not in d
