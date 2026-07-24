"""Python code execution tool — run Python scripts on the Kali machine."""

from __future__ import annotations

import logging

import os
import tempfile
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_timeout
from models import ToolError
from responses import success_response, error_response

logger = logging.getLogger("kali_mcp.tools")


class PythonCommandTool(BaseTool):
    @property
    def name(self) -> str:
        return "python_command"

    @property
    def description(self) -> str:
        return (
            "Execute Python code on the Kali machine. "
            "Write multi-line Python scripts with imports, functions, classes, etc. "
            "Use for data processing, API calls, parsing, automation, or anything "
            "better done in Python than bash. Returns stdout, stderr, exit code, and timing."
        )

    @property
    def default_timeout(self) -> int:
        return 300

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "code": {
                    "type": "string",
                    "description": "Python code to execute. Supports multi-line scripts with imports, functions, loops, etc.",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Execution timeout in seconds (default 300, max 3600)",
                    "default": 300,
                },
                "cwd": {
                    "type": "string",
                    "description": "Working directory for execution (optional)",
                    "default": "",
                },
            },
            "required": ["code"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "code")
        code = arguments["code"]
        if not isinstance(code, str) or not code.strip():
            raise ValueError("Code must be a non-empty string")
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"])

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["python3", "-c", arguments["code"]]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))
        except Exception as e:
            logger.exception("Tool %s failed", self.name)
            return error_response(ToolError(error="Execution failed", details=str(e)))

        code = arguments["code"]
        timeout = arguments.get("timeout", self.default_timeout)
        cwd = arguments.get("cwd") or None

        # Write code to a temp file and execute with python3
        tmp = tempfile.NamedTemporaryFile(
            mode="w", suffix=".py", prefix="mcp_exec_", delete=False
        )
        try:
            tmp.write(code)
            tmp.close()

            result = await engine.execute(
                command=["python3", tmp.name],
                tool=self.name,
                timeout=timeout,
                cwd=cwd,
            )

            return success_response(result)
        finally:
            os.unlink(tmp.name)
