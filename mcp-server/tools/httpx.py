"""httpx HTTP toolkit tool."""

from __future__ import annotations
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_timeout
from models import ToolError
from responses import success_response, error_response


class HttpxTool(BaseTool):
    @property
    def name(self) -> str:
        return "httpx"

    @property
    def description(self) -> str:
        return "Run httpx for HTTP probing, technology detection, and web reconnaissance."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "URL, domain, or IP to probe"},
                "scan_type": {"type": "string", "description": "httpx flags (e.g. '-status-code -title -tech-detect')", "default": "-status-code -title -tech-detect"},
                "input_file": {"type": "string", "description": "Path to input file with targets (one per line)"},
                "extra_args": {"type": "string", "description": "Additional httpx arguments"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 300)", "default": 300},
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target")
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"])

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["httpx"]
        if "input_file" in arguments:
            cmd.extend(["-l", arguments["input_file"]])
        else:
            cmd.extend(["-u", arguments["target"]])
        cmd.extend(arguments.get("scan_type", "-status-code -title -tech-detect").split())
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
