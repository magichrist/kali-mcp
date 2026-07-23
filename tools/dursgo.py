"""DursGo web application security scanner tool."""

from __future__ import annotations

import shlex
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_timeout
from models import ToolError
from responses import success_response, error_response


class DursgoTool(BaseTool):
    @property
    def name(self) -> str:
        return "dursgo"

    @property
    def description(self) -> str:
        return "Run DursGo web application security scanner for automated security audits and penetration testing."

    @property
    def default_timeout(self) -> int:
        return 900

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Target URL to scan (e.g. 'https://example.com')",
                },
                "scan_type": {
                    "type": "string",
                    "description": "Scan mode (e.g. 'full', 'quick', 'passive')",
                    "default": "full",
                },
                "extra_args": {
                    "type": "string",
                    "description": "Additional DursGo arguments (e.g. '-depth 3 -threads 10')",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 900)",
                    "default": 900,
                },
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target")
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"], max_val=3600)

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["dursgo", "-u", arguments["target"]]

        scan_type = arguments.get("scan_type", "full")
        if scan_type == "quick":
            cmd.extend(["-mode", "quick"])
        elif scan_type == "passive":
            cmd.extend(["-mode", "passive"])
        else:
            cmd.extend(["-mode", "full"])

        if "extra_args" in arguments:
            cmd.extend(shlex.split(arguments["extra_args"]))

        return cmd

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))

        timeout = arguments.get("timeout", self.default_timeout)
        cmd = self.build_command(arguments)

        result = await engine.execute(cmd, tool=self.name, timeout=timeout)
        return success_response(result)
