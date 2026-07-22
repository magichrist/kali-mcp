"""Nuclei vulnerability scanner tool."""

from __future__ import annotations
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_timeout
from models import ToolError
from responses import success_response, error_response


class NucleiTool(BaseTool):
    @property
    def name(self) -> str:
        return "nuclei"

    @property
    def description(self) -> str:
        return "Run nuclei template-based vulnerability scanner against targets."

    @property
    def default_timeout(self) -> int:
        return 900

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target URL, domain, or IP"},
                "templates": {"type": "string", "description": "Template paths or IDs (e.g. 'cves/,misconfig/')"},
                "severity": {"type": "string", "description": "Filter by severity (e.g. 'critical,high')"},
                "extra_args": {"type": "string", "description": "Additional nuclei arguments"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 900)", "default": 900},
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target")
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"], max_val=3600)

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["nuclei", "-u", arguments["target"]]
        if "templates" in arguments:
            cmd.extend(["-t", arguments["templates"]])
        if "severity" in arguments:
            cmd.extend(["-severity", arguments["severity"]])
        if "extra_args" in arguments:
            cmd.extend(arguments["extra_args"].split())
        return cmd

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))
        return success_response(
            await engine.execute(command=self.build_command(arguments), tool=self.name, timeout=arguments.get("timeout", self.default_timeout))
        )
