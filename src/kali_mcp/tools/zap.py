"""OWASP ZAP wrapper for web application vulnerability scanning."""

from __future__ import annotations

from typing import Any

from kali_mcp.tools.base import BaseTool
from kali_mcp.tools.normalization import NormalizedToolMixin
from kali_mcp.tools.persist import run_tool_with_persistence
from kali_mcp.validation import validate_required, validate_url


def _parse(stdout: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract ZAP alert lines ([severity] url: title) as findings."""
    findings = []
    for line in (stdout or "").splitlines():
        line = line.strip()
        if line.startswith(("INFO", "LOW", "MEDIUM", "HIGH")) and ":" in line:
            severity = line.split(":", 1)[0].lower()
            if severity == "info":
                severity = "informational"
            findings.append(
                {
                    "type": "zap_alert",
                    "severity": severity
                    if severity in ("informational", "low", "medium", "high")
                    else "informational",
                    "title": line[:120],
                    "description": line[:300],
                    "evidence": line,
                }
            )
    return findings, []


class ZapTool(BaseTool, NormalizedToolMixin):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "zap"

    @property
    def description(self) -> str:
        return (
            "OWASP ZAP baseline web application scanner. Alerts with severities "
            "are parsed into structured findings."
        )

    @property
    def default_timeout(self) -> int:
        return 900

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {"type": "string", "description": "Target URL to scan"},
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds",
                    "default": 900,
                },
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target")
        validate_url(arguments["target"])

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["zap-baseline.py", "-t", arguments["target"]]

    def normalize(self, stdout: str, stderr: str, exit_code: int, **kwargs: Any) -> dict[str, Any]:
        return {"normalized": {"scan_output": (stdout or "").strip()[:2000]}}

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await run_tool_with_persistence(self, arguments, parser=_parse)
