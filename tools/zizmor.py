"""Zizmor GitHub Actions security scanner tool."""

from __future__ import annotations

import logging

import os
import shlex
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_timeout
from models import ToolError
from responses import success_response, error_response

logger = logging.getLogger("kali_mcp.tools")


class ZizmorTool(BaseTool):
    @property
    def name(self) -> str:
        return "zizmor"

    @property
    def description(self) -> str:
        return (
            "Run zizmor static analysis on GitHub Actions workflows. "
            "Scans workflow files, action definitions, and Dependabot configs "
            "for security issues. Accepts local paths or user/repo slugs."
        )

    @property
    def default_timeout(self) -> int:
        return 120

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": (
                        "Target to audit: workflow file, directory, action.yml, "
                        "or GitHub slug (e.g. 'owner/repo')"
                    ),
                },
                "collect": {
                    "type": "string",
                    "description": "What to collect: all, default, workflows, actions, dependabot",
                    "default": "all",
                },
                "extra_args": {
                    "type": "string",
                    "description": "Additional zizmor arguments",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 120)",
                    "default": 120,
                },
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        pass

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["zizmor"]

        collect = arguments.get("collect", "all")
        cmd.extend(["--collect", collect])

        cmd.append(arguments["target"])

        extra = arguments.get("extra_args")
        if extra:
            cmd.extend(shlex.split(extra))

        gh_token = os.getenv("GH_TOKEN", "")
        if gh_token:
            cmd.extend(["--gh-token", gh_token])

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
