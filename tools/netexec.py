"""NetExec (nxc) network execution tool."""

from __future__ import annotations

import shlex
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_ip, validate_cidr, validate_enum, validate_timeout
from models import ToolError
from responses import success_response, error_response


class NetexecTool(BaseTool):
    @property
    def name(self) -> str:
        return "netexec"

    @property
    def description(self) -> str:
        return "Run NetExec (nxc) for network protocol execution — SMB, WinRM, SSH, etc. Accepts IPs, CIDRs, and hostnames."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target IP, CIDR, or hostname"},
                "protocol": {"type": "string", "description": "Protocol: smb, winrm, ssh, ldap, rdp, mssql, ftp"},
                "extra_args": {"type": "string", "description": "Additional nxc arguments"},
                "timeout": {"type": "integer", "default": 300},
            },
            "required": ["target", "protocol"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target", "protocol")
        target = arguments["target"]
        try:
            validate_ip(target)
        except ValueError:
            try:
                validate_cidr(target)
            except ValueError:
                pass
        validate_enum(arguments["protocol"], ["smb", "winrm", "ssh", "ldap", "rdp", "mssql", "ftp"])
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"])

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["nxc", arguments["protocol"], arguments["target"]]
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
