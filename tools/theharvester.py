"""theHarvester OSINT tool."""

from __future__ import annotations

import shlex
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_domain, validate_timeout
from models import ToolError
from responses import success_response, error_response


class TheharvesterTool(BaseTool):
    @property
    def name(self) -> str:
        return "theharvester"

    @property
    def description(self) -> str:
        return "Run theHarvester for email, subdomain, and name harvesting from public sources."

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Target domain"},
                "source": {"type": "string", "description": "Data sources (e.g. 'all', 'google,bing,linkedin')", "default": "all"},
                "limit": {"type": "integer", "description": "Max results per source (default 500)", "default": 500},
                "extra_args": {"type": "string", "description": "Additional theHarvester arguments"},
                "timeout": {"type": "integer", "default": 300},
            },
            "required": ["domain"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "domain")
        validate_domain(arguments["domain"])
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"])

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["theHarvester", "-d", arguments["domain"], "-b", arguments.get("source", "all"), "-l", str(arguments.get("limit", 500))]
        if "extra_args" in arguments:
            cmd.extend(shlex.split(arguments.get("extra_args") or ""))
        return cmd

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))
        return success_response(
            await engine.execute(command=self.build_command(arguments), tool=self.name, timeout=arguments.get("timeout", self.default_timeout))
        )
