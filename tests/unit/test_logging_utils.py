"""Unit tests for logging_utils.py."""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kali_mcp.logging_utils import JSONFormatter, log_execution, setup_logging
from kali_mcp.models import ExecutionResult


@pytest.fixture(autouse=True)
def _clean_kali_mcp_loggers():
    """Ensure the kali_mcp logger has no leftover handlers between tests."""
    yield
    for name in ("kali_mcp", "kali_mcp.executions"):
        logger = logging.getLogger(name)
        logger.handlers.clear()


class TestJSONFormatter:
    def test_format_contains_expected_keys(self) -> None:
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="kali_mcp.test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="hello %s",
            args=("world",),
            exc_info=None,
        )
        payload = json.loads(fmt.format(record))
        assert payload["timestamp"]
        assert payload["level"] == "INFO"
        assert payload["logger"] == "kali_mcp.test"
        assert payload["message"] == "hello world"

    def test_format_includes_extra_data(self) -> None:
        fmt = JSONFormatter()
        record = logging.LogRecord(
            name="kali_mcp.test",
            level=logging.DEBUG,
            pathname="",
            lineno=0,
            msg="msg",
            args=(),
            exc_info=None,
        )
        record.extra_data = {"key": "value"}
        payload = json.loads(fmt.format(record))
        assert payload["data"] == {"key": "value"}


class TestSetupLogging:
    def test_setup_logging_is_idempotent(self) -> None:
        root = logging.getLogger("kali_mcp")
        root.handlers.clear()
        setup_logging()
        count_after_first = len(root.handlers)
        setup_logging()
        # Second call must not add duplicate handlers
        assert len(root.handlers) == count_after_first
        assert count_after_first > 0

    def test_setup_logging_creates_handlers(self) -> None:
        root = logging.getLogger("kali_mcp")
        root.handlers.clear()
        with patch("kali_mcp.logging_utils.config") as mock_config:
            mock_config.debug = False
            mock_config.log_dir = Path("/tmp/test_logs")
            # Configure the mock handler so the logging module can compare levels
            mock_handler_instance = MagicMock()
            mock_handler_instance.level = logging.INFO
            mock_handler = MagicMock(return_value=mock_handler_instance)
            with patch("kali_mcp.logging_utils.RotatingFileHandler", mock_handler):
                setup_logging()
                assert mock_handler.called


class TestLogExecution:
    def test_log_execution_swallows_errors(self) -> None:
        result = MagicMock()
        result.tool = "generic_command"
        result.command = "echo hi"
        result.exit_code = 0
        result.success = True
        result.duration = 0.123
        result.timed_out = False
        log_execution(result)

    def test_log_execution_with_real_result(self) -> None:
        result = ExecutionResult(
            tool="nmap",
            command="nmap -sT 127.0.0.1",
            stdout="",
            stderr="",
            exit_code=0,
            success=True,
            timed_out=False,
            duration=1.5,
            start_time="2026-01-01T00:00:00+00:00",
            end_time="2026-01-01T00:00:01+00:00",
        )
        log_execution(result)
