"""Flowlyt CI/CD security analyzer tool."""

from __future__ import annotations

import logging

import shlex
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_timeout
from models import ToolError
from responses import success_response, error_response

logger = logging.getLogger("kali_mcp.tools")


class FlowlytTool(BaseTool):
    @property
    def name(self) -> str:
        return "flowlyt"

    @property
    def description(self) -> str:
        return (
            "Run Flowlyt multi-platform CI/CD security analyzer. "
            "Scans GitHub/GitLab/Bitbucket repos and workflow files for security issues."
        )

    @property
    def default_timeout(self) -> int:
        return 300

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "repo": {
                    "type": "string",
                    "description": "Repository to scan (e.g. 'owner/repo' or full URL)",
                },
                "workflow_file": {
                    "type": "string",
                    "description": "Specific workflow file to scan (e.g. '.github/workflows/ci.yml')",
                },
                "extra_args": {
                    "type": "string",
                    "description": "Additional Flowlyt arguments",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 300)",
                    "default": 300,
                },
            },
            "required": ["repo"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        pass

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["flowlyt", "scan"]

        if arguments.get("workflow_file"):
            cmd.extend(["--file", arguments["workflow_file"]])

        cmd.append(arguments["repo"])

        if "extra_args" in arguments:
            cmd.extend(shlex.split(arguments["extra_args"]))

        return cmd

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))
        except Exception as e:
            logger.exception("Tool %s failed", self.name)
            return error_response(ToolError(error="Execution failed", details=str(e)))

        timeout = arguments.get("timeout", self.default_timeout)
        cmd = self.build_command(arguments)

        result = await engine.execute(cmd, tool=self.name, timeout=timeout)
        return success_response(result)
