"""Amass attack surface mapping tool."""

from __future__ import annotations

import shlex
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_domain, validate_enum, validate_timeout
from models import ToolError
from responses import success_response, error_response


class AmassTool(BaseTool):
    @property
    def name(self) -> str:
        return "amass"

    @property
    def description(self) -> str:
        return "Run amass for attack surface mapping and subdomain enumeration."

    @property
    def default_timeout(self) -> int:
        return 900

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domain": {"type": "string", "description": "Target domain"},
                "mode": {"type": "string", "description": "Amass mode: 'enum' (default) or 'intel'", "default": "enum"},
                "extra_args": {"type": "string", "description": "Additional amass arguments"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 900)", "default": 900},
            },
            "required": ["domain"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "domain")
        validate_domain(arguments["domain"])
        if "mode" in arguments:
            validate_enum(arguments["mode"], ["enum", "intel"])
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"], max_val=3600)

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        mode = arguments.get("mode", "enum")
        cmd = ["amass", mode, "-d", arguments["domain"]]
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
