"""Coverage tests for step_types.py step type handlers.

Each handler delegates to the matching method on ``PlaybookEngine``. The
engine methods themselves are exercised in test_dag_executor_coverage.py;
here we use a mock engine so these tests pin the delegation contract of
step_types.py in isolation (no real subprocesses / network / SQLite).
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from kmcp.workflow.step_types import (
    step_assessment_report,
    step_custom,
    step_finding_correlation,
    step_scope_check,
    step_tool,
)


class _FakeEngine:
    """Stand-in for PlaybookEngine whose step runners are AsyncMocks."""

    def __init__(self) -> None:
        self._run_tool_step = AsyncMock(return_value={"step": "s1", "tool": "nmap"})
        self._run_scope_check = AsyncMock(return_value={"step": "s2", "scope_ok": True})
        self._run_finding_correlation = AsyncMock(
            return_value={"step": "s3", "total_correlated": 1}
        )
        self._run_assessment_report = AsyncMock(
            return_value={"step": "s4", "report": {"total_findings": 1}}
        )
        self._run_custom_step = AsyncMock(return_value={"step": "s5", "status": "executed"})


@pytest.mark.asyncio
async def test_step_tool_delegates():
    engine = _FakeEngine()
    step = {"id": "s1", "tool": "nmap", "args": {"target": "example.com"}}
    state = {}
    result = await step_tool(step, state, engine)
    engine._run_tool_step.assert_awaited_once_with(step, state)
    assert result == {"step": "s1", "tool": "nmap"}


@pytest.mark.asyncio
async def test_step_scope_check_delegates():
    engine = _FakeEngine()
    step = {"id": "s2", "tool": "nmap", "args": {"target": "example.com"}}
    state = {}
    result = await step_scope_check(step, state, engine)
    engine._run_scope_check.assert_awaited_once_with(step, state)
    assert result == {"step": "s2", "scope_ok": True}


@pytest.mark.asyncio
async def test_step_finding_correlation_delegates():
    engine = _FakeEngine()
    step = {"id": "s3", "depends_on": ["s1", "s2"]}
    state = {}
    result = await step_finding_correlation(step, state, engine)
    engine._run_finding_correlation.assert_awaited_once_with(step, state)
    assert result == {"step": "s3", "total_correlated": 1}


@pytest.mark.asyncio
async def test_step_assessment_report_delegates():
    engine = _FakeEngine()
    step = {"id": "s4", "depends_on": ["s3"]}
    state = {}
    result = await step_assessment_report(step, state, engine)
    engine._run_assessment_report.assert_awaited_once_with(step, state)
    assert result == {"step": "s4", "report": {"total_findings": 1}}


@pytest.mark.asyncio
async def test_step_custom_delegates():
    engine = _FakeEngine()
    step = {"id": "s5", "tool": "some.module", "args": {"module": "some.module"}}
    state = {}
    result = await step_custom(step, state, engine)
    engine._run_custom_step.assert_awaited_once_with(step, state)
    assert result == {"step": "s5", "status": "executed"}


@pytest.mark.asyncio
async def test_step_handles_engine_returning_none():
    """Handlers must pass through whatever the engine returns, including None."""
    engine = _FakeEngine()
    engine._run_tool_step = AsyncMock(return_value=None)
    step = {"id": "s1", "tool": "nmap", "args": {}}
    assert await step_tool(step, {}, engine) is None
