"""Wfuzz wrapper for web fuzzing (directories, parameters, headers)."""

from __future__ import annotations

from typing import Any

from kmcp.tools.base import BaseTool
from kmcp.tools.normalization import NormalizedToolMixin
from kmcp.tools.persist import parse_wfuzz, run_tool_with_persistence
from kmcp.validation import validate_required


def _parse(stdout: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return parse_wfuzz(stdout), []


class WfuzzTool(BaseTool, NormalizedToolMixin):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "wfuzz"

    @property
    def description(self) -> str:
        return (
            "wfuzz web fuzzer — fuzz directories, parameters, and headers using "
            "FUZZ placeholders. Result table hits are parsed into findings."
        )

    @property
    def default_timeout(self) -> int:
        return 600

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Target URL with FUZZ placeholder (e.g. http://host/FUZZ)",
                },
                "wordlist": {
                    "type": "string",
                    "description": "Path to wordlist",
                    "default": "/usr/share/wordlists/dirb/common.txt",
                },
                "methods": {
                    "type": "string",
                    "description": "HTTP method (-X), default GET",
                },
                "filters": {
                    "type": "string",
                    "description": "Filter expression, e.g. '--filter 200' → c=200",
                },
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
        target = arguments.get("target", "")
        if target and "FUZZ" not in target:
            raise ValueError("target URL must contain a FUZZ placeholder")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        wordlist = arguments.get("wordlist") or "/usr/share/wordlists/dirb/common.txt"
        cmd = ["wfuzz", "-w", wordlist, arguments["target"]]
        methods = arguments.get("methods")
        if methods:
            cmd.extend(["-X", methods])
        filters = arguments.get("filters")
        if filters:
            cmd.extend(["--filter", filters])
        return cmd

    def normalize(self, stdout: str, stderr: str, exit_code: int, **kwargs: Any) -> dict[str, Any]:
        findings = parse_wfuzz(stdout)
        return {
            "normalized": {
                "hits_found": len(findings),
                "urls": [f["url"] for f in findings],
                "raw_output": (stdout or "").strip()[:2000],
            }
        }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await run_tool_with_persistence(self, arguments, parser=_parse)
