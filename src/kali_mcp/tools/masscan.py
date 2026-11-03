"""Masscan wrapper for high-speed port scanning."""

from __future__ import annotations

from typing import Any

from kali_mcp.tools.base import BaseTool
from kali_mcp.tools.normalization import NormalizedToolMixin
from kali_mcp.tools.persist import parse_masscan, run_tool_with_persistence
from kali_mcp.validation import validate_ports, validate_required


def _parse(stdout: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    return parse_masscan(stdout), []


class MasscanTool(BaseTool, NormalizedToolMixin):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "masscan"

    @property
    def description(self) -> str:
        return (
            "masscan — the fastest TCP/UDP port scanner. Discovered open ports "
            "are parsed into structured findings."
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
                    "description": "Target IP or CIDR range (e.g. 10.0.0.0/24)",
                },
                "ports": {
                    "type": "string",
                    "description": "Ports to scan (e.g. '80,443' or '1-65535')",
                },
                "rate": {
                    "type": "integer",
                    "description": "Packet rate (default 1000)",
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
        ports = arguments.get("ports")
        if ports:
            validate_ports(ports)

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["masscan", arguments["target"]]
        ports = arguments.get("ports")
        if ports:
            cmd.extend(["-p", ports])
        cmd.extend(["--rate", str(arguments.get("rate", 1000))])
        return cmd

    def normalize(self, stdout: str, stderr: str, exit_code: int, **kwargs: Any) -> dict[str, Any]:
        findings = parse_masscan(stdout)
        return {
            "normalized": {
                "open_ports": len(findings),
                "ports": [{"port": f["port"], "protocol": f["service"]} for f in findings],
                "raw_output": (stdout or "").strip()[:2000],
            }
        }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await run_tool_with_persistence(self, arguments, parser=_parse)
