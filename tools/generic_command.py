"""Generic command execution tool — the escape hatch."""

from __future__ import annotations

import logging

import shlex
import os
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_timeout
from models import ExecutionResult, ToolError
from responses import success_response, error_response

logger = logging.getLogger("kali_mcp.tools")


class GenericCommandTool(BaseTool):
    @property
    def name(self) -> str:
        return "generic_command"

    @property
    def description(self) -> str:
        return (
            "Execute an arbitrary shell command on the Kali machine. "
            "Use this for any tool not listed as a native tool. "
            "Returns stdout, stderr, exit code, and timing information."
        )

    @property
    def default_timeout(self) -> int:
        return 300

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "command": {
                    "type": "string",
                    "description": "The full command string to execute (e.g. 'nmap -sV 10.0.0.1')",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Execution timeout in seconds (default 300, max 3600)",
                    "default": 300,
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for command execution (optional)",
                    "default": "",
                },
            },
            "required": ["command"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "command")
        cmd = arguments["command"]
        if not isinstance(cmd, str) or not cmd.strip():
            raise ValueError("Command must be a non-empty string")
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"])

    def build_command(self, arguments: dict[str, Any]) -> str:
        """Return the raw shell command string — execution engine handles shell mode."""
        return arguments["command"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))
        except Exception as e:
            logger.exception("Tool %s failed", self.name)
            return error_response(ToolError(error="Execution failed", details=str(e)))

        command_str = self.build_command(arguments)
        timeout = arguments.get("timeout", self.default_timeout)
        cwd = arguments.get("cwd") or None
        env = arguments.get("env")

        exec_env = os.environ.copy()
        if env:
            exec_env.update(env)

        result = await engine.execute(
            command=command_str,
            tool=self.name,
            timeout=timeout,
            cwd=cwd,
            env=exec_env,
        )

        return success_response(result)
