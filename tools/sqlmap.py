"""SQLMap SQL injection tool."""

from __future__ import annotations

import shlex
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_url, validate_timeout
from models import ToolError
from responses import success_response, error_response


class SqlmapTool(BaseTool):
    @property
    def name(self) -> str:
        return "sqlmap"

    @property
    def description(self) -> str:
        return "Run sqlmap for SQL injection detection and exploitation."

    @property
    def default_timeout(self) -> int:
        return 900

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target URL with injectable parameter"},
                "extra_args": {"type": "string", "description": "Additional sqlmap arguments (e.g. '--dbs --batch')"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 900)", "default": 900},
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target")
        validate_url(arguments["target"])
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"], max_val=3600)

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["sqlmap", "-u", arguments["target"], "--batch"]
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
