"""CrackMapExec compatibility wrapper."""

from __future__ import annotations

import logging
import shlex
from typing import Any

from kmcp.execution import engine
from kmcp.models import ToolError
from kmcp.responses import error_response, success_response
from kmcp.tools.base import BaseTool
from kmcp.validation import validate_enum, validate_required, validate_timeout

logger = logging.getLogger("kmcp.tools")


class CrackmapexecTool(BaseTool):
    @property
    def name(self) -> str:
        return "crackmapexec"

    @property
    def description(self) -> str:
        return "Run CrackMapExec (cme) for network authentication and exploitation. Falls back to netexec (nxc) if cme is not installed."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target IP or CIDR"},
                "protocol": {
                    "type": "string",
                    "description": "Protocol: smb, winrm, ssh, ldap, rdp, mssql, ftp",
                },
                "extra_args": {
                    "type": "string",
                    "description": "Additional cme arguments",
                },
                "timeout": {"type": "integer", "default": 300},
            },
            "required": ["target", "protocol"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target", "protocol")
        validate_enum(
            arguments["protocol"],
            ["smb", "winrm", "ssh", "ldap", "rdp", "mssql", "ftp"],
        )
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"])

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["crackmapexec", arguments["protocol"], arguments["target"]]
        extra = arguments.get("extra_args")
        if extra:
            cmd.extend(shlex.split(extra))
        return cmd

    def _build_fallback_command(self, arguments: dict[str, Any]) -> list[str]:
        """Build command using netexec as fallback."""
        cmd = ["nxc", arguments["protocol"], arguments["target"]]
        extra = arguments.get("extra_args")
        if extra:
            cmd.extend(shlex.split(extra))
        return cmd

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))
        except Exception as e:
            logger.exception("Tool %s failed", self.name)
            return error_response(ToolError(error="Execution failed", details=str(e)))

        import shutil

        # Try crackmapexec first
        if shutil.which("crackmapexec"):
            result = await engine.execute(
                command=self.build_command(arguments),
                tool=self.name,
                timeout=arguments.get("timeout", self.default_timeout),
            )
            return success_response(result)

        # Fallback to netexec (nxc)
        if shutil.which("nxc"):
            result = await engine.execute(
                command=self._build_fallback_command(arguments),
                tool="netexec",
                timeout=arguments.get("timeout", self.default_timeout),
            )
            return success_response(result)

        return error_response(
            ToolError(error="Neither crackmapexec nor netexec (nxc) found on system")
        )
