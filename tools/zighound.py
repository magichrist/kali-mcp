"""ZigHound red team network framework tool."""

from __future__ import annotations

import shlex
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_timeout
from models import ToolError
from responses import success_response, error_response


class ZighoundTool(BaseTool):
    @property
    def name(self) -> str:
        return "zighound"

    @property
    def description(self) -> str:
        return (
            "Run ZigHound red team network framework. "
            "Supports network scanning, C2 listener, agent deployment, and evasion simulation."
        )

    @property
    def default_timeout(self) -> int:
        return 600

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "Subcommand: 'scan', 'c2', 'agent', or 'evasion'",
                },
                "target": {
                    "type": "string",
                    "description": "Target for scan (CIDR format, e.g. '10.0.0.0/24')",
                },
                "ports": {
                    "type": "string",
                    "description": "Comma-separated ports for scan (e.g. '22,80,443')",
                },
                "stealth": {
                    "type": "boolean",
                    "description": "Enable stealth mode for scan",
                },
                "host": {
                    "type": "string",
                    "description": "C2 server address for agent (default 127.0.0.1)",
                },
                "port": {
                    "type": "integer",
                    "description": "Port for C2 listener or agent (default 443)",
                },
                "psk": {
                    "type": "string",
                    "description": "Pre-shared key for C2 encryption",
                },
                "jitter": {
                    "type": "integer",
                    "description": "Beacon interval jitter in milliseconds",
                },
                "install": {
                    "type": "boolean",
                    "description": "Install persistence on agent (reboot survival)",
                },
                "extra_args": {
                    "type": "string",
                    "description": "Additional ZigHound arguments",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 600)",
                    "default": 600,
                },
            },
            "required": ["command"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "command")
        command = arguments["command"].lower()
        if command not in ("scan", "c2", "agent", "evasion"):
            raise ValueError(f"Invalid command: {command}. Must be scan, c2, agent, or evasion")
        if command == "scan":
            validate_required(arguments, "target")
        if command == "agent":
            validate_required(arguments, "host")
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"], max_val=3600)

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        command = arguments["command"].lower()
        cmd = ["zighound", command]

        if command == "scan":
            cmd.extend(["--target", arguments["target"]])
            if arguments.get("ports"):
                cmd.extend(["--ports", arguments["ports"]])
            if arguments.get("stealth"):
                cmd.append("--stealth")
            if arguments.get("jitter"):
                cmd.extend(["--jitter", str(arguments["jitter"])])

        elif command == "c2":
            cmd.append("listen")
            if arguments.get("port"):
                cmd.extend(["--port", str(arguments["port"])])
            if arguments.get("psk"):
                cmd.extend(["--psk", arguments["psk"]])

        elif command == "agent":
            cmd.extend(["--host", arguments["host"]])
            if arguments.get("port"):
                cmd.extend(["--port", str(arguments["port"])])
            if arguments.get("psk"):
                cmd.extend(["--psk", arguments["psk"]])
            if arguments.get("jitter"):
                cmd.extend(["--jitter", str(arguments["jitter"])])
            if arguments.get("install"):
                cmd.append("--install")

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
