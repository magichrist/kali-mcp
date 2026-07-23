"""SpiderFoot OSINT automation tool."""

from __future__ import annotations

import shlex
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_timeout
from models import ToolError
from responses import success_response, error_response


class SpiderfootTool(BaseTool):
    @property
    def name(self) -> str:
        return "spiderfoot"

    @property
    def description(self) -> str:
        return "Run SpiderFoot for OSINT automation and reconnaissance."

    @property
    def default_timeout(self) -> int:
        return 900

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target domain, IP, or keyword"},
                "modules": {"type": "string", "description": "Specific modules to run (comma-separated, or 'all')", "default": "all"},
                "extra_args": {"type": "string", "description": "Additional spiderfoot-cli arguments"},
                "timeout": {"type": "integer", "default": 900},
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target")
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"], max_val=3600)

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["spiderfoot-cli", "-s", arguments["target"]]
        if "modules" in arguments and arguments["modules"] != "all":
            cmd.extend(["-m", arguments["modules"]])
        if "extra_args" in arguments:
            cmd.extend(shlex.split(arguments["extra_args"]))
        return cmd

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))
        return success_response(
            await engine.execute(command=self.build_command(arguments), tool=self.name, timeout=arguments.get("timeout", self.default_timeout))
        )
