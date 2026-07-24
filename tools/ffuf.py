"""FFUF web fuzzer tool."""

from __future__ import annotations

import shlex
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_timeout
from models import ToolError
from responses import success_response, error_response


class FfufTool(BaseTool):
    @property
    def name(self) -> str:
        return "ffuf"

    @property
    def description(self) -> str:
        return "Run ffuf for web fuzzing — directory discovery, parameter fuzzing, vhost enumeration."

    @property
    def default_timeout(self) -> int:
        return 600

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target URL with FUZZ keyword (e.g. 'https://target.com/FUZZ')"},
                "wordlist": {"type": "string", "description": "Path to wordlist file"},
                "filter": {"type": "string", "description": "Filter flags (e.g. '-fc 404 -fs 0')"},
                "extra_args": {"type": "string", "description": "Additional ffuf arguments"},
                "timeout": {"type": "integer", "description": "Timeout in seconds (default 600)", "default": 600},
            },
            "required": ["target", "wordlist"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target", "wordlist")
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"])

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        target = arguments["target"]
        if not target.startswith(("http://", "https://")):
            target = f"http://{target}"
        cmd = ["ffuf", "-u", target, "-w", arguments["wordlist"]]
        filter_val = arguments.get("filter")
        if filter_val:
            cmd.extend(shlex.split(filter_val))
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
