"""Metasploit Framework console wrapper (resource-script driven)."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool
from tools.normalization import NormalizedToolMixin
from tools.persist import run_tool_with_persistence


class MsfconsoleTool(BaseTool, NormalizedToolMixin):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "msfconsole"

    @property
    def description(self) -> str:
        return (
            "Metasploit Framework console driven by a resource script (.rc). "
            "Session/command output is returned as evidence."
        )

    @property
    def default_timeout(self) -> int:
        return 1200

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "resource": {
                    "type": "string",
                    "description": "Path to a Metasploit .rc resource script to execute",
                },
                "timeout": {"type": "integer", "description": "Timeout in seconds", "default": 1200},
            },
            "required": ["resource"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        resource = arguments.get("resource")
        if not isinstance(resource, str) or not resource.strip():
            raise ValueError("'resource' is required and must be a non-empty string")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["msfconsole", "-q", "-r", arguments["resource"]]

    def normalize(self, stdout: str, stderr: str, exit_code: int, **kwargs: Any) -> dict[str, Any]:
        return {"normalized": {"console_output": (stdout or "").strip()[:2000]}}

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await run_tool_with_persistence(self, arguments)
