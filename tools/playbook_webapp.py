"""Playbook: Web Application Assessment — katana → arjun → ffuf → nuclei → sqlmap → commix."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool
from tools.persist import wrap_execution_result
from validation import validate_required, validate_url


class PlaybookWebappTool(BaseTool):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "playbook_webapp"

    @property
    def description(self) -> str:
        return (
            "Web application assessment playbook: crawling (katana) → parameter "
            "discovery (arjun) → directory fuzzing (ffuf) → vulnerability scan "
            "(nuclei) → SQLi (sqlmap) → command injection (commix). "
            "All results are persisted to SQLite and the vault."
        )

    @property
    def default_timeout(self) -> int:
        return 2400

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Target URL (e.g. 'http://example.com')",
                },
                "wordlist": {
                    "type": "string",
                    "description": "Wordlist for ffuf (default /usr/share/wordlists/dirb/common.txt)",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds",
                    "default": 2400,
                },
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target")
        validate_url(arguments["target"])

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["playbook_webapp", arguments.get("target", "")]

    def _playbook(self, arguments: dict[str, Any]) -> dict[str, Any]:
        wordlist = arguments.get("wordlist") or "/usr/share/wordlists/dirb/common.txt"
        t = arguments["target"]
        return {
            "name": "playbook_webapp",
            "target": t,
            "steps": [
                {
                    "parallel": False,
                    "tools": [
                        {"tool": "katana", "args": {"target": "{{target}}"}},
                    ],
                },
                {
                    "parallel": True,
                    "tools": [
                        {"tool": "arjun", "args": {"target": "{{target}}"}},
                        {
                            "tool": "ffuf",
                            "args": {"target": "{{target}}", "wordlist": wordlist},
                        },
                    ],
                },
                {
                    "parallel": False,
                    "tools": [
                        {"tool": "nuclei", "args": {"target": "{{target}}"}},
                    ],
                },
                {
                    "parallel": True,
                    "tools": [
                        {"tool": "sqlmap", "args": {"target": "{{target}}"}},
                        {"tool": "commix", "args": {"target": "{{target}}"}},
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
