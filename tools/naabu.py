"""Naabu fast port scanner tool."""

from __future__ import annotations

import shlex
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_enum, validate_timeout
from models import ToolError
from responses import success_response, error_response


class NaabuTool(BaseTool):
    @property
    def name(self) -> str:
        return "naabu"

    @property
    def description(self) -> str:
        return "Run naabu for fast TCP/UDP port scanning with SYN/connect scan support."

    @property
    def default_timeout(self) -> int:
        return 300

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target IP, CIDR, or hostname"},
                "ports": {"type": "string", "description": "Port spec (e.g. '80,443', '1-1000')"},
                "scan_type": {"type": "string", "description": "Scan type: 'syn' (default) or 'connect'", "default": "syn"},
                "extra_args": {"type": "string", "description": "Additional naabu arguments"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 300)", "default": 300},
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target")
        if "scan_type" in arguments:
            validate_enum(arguments["scan_type"], ["syn", "connect"])
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"])

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["naabu", "-host", arguments["target"]]
        if "ports" in arguments:
            cmd.extend(["-p", arguments["ports"]])
        scan = arguments.get("scan_type", "syn")
        if scan == "syn":
            cmd.append("-s")
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
