"""Nmap network scanner tool."""

from __future__ import annotations

import shlex
from typing import Any

from kali_mcp.execution import engine
from kali_mcp.models import ToolError
from kali_mcp.responses import error_response, success_response
from kali_mcp.tools.base import BaseTool
from kali_mcp.validation import validate_cidr, validate_ip, validate_required, validate_timeout


class NmapTool(BaseTool):
    @property
    def name(self) -> str:
        return "nmap"

    @property
    def description(self) -> str:
        return "Run nmap port scans. Supports target specification, scan types, timing, and output options."

    @property
    def default_timeout(self) -> int:
        return 600

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Target IP, CIDR, or hostname to scan",
                },
                "scan_type": {
                    "type": "string",
                    "description": "Scan type flag (e.g. '-sS', '-sT', '-sV', '-sC', '-A')",
                    "default": "-sV",
                },
                "ports": {
                    "type": "string",
                    "description": "Port specification (e.g. '1-1000', '80,443', '-')",
                },
                "extra_args": {
                    "type": "string",
                    "description": "Additional nmap arguments (e.g. '-O --script vuln')",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 600)",
                    "default": 600,
                },
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        if not isinstance(arguments, dict):
            raise ValueError("Arguments must be an object")
        target = arguments.get("target")
        if not target or not isinstance(target, str):
            raise ValueError("Missing or invalid required parameter: target")
        try:
            validate_ip(target)
        except ValueError:
            try:
                validate_cidr(target)
            except ValueError:
                if not all(c.isalnum() or c in ".-_" for c in target):
                    raise ValueError(f"Invalid target: {target}")
        if "timeout" in arguments:
            if not isinstance(arguments["timeout"], (int, float)):
                raise ValueError("Timeout must be a number")
            validate_timeout(arguments["timeout"], min_val=1, max_val=3600)
        if "ports" in arguments and not isinstance(arguments["ports"], str):
            raise ValueError("Ports must be a string")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["nmap"]
        cmd.append(arguments.get("scan_type", "-sV"))
        if "ports" in arguments and arguments["ports"]:
            cmd.extend(["-p", str(arguments["ports"])])
        extra = arguments.get("extra_args")
        if extra:
            cmd.extend(shlex.split(str(extra)))
        cmd.append(str(arguments["target"]))
        return cmd

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))
        return success_response(
            await engine.execute(
                command=self.build_command(arguments),
                tool=self.name,
                timeout=arguments.get("timeout", self.default_timeout),
            )
        )
