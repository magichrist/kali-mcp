"""Step type implementations for the DAG workflow engine.

Each step type is a callable that receives (step, state, engine) and returns
a structured result. These are used internally by dag_executor.py.
"""

from __future__ import annotations

from typing import Any

from kmcp.workflow.dag_executor import PlaybookEngine


async def step_tool(step: dict[str, Any], state: dict[str, Any], engine: PlaybookEngine) -> Any:
    """Execute a native tool step."""
    return await engine._run_tool_step(step, state)


async def step_scope_check(
    step: dict[str, Any], state: dict[str, Any], engine: PlaybookEngine
) -> Any:
    """Validate target against scope."""
    return await engine._run_scope_check(step, state)


async def step_finding_correlation(
    step: dict[str, Any], state: dict[str, Any], engine: PlaybookEngine
) -> Any:
    """Correlate findings from multiple steps."""
    return await engine._run_finding_correlation(step, state)


async def step_assessment_report(
    step: dict[str, Any], state: dict[str, Any], engine: PlaybookEngine
) -> Any:
    """Generate assessment report."""
    return await engine._run_assessment_report(step, state)


async def step_custom(step: dict[str, Any], state: dict[str, Any], engine: PlaybookEngine) -> Any:
    """Custom step execution."""
    return await engine._run_custom_step(step, state)
