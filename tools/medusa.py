"""Medusa wrapper for parallelized login brute-force."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool
from tools.normalization import NormalizedToolMixin
from tools.persist import parse_medusa, run_tool_with_persistence
from validation import validate_required


def _parse(stdout: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    creds = parse_medusa(stdout)
    findings = [
        {
            "type": "credential",
            "severity": "critical",
            "title": f"Valid credentials: {c['username']} on {c['service']}",
            "description": f"host={c['host']}",
            "evidence": str(c),
            "service": c["service"],
        }
        for c in creds
    ]
    return findings, creds


class MedusaTool(BaseTool, NormalizedToolMixin):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "medusa"

    @property
    def description(self) -> str:
        return (
            "Medusa parallelized login brute-forcer — audit many hosts/services "
            "concurrently. Valid credentials found are parsed and stored."
        )

    @property
    def default_timeout(self) -> int:
        return 600

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target address"},
                "service": {
                    "type": "string",
                    "description": "Service to attack (ssh, ftp, smb, http, etc.)",
                },
                "user_list": {"type": "string", "description": "Path to user list"},
                "pass_list": {"type": "string", "description": "Path to password list"},
                "port": {"type": "integer", "description": "Port number"},
                "threads": {"type": "integer", "description": "Threads"},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds",
                    "default": 600,
                },
            },
            "required": ["target", "service", "user_list", "pass_list"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target", "service", "user_list", "pass_list")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = [
            "medusa",
            "-H",
            arguments["target"],
            "-U",
            arguments["user_list"],
            "-P",
            arguments["pass_list"],
            "-M",
            arguments["service"],
            "-t",
            str(arguments.get("threads", 4)),
        ]
        port = arguments.get("port")
        if port:
            cmd.extend(["-n", str(port)])
        return cmd

    def normalize(
        self, stdout: str, stderr: str, exit_code: int, **kwargs: Any
    ) -> dict[str, Any]:
        creds = parse_medusa(stdout)
        return {
            "normalized": {
                "credentials_found": len(creds),
                "credentials": creds,
                "service_output": (stdout or "").strip()[:2000],
            }
        }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await run_tool_with_persistence(self, arguments, parser=_parse)
