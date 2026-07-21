"""WhatWeb web fingerprinting tool."""

from __future__ import annotations
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_url, validate_timeout
from models import ToolError
from responses import success_response, error_response


class WhatwebTool(BaseTool):
    @property
    def name(self) -> str:
        return "whatweb"

    @property
    def description(self) -> str:
        return "Run whatweb for web technology fingerprinting."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target URL or domain"},
                "verbosity": {"type": "integer", "description": "Verbosity level 0-4 (default 1)", "default": 1},
                "extra_args": {"type": "string", "description": "Additional whatweb arguments"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 300)", "default": 300},
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target")
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"])

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["whatweb", "-v", str(arguments.get("verbosity", 1)), arguments["target"]]
        if "extra_args" in arguments:
            cmd.extend(arguments["extra_args"].split())
        return cmd

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))
        return success_response(
            await engine.execute(command=self.build_command(arguments), tool=self.name, timeout=arguments.get("timeout", self.default_timeout))
        )
