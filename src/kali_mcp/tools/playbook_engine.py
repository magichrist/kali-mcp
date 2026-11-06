"""Minimal Playbook Engine for Kali MCP Server (Phase 3).

A lightweight, internal engine to orchestrate playbooks by invoking existing
tool wrappers via the registry. Tracks run state (for `playbook_status`) and
supports resuming partially-completed playbooks.
"""

from __future__ import annotations

import asyncio
import json
from typing import Any

from kali_mcp.models import ExecutionResult
from kali_mcp.registry import registry
from kali_mcp.tools.persist import now_iso

# Shared run-state registry with the DAG engine (kali_mcp.workflow.RUN_STATUS).
# Imported rather than re-defined so that PlaybookStatusTool and the legacy
# engine observe the same store.
from kali_mcp.workflow import RUN_STATUS  # noqa: E402  (circular-import safe: workflow does not import this module)


class PlaybookEngine:
    """Executes a playbook description consisting of sequential steps.

        A playbook is a dict with:
    - name: string (playbook name)
    - steps: list of steps where each step is either:
      - {'parallel': True, 'tools': [{'tool': str, 'args': dict}, ...]}
      - {'parallel': False, 'tools': [{'tool': str, 'args': dict}, ...]}

        Args support ``{{target}}`` placeholders, substituted with the playbook's
        top-level 'target' value before execution.

        Options:
    - resume: if True, skip steps already marked completed in the last run of
      this playbook name (stored in RUN_STATUS).
    """

    def __init__(self) -> None:
        pass

    async def _run_tool(self, spec: dict[str, Any]) -> Any:
        tool_name = spec.get("tool")
        args = spec.get("args", {})
        tool = registry.get(tool_name)
        if tool is None:
            return {"tool": tool_name, "error": "unknown tool"}
        # Each tool has a safe_execute wrapper; propagate as a dict result
        return await tool.safe_execute(args)

    async def _run_step(self, step: dict[str, Any]) -> list[Any] | Any:
        if step.get("parallel"):
            specs: list[dict[str, Any]] = step.get("tools", [])
            tasks = [self._run_tool(s) for s in specs]
            return await asyncio.gather(*tasks)
        else:
            # Sequential: run each tool in order and collect their results
            results = []
            for s in step.get("tools", []):
                results.append(await self._run_tool(s))
            return results

    async def run(self, playbook: dict[str, Any], resume: bool = False) -> ExecutionResult:
        name = playbook.get("name", "playbook")
        steps: list[dict[str, Any]] = playbook.get("steps", [])
        subst_target = playbook.get("target")

        # ── Substitute {{target}} placeholders in step args ───────────────
        if subst_target:
            for step in steps:
                for spec in step.get("tools", []):
                    spec["args"] = {
                        k: (v.replace("{{target}}", str(subst_target)) if isinstance(v, str) else v)
                        for k, v in (spec.get("args") or {}).items()
                    }

        # ── Resume: determine which step indices to skip ──────────────────
        skip_indices: set[int] = set()
        prior = RUN_STATUS.get(name)
        if (
            resume
            and prior
            and prior.get("status") in ("completed", "failed", "aborted", "partial")
        ):
            skip_indices = set(prior.get("completed_steps", []))

        state = RUN_STATUS.setdefault(name, {})
        state.update(
            {
                "status": "running",
                "steps_total": len(steps),
                "started_at": now_iso(),
            }
        )
        if resume:
            state["completed_steps"] = sorted(skip_indices)
        else:
            state["completed_steps"] = []

        results: list[Any] = []
        for idx, step in enumerate(steps):
            if idx in skip_indices:
                continue
            step_res = await self._run_step(step)
            # Normalize to a flat list for stdout
            if isinstance(step_res, list):
                results.extend(step_res)
            else:
                results.append(step_res)
            state["completed_steps"].append(idx)

        all_completed = len(state["completed_steps"]) == len(steps)
        state["status"] = "completed" if all_completed else "partial"
        state["finished_at"] = now_iso()

        payload = {
            "playbook": name,
            "steps": steps,
            "results": results,
            "status": state["status"],
            "completed_steps": state["completed_steps"],
        }

        # Build a synthetic ExecutionResult-like payload
        return ExecutionResult(
            tool=name,
            command=json.dumps(steps, indent=2),
            stdout=json.dumps(payload, indent=2),
            stderr="",
            exit_code=0,
            success=True,
            timed_out=False,
            duration=0.0,
            start_time=state["started_at"],
            end_time=state["finished_at"],
        )


def run_playbook(playbook: dict[str, Any], resume: bool = False) -> ExecutionResult:
    """Synchronous wrapper to run a playbook via the internal engine.

    Kept for CLI/script compatibility. Callers running inside an active
    event loop must use :func:`run_playbook_async` instead.
    """
    eng = PlaybookEngine()
    return asyncio.run(eng.run(playbook, resume=resume))


async def run_playbook_async(
    playbook: dict[str, Any], resume: bool = False
) -> ExecutionResult:
    """Async-native entry point: directly awaits the engine's ``run()``."""
    eng = PlaybookEngine()
    return await eng.run(playbook, resume=resume)
