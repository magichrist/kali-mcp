"""Gobuster wrapper for directory/DNS/vhost brute-force."""

from __future__ import annotations

from typing import Any

from kmcp.tools.base import BaseTool
from kmcp.tools.normalization import NormalizedToolMixin
from kmcp.tools.persist import parse_gobuster, run_tool_with_persistence
from kmcp.validation import validate_required


def _parse(stdout: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return parse_gobuster(stdout), []


class GobusterTool(BaseTool, NormalizedToolMixin):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "gobuster"

    @property
    def description(self) -> str:
        return (
            "Gobuster directory/DNS/vhost brute-forcer. Discovered paths with "
            "status codes are parsed into structured findings."
        )

    @property
    def default_timeout(self) -> int:
        return 600

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target URL or host"},
                "wordlist": {
                    "type": "string",
                    "description": "Path to wordlist",
                    "default": "/usr/share/wordlists/dirb/common.txt",
                },
                "mode": {
                    "type": "string",
                    "description": "Mode: dir, dns, vhost (default dir)",
                    "enum": ["dir", "dns", "vhost"],
                    "default": "dir",
                },
                "extensions": {
                    "type": "string",
                    "description": "Comma-separated extensions (e.g. php,html)",
                },
                "threads": {"type": "integer", "description": "Threads", "default": 10},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds",
                    "default": 600,
                },
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        mode = arguments.get("mode", "dir")
        wordlist = arguments.get("wordlist") or "/usr/share/wordlists/dirb/common.txt"
        cmd = ["gobuster", mode, "-u", arguments["target"], "-w", wordlist]
        extensions = arguments.get("extensions")
        if extensions and mode == "dir":
            cmd.extend(["-x", extensions])
        cmd.extend(["-t", str(arguments.get("threads", 10))])
        return cmd

    def normalize(self, stdout: str, stderr: str, exit_code: int, **kwargs: Any) -> dict[str, Any]:
        findings = parse_gobuster(stdout)
        return {
            "normalized": {
                "paths_found": len(findings),
                "paths": [f["url"] for f in findings],
                "raw_output": (stdout or "").strip()[:2000],
            }
        }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await run_tool_with_persistence(self, arguments, parser=_parse)
