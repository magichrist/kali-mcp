"""BloodHound collection tool."""

from __future__ import annotations
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_timeout
from models import ToolError
from responses import success_response, error_response


class BloodhoundTool(BaseTool):
    @property
    def name(self) -> str:
        return "bloodhound"

    @property
    def description(self) -> str:
        return "Run SharpHound/BloodHound collection for Active Directory enumeration."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "collection": {"type": "string", "description": "Collection method (e.g. 'All', 'Group', 'LocalAdmin')", "default": "All"},
                "domain": {"type": "string", "description": "Target domain (optional)"},
                "extra_args": {"type": "string", "description": "Additional sharpound arguments"},
                "timeout": {"type": "integer", "default": 900},
            },
            "required": [],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"], max_val=3600)

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["sharpound", "-c", arguments.get("collection", "All")]
        if "domain" in arguments:
            cmd.extend(["-d", arguments["domain"]])
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
