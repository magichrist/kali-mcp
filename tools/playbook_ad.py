"""Playbook: Active Directory Assessment — enum4linux → bloodhound → netexec → crackmapexec."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool
from tools.persist import wrap_execution_result
from validation import validate_required


class PlaybookAdTool(BaseTool):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "playbook_ad"

    @property
    def description(self) -> str:
        return (
            "Active Directory assessment playbook: SMB enumeration "
            "(enum4linux) → attack path mapping (bloodhound) → protocol "
            "execution (netexec) → auth testing (crackmapexec). "
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
                    "description": "Domain controller host or IP",
                },
                "domain": {
                    "type": "string",
                    "description": "AD domain name (e.g. 'corp.local')",
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
        validate_required(arguments, "target")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["playbook_ad", arguments.get("target", "")]

    def _playbook(self, arguments: dict[str, Any]) -> dict[str, Any]:
        domain = arguments.get("domain") or arguments["target"]
        return {
            "name": "playbook_ad",
            "target": arguments["target"],
            "steps": [
                {
                    "parallel": False,
                    "tools": [
                        {"tool": "enum4linux", "args": {"target": "{{target}}"}},
                    ],
                },
                {
                    "parallel": False,
                    "tools": [
                        {"tool": "bloodhound", "args": {"domain": domain}},
                    ],
                },
                {
                    "parallel": True,
                    "tools": [
                        {
                            "tool": "netexec",
                            "args": {"target": "{{target}}", "protocol": "smb"},
                        },
                        {
                            "tool": "crackmapexec",
                            "args": {"target": "{{target}}", "protocol": "smb"},
                        },
                    ],
                },
            ],
        }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(arguments)
        from tools.playbook_engine import PlaybookEngine

        engine = PlaybookEngine()
        res = await engine.run(
            self._playbook(arguments), resume=bool(arguments.get("resume"))
        )
        return wrap_execution_result(res, self.name)
