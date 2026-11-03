"""Responder wrapper for LLMNR/NBT-NS/MDNS poisoning."""

from __future__ import annotations

from typing import Any

from kali_mcp.tools.base import BaseTool
from kali_mcp.tools.normalization import NormalizedToolMixin
from kali_mcp.tools.persist import parse_responder_hashes, run_tool_with_persistence
from kali_mcp.validation import validate_required


def _parse(stdout: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    findings = parse_responder_hashes(stdout)
    return findings, []


class ResponderTool(BaseTool, NormalizedToolMixin):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "responder"

    @property
    def description(self) -> str:
        return (
            "Responder LLMNR/NBT-NS/MDNS poisoner — captures authentication "
            "hashes (NTLMv1/NTLMv2) on the local network. Captured hashes are "
            "parsed from output and recorded as high-severity findings."
        )

    @property
    def default_timeout(self) -> int:
        return 300

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "interface": {
                    "type": "string",
                    "description": "Network interface to listen on (e.g. 'eth0')",
                },
                "analyze": {
                    "type": "boolean",
                    "description": "Passive analysis mode (poisoning disabled) (default false)",
                    "default": False,
                },
                "log_dir": {
                    "type": "string",
                    "description": "Directory for captured hash logs (default /usr/share/responder/logs)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 300)",
                    "default": 300,
                },
            },
            "required": ["interface"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "interface")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["responder", "-I", arguments["interface"]]
        if arguments.get("analyze"):
            cmd.append("-A")
        log_dir = arguments.get("log_dir")
        if log_dir:
            cmd.extend(["-lw", log_dir])
        return cmd

    def normalize(
        self, stdout: str, stderr: str, exit_code: int, **kwargs: Any
    ) -> dict[str, Any]:
        hashes = parse_responder_hashes(stdout)
        return {
            "normalized": {
                "hashes_captured": len(hashes),
                "poisoner_output": (stdout or "").strip()[:2000],
            }
        }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await run_tool_with_persistence(self, arguments, parser=_parse)
