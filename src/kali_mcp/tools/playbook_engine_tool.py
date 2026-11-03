"""Playbook engine tool — agents run custom multi-tool sequences via MCP."""

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
            "Execute a custom playbook: {'name': str, 'target': str, 'steps': [...]}. "
            "Each step is {'parallel': bool, 'tools': [{'tool': name, 'args': {...}}]}. "
            "Step args support '{{target}}' placeholders substituted with the "
            "playbook target. Failed steps don't abort the run; use resume=true "
            "to skip previously completed steps."
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
                    "description": "Playbook specification: {name, target, steps}",
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
            raise ValueError("playbook must be an object")
        steps = pb.get("steps")
        if not isinstance(steps, list) or not steps:
            raise ValueError("playbook.steps must be a non-empty list")
        for i, step in enumerate(steps):
            if not isinstance(step, dict) or not isinstance(step.get("tools"), list):
                raise ValueError(f"playbook.steps[{i}] must have a 'tools' list")
            for spec in step["tools"]:
                if not isinstance(spec, dict) or "tool" not in spec:
                    raise ValueError(
                        f"playbook.steps[{i}].tools entries must be {{tool, args}}"
                    )

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["playbook_engine"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(arguments)
        from kali_mcp.tools.playbook_engine import PlaybookEngine

        engine = PlaybookEngine()
        res = await engine.run(
            arguments["playbook"], resume=bool(arguments.get("resume"))
        )
        return wrap_execution_result(res, self.name)
