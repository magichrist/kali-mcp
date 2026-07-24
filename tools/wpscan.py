"""WPScan WordPress scanner tool."""

from __future__ import annotations

import shlex
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_url, validate_timeout
from models import ToolError
from responses import success_response, error_response


class WpscanTool(BaseTool):
    @property
    def name(self) -> str:
        return "wpscan"

    @property
    def description(self) -> str:
        return "Run wpscan for WordPress vulnerability scanning."

    @property
    def default_timeout(self) -> int:
        return 600

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "WordPress site URL"},
                "enumerate": {"type": "string", "description": "Enumeration options (e.g. 'vp,vt,u')"},
                "extra_args": {"type": "string", "description": "Additional wpscan arguments"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 600)", "default": 600},
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target")
        validate_url(arguments["target"])
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"])

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["wpscan", "--url", arguments["target"]]
        if arguments.get("enumerate"):
            cmd.extend(["--enumerate", arguments["enumerate"]])
        extra = arguments.get("extra_args")
        if extra:
            cmd.extend(shlex.split(extra))
        return cmd

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))
        return success_response(
            await engine.execute(command=self.build_command(arguments), tool=self.name, timeout=arguments.get("timeout", self.default_timeout))
        )
