"""Dirb wrapper for wordlist-based web content discovery."""

from __future__ import annotations

from typing import Any

from kali_mcp.tools.base import BaseTool
from kali_mcp.tools.normalization import NormalizedToolMixin
from kali_mcp.tools.persist import parse_dirb, run_tool_with_persistence
from kali_mcp.validation import validate_required


def _parse(stdout: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return parse_dirb(stdout), []


class DirbTool(BaseTool, NormalizedToolMixin):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "dirb"

    @property
    def description(self) -> str:
        return (
            "dirb web content scanner. Discovered URLs with response codes are "
            "parsed into structured findings."
        )

    @property
    def default_timeout(self) -> int:
        return 600

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target URL"},
                "wordlist": {"type": "string", "description": "Path to wordlist"},
                "recursive": {
                    "type": "boolean",
                    "description": "Recursive scan (-r)",
                    "default": False,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds",
                    "default": 600,
                },
            },
            "required": ["target", "wordlist"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target", "wordlist")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["dirb", arguments["target"], arguments["wordlist"]]
        if arguments.get("recursive"):
            cmd.append("-r")
        return cmd

    def normalize(self, stdout: str, stderr: str, exit_code: int, **kwargs: Any) -> dict[str, Any]:
        findings = parse_dirb(stdout)
        return {
            "normalized": {
                "paths_found": len(findings),
                "paths": [f["url"] for f in findings],
                "raw_output": (stdout or "").strip()[:2000],
            }
        }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await run_tool_with_persistence(self, arguments, parser=_parse)
