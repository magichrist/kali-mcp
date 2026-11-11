"""Unit tests for execution scope enforcement (kmcp/execution.py).

Covers the scope enforcement hook that rejects out-of-scope targets before
execution, plus target/assessment_id/job_id params passthrough.
"""

from __future__ import annotations

import asyncio

from kmcp.execution import ExecutionEngine

_SCOPE_ENV_VARS = (
    "MCP_SCOPE_ALLOWED_TARGETS",
    "MCP_SCOPE_EXCLUDED_TARGETS",
    "MCP_SCOPE_ALLOWED_OPERATIONS",
    "MCP_SCOPE_EXPIRATION",
)


def _clear_scope_env(monkeypatch):
    for var in _SCOPE_ENV_VARS:
        monkeypatch.delenv(var, raising=False)


class TestExecutionScopeEnforcement:
    def test_default_permissive_scope_allows(self, monkeypatch):
        _clear_scope_env(monkeypatch)
        eng = ExecutionEngine()
        result = asyncio.run(
            eng.execute(
                command="echo hello",
                tool="generic_command",
                target="any.external.host",
                timeout=5,
            )
        )
        assert result.success is True
        assert "hello" in result.stdout

    def test_scope_violation_returns_failure_result(self, monkeypatch):
        _clear_scope_env(monkeypatch)
        monkeypatch.setenv("MCP_SCOPE_ALLOWED_TARGETS", "127.0.0.1")
        eng = ExecutionEngine()
        result = asyncio.run(
            eng.execute(
                command="echo hello",
                tool="generic_command",
                target="any.external.host",
                timeout=5,
            )
        )
        assert result.success is False
        assert result.exit_code == -1
        assert "Scope violation" in result.stderr
        # No command actually ran.
        assert result.stdout == ""

    def test_in_scope_target_executes_normally(self, monkeypatch):
        _clear_scope_env(monkeypatch)
        monkeypatch.setenv("MCP_SCOPE_ALLOWED_TARGETS", "127.0.0.1")
        eng = ExecutionEngine()
        result = asyncio.run(
            eng.execute(
                command="echo hello",
                tool="generic_command",
                target="127.0.0.1",
                timeout=5,
            )
        )
        assert result.success is True
        assert "hello" in result.stdout

    def test_disallowed_operation_rejected(self, monkeypatch):
        _clear_scope_env(monkeypatch)
        monkeypatch.setenv("MCP_SCOPE_ALLOWED_OPERATIONS", "nmap")
        eng = ExecutionEngine()
        result = asyncio.run(
            eng.execute(
                command="echo hello",
                tool="generic_command",
                target="127.0.0.1",
                timeout=5,
            )
        )
        assert result.success is False
        assert "Scope violation" in result.stderr

    def test_excluded_target_rejected(self, monkeypatch):
        _clear_scope_env(monkeypatch)
        monkeypatch.setenv("MCP_SCOPE_ALLOWED_TARGETS", "localhost,127.0.0.1")
        monkeypatch.setenv("MCP_SCOPE_EXCLUDED_TARGETS", "127.0.0.1")
        eng = ExecutionEngine()
        result = asyncio.run(
            eng.execute(
                command="echo hello",
                tool="generic_command",
                target="127.0.0.1",
                timeout=5,
            )
        )
        assert result.success is False
        assert "Scope violation" in result.stderr

    def test_assessment_id_and_job_id_params_accepted(self, monkeypatch):
        _clear_scope_env(monkeypatch)
        eng = ExecutionEngine()
        result = asyncio.run(
            eng.execute(
                command="echo hello",
                tool="generic_command",
                target="127.0.0.1",
                assessment_id="assessment_abc123def456",
                job_id="job_abc123def456",
                timeout=5,
            )
        )
        assert result.success is True
        assert result.tool == "generic_command"

    def test_no_target_and_no_tool_skips_scope(self, monkeypatch):
        _clear_scope_env(monkeypatch)
        monkeypatch.setenv("MCP_SCOPE_ALLOWED_TARGETS", "127.0.0.1")
        eng = ExecutionEngine()
        result = asyncio.run(
            eng.execute(
                command="echo hello",
                tool="generic_command",
                target=None,
                timeout=5,
            )
        )
        assert result.success is True
