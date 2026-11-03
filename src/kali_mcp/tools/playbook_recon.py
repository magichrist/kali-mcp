"""Playbook: External Reconnaissance — subfinder → httpx → nmap → whatweb → nuclei."""

from __future__ import annotations

from typing import Any

from kali_mcp.tools.base import BaseTool
from kali_mcp.tools.persist import wrap_execution_result


class PlaybookReconTool(BaseTool):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "playbook_recon"

    @property
    def description(self) -> str:
        return (
            "External reconnaissance playbook: passive subdomain enumeration "
            "(subfinder) → HTTP probing (httpx) → fast port scan (masscan) → "
            "tech fingerprinting (whatweb) → vulnerability scan (nuclei). "
            "All results are persisted to SQLite and the vault."
        )

    @property
    def default_timeout(self) -> int:
        return 1800

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Target domain or host (e.g. 'example.com')",
                },
                "skip_nuclei": {
                    "type": "boolean",
                    "description": "Skip the final vulnerability scan (default false)",
                    "default": False,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds",
                    "default": 1800,
                },
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        if not arguments.get("target"):
            raise ValueError("target is required")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["playbook_recon", arguments.get("target", "")]

    def _playbook(self, arguments: dict[str, Any]) -> dict[str, Any]:
        t = arguments["target"]
        steps: list[dict[str, Any]] = [
            {
                "parallel": False,
                "tools": [
                    {"tool": "subfinder", "args": {"domain": "{{target}}"}},
                ],
            },
            {
                "parallel": False,
                "tools": [
                    {"tool": "httpx", "args": {"target": "{{target}}"}},
                ],
            },
            {
                "parallel": False,
                "tools": [
                    {"tool": "masscan", "args": {"target": "{{target}}"}},
                ],
            },
            {
                "parallel": True,
                "tools": [
                    {"tool": "whatweb", "args": {"target": "{{target}}"}},
                    {
                        "tool": "nmap",
                        "args": {"target": "{{target}}", "scan_type": "quick"},
                    },
                ],
            },
        ]
        if not arguments.get("skip_nuclei"):
            steps.append(
                {
                    "parallel": False,
                    "tools": [
                        {"tool": "nuclei", "args": {"target": "{{target}}"}},
                    ],
                }
            )
        return {"name": "playbook_recon", "target": t, "steps": steps}

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(arguments)
        from kali_mcp.tools.playbook_engine import PlaybookEngine

        engine = PlaybookEngine()
        res = await engine.run(
            self._playbook(arguments), resume=bool(arguments.get("resume"))
        )
        return _wrap(res, self.name, arguments)


def _wrap(res: Any, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    """Convert an ExecutionResult into the standardized MCP response."""

    return wrap_execution_result(res, name)
