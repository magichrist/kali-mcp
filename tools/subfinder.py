"""Subfinder subdomain discovery tool."""

from __future__ import annotations
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_domain, validate_timeout
from models import ToolError
from responses import success_response, error_response


class SubfinderTool(BaseTool):
    @property
    def name(self) -> str:
        return "subfinder"

    @property
    def description(self) -> str:
        return "Run subfinder for passive subdomain discovery."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Target domain (e.g. 'example.com')"},
                "extra_args": {"type": "string", "description": "Additional subfinder arguments"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 300)", "default": 300},
            },
            "required": ["domain"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "domain")
        validate_domain(arguments["domain"])
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"])

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["subfinder", "-d", arguments["domain"]]
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
