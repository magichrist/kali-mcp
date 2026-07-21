"""Arjun HTTP parameter discovery tool."""

from __future__ import annotations
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_url, validate_timeout
from models import ToolError
from responses import success_response, error_response


class ArjunTool(BaseTool):
    @property
    def name(self) -> str:
        return "arjun"

    @property
    def description(self) -> str:
        return "Run arjun for HTTP parameter discovery."

    @property
    def default_timeout(self) -> int:
        return 600

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target URL to scan for parameters"},
                "wordlist": {"type": "string", "description": "Custom parameter wordlist path"},
                "extra_args": {"type": "string", "description": "Additional arjun arguments"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 600)", "default": 600},
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target")
        validate_url(arguments["target"])
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"])

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["arjun", "-u", arguments["target"]]
        if "wordlist" in arguments:
            cmd.extend(["-w", arguments["wordlist"]])
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
