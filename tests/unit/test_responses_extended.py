"""Extended unit tests for response builders (kmcp/responses.py)."""

from __future__ import annotations

import json

from kmcp.models import ExecutionResult, ToolError, utc_now_iso
from kmcp.responses import (
    error_response,
    error_response_from_exception,
    success_response,
)


def _result() -> ExecutionResult:
    ts = utc_now_iso()
    return ExecutionResult(
        tool="nmap",
        command="nmap -sn 127.0.0.1",
        stdout="host up",
        stderr="",
        exit_code=0,
        success=True,
        timed_out=False,
        duration=0.5,
        start_time=ts,
        end_time=ts,
    )


def test_success_response_full_shape() -> None:
    result = _result()
    sr = success_response(result)
    assert sr["isError"] is False
    assert sr["content"][0]["type"] == "text"
    parsed = json.loads(sr["content"][0]["text"])
    assert parsed == result.to_dict()
    assert parsed["tool"] == "nmap"
    assert parsed["success"] is True


def test_success_response_is_valid_json() -> None:
    sr = success_response(_result())
    json.loads(sr["content"][0]["text"])  # must not raise


def test_error_response_full_shape() -> None:
    er = error_response(ToolError(error="fail", details="boom"))
    assert er["isError"] is True
    assert er["content"][0]["type"] == "text"
    parsed = json.loads(er["content"][0]["text"])
    assert parsed["success"] is False
    assert parsed["error"] == "fail"
    assert parsed["details"] == "boom"


def test_error_response_without_details_omits_key() -> None:
    er = error_response(ToolError(error="fail"))
    parsed = json.loads(er["content"][0]["text"])
    assert "details" not in parsed


def test_error_response_from_exception_various_types() -> None:
    for exc in (RuntimeError("runtime boom"), ValueError("value bad"), Exception()):
        er = error_response_from_exception(exc)
        assert er["isError"] is True
        parsed = json.loads(er["content"][0]["text"])
        assert parsed["success"] is False
        assert parsed["error"] == str(exc)
        assert "details" not in parsed
        # traceback must never be exposed
        assert "traceback" not in parsed
