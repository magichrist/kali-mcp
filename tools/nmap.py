"""Nmap network scanner tool."""

from __future__ import annotations

import shlex
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_ip, validate_cidr, validate_timeout
from models import ToolError
from responses import success_response, error_response


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
                "target": {"type": "string", "description": "Target IP, CIDR, or hostname to scan"},
                "scan_type": {"type": "string", "description": "Scan type flag (e.g. '-sS', '-sT', '-sV', '-sC', '-A')", "default": "-sV"},
                "ports": {"type": "string", "description": "Port specification (e.g. '1-1000', '80,443', '-')"},
                "extra_args": {"type": "string", "description": "Additional nmap arguments (e.g. '-O --script vuln')"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 600)", "default": 600},
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target")
        target = arguments["target"]
        try:
            validate_ip(target)
        except ValueError:
            try:
                validate_cidr(target)
            except ValueError:
                if not all(c.isalnum() or c in ".-_" for c in target):
                    raise ValueError(f"Invalid target: {target}")
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"], min_val=1, max_val=3600)

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["nmap"]
        cmd.append(arguments.get("scan_type", "-sV"))
        if "ports" in arguments:
            cmd.extend(["-p", arguments["ports"]])
        if "extra_args" in arguments:
            cmd.extend(shlex.split(arguments["extra_args"]))
        cmd.append(arguments["target"])
        return cmd

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))
        return success_response(
            await engine.execute(command=self.build_command(arguments), tool=self.name, timeout=arguments.get("timeout", self.default_timeout))
        )
