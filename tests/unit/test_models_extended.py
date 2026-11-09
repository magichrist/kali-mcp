"""Extended unit tests for core data models (kali_mcp/models.py)."""

from __future__ import annotations

from datetime import datetime

from kali_mcp.models import ExecutionResult, ToolError, utc_now_iso


def _make_result(**overrides):
    ts = utc_now_iso()
    defaults = {
        "tool": "nmap",
        "command": "nmap -sV 127.0.0.1",
        "stdout": "PORT   STATE SERVICE\n",
        "stderr": "",
        "exit_code": 0,
        "success": True,
        "timed_out": False,
        "duration": 1.5,
        "start_time": ts,
        "end_time": ts,
    }
    defaults.update(overrides)
    return ExecutionResult(**defaults)


def test_utc_now_iso_is_utc_isoformat() -> None:
    ts = utc_now_iso()
    assert "T" in ts
    assert ts.endswith(("+00:00", "Z"))
    parsed = datetime.fromisoformat(ts)
    assert parsed.tzinfo is not None


def test_execution_result_to_dict_full_shape() -> None:
    r = _make_result()
    d = r.to_dict()
    assert d == {
        "tool": "nmap",
        "command": "nmap -sV 127.0.0.1",
        "stdout": "PORT   STATE SERVICE\n",
        "stderr": "",
        "exit_code": 0,
        "success": True,
        "timed_out": False,
        "duration": 1.5,
        "start_time": r.start_time,
        "end_time": r.end_time,
    }


def test_execution_result_dataclass_equality() -> None:
    ts = utc_now_iso()
    kwargs = {
        "tool": "t",
        "command": "c",
        "stdout": "o",
        "stderr": "e",
        "exit_code": 0,
        "success": True,
        "timed_out": False,
        "duration": 0.1,
        "start_time": ts,
        "end_time": ts,
    }
    assert ExecutionResult(**kwargs) == ExecutionResult(**kwargs)


def test_tool_error_to_dict_with_details() -> None:
    d = ToolError(error="boom", details="trace info").to_dict()
    assert d == {"success": False, "error": "boom", "details": "trace info"}


def test_tool_error_to_dict_without_details_omits_key() -> None:
    d = ToolError(error="boom").to_dict()
    assert d == {"success": False, "error": "boom"}
    assert "details" not in d


def test_tool_error_default_details_is_empty_string() -> None:
    assert ToolError(error="boom").details == ""
