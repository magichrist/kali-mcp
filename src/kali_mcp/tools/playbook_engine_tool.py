"""Playbook engine tool — agents run custom DAG playbooks via MCP.

Accepts a playbook specification (YAML-compatible dict) and executes it
through the v2.0 DAG workflow engine with depends_on, when, parallel,
foreach, output_mapping, checkpoint, resume, retry, and on_failure.
"""

from __future__ import annotations

from typing import Any

from kali_mcp.tools.base import BaseTool
from kali_mcp.tools.persist import wrap_execution_result


class PlaybookEngineTool(BaseTool):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "playbook_engine"

    @property
    def description(self) -> str:
        return (
            "Execute a custom DAG playbook via the v2.0 workflow engine. "
            "Specify {name, version, inputs, execution, steps} where each step "
            "has id, tool/type, depends_on, when, parallel, foreach, "
            "output_mapping, retry, on_failure, checkpoint, budget, and args. "
            "Step args support '{{target}}' substitution. Use resume=true to "
            "skip previously completed steps."
        )

    @property
    def default_timeout(self) -> int:
        return 3600

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "playbook": {
                    "type": "object",
                    "description": "DAG playbook specification: {name, version, inputs, execution, steps}",
                },
                "resume": {
                    "type": "boolean",
                    "description": "Skip steps completed in a previous run of this playbook (default false)",
                    "default": False,
                },
            },
            "required": ["playbook"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        pb = arguments.get("playbook")
        if not isinstance(pb, dict):
            raise TypeError("playbook must be an object")
        if not pb.get("name"):
            raise ValueError("playbook.name is required")
        steps = pb.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("playbook.steps must be a non-empty list")
        step_ids: set[str] = set()
        for i, step in enumerate(steps):
            if not isinstance(step, dict):
                raise TypeError(f"playbook.steps[{i}] must be an object")
            sid = step.get("id")
            if not sid:
                raise ValueError(f"playbook.steps[{i}] missing required 'id'")
            if sid in step_ids:
                raise ValueError(f"Duplicate step id: {sid}")
            step_ids.add(sid)

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["playbook_engine"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(arguments)
        from kali_mcp.workflow import load_playbook, run_playbook_async

        pb = load_playbook(arguments["playbook"])
        res = await run_playbook_async(pb, resume=bool(arguments.get("resume", False)))
        return wrap_execution_result(res, self.name)
