"""WhatWeb technology fingerprinting tool."""

from __future__ import annotations

import shlex
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_timeout
from models import ToolError
from responses import success_response, error_response


class WhatwebTool(BaseTool):
    @property
    def name(self) -> str:
        return "whatweb"

    @property
    def description(self) -> str:
        return "Run whatweb for web technology fingerprinting — CMS, frameworks, libraries, plugins."

    @property
    def default_timeout(self) -> int:
        return 300

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target URL, domain, or IP"},
                "aggression": {"type": "integer", "description": "Aggression level 1-4 (default 1). 1=silent, 4=aggressive", "default": 1},
                "extra_args": {"type": "string", "description": "Additional whatweb arguments"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 300)", "default": 300},
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target")
        level = arguments.get("aggression", 1)
        if not isinstance(level, int) or level < 1 or level > 4:
            raise ValueError("Aggression level must be between 1 and 4")
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"])

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["whatweb", arguments["target"], f"-a{arguments.get('aggression', 1)}"]
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
