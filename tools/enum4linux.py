"""Enum4linux SMB enumeration tool."""

from __future__ import annotations

import shlex
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_ip, validate_timeout
from models import ToolError
from responses import success_response, error_response


class Enum4linuxTool(BaseTool):
    @property
    def name(self) -> str:
        return "enum4linux"

    @property
    def description(self) -> str:
        return "Run enum4linux-ng for SMB/Samba enumeration."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target IP address"},
                "extra_args": {"type": "string", "description": "Additional arguments"},
                "timeout": {"type": "integer", "default": 300},
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target")
        validate_ip(arguments["target"])
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"])

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["enum4linux", "-a", arguments["target"]]
        if "extra_args" in arguments:
            cmd.extend(shlex.split(arguments.get("extra_args") or ""))
        return cmd

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))
        return success_response(
            await engine.execute(command=self.build_command(arguments), tool=self.name, timeout=arguments.get("timeout", self.default_timeout))
        )
