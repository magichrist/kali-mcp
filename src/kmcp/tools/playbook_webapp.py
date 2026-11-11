"""Playbook: Web Application Assessment — DAG-based.

Uses the v2.0 DAG workflow engine: validate → crawl (katana) → param discovery
(arjun) + dir fuzzing (ffuf, parallel) → nuclei → sqlmap+commix (parallel) →
correlate → report.
"""

from __future__ import annotations

from typing import Any

from kmcp.tools.base import BaseTool
from kmcp.tools.persist import wrap_execution_result
from kmcp.validation import validate_required, validate_url


class PlaybookWebappTool(BaseTool):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "playbook_webapp"

    @property
    def description(self) -> str:
        return (
            "Web application assessment via DAG workflow: validate scope → "
            "crawling (katana) → parameter discovery (arjun) and directory "
            "fuzzing (ffuf, parallel) → vulnerability scan (nuclei) → "
            "SQLi (sqlmap) and command injection (commix, parallel) → "
            "finding correlation → assessment report."
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
                "resume": {
                    "type": "boolean",
                    "description": "Skip steps completed in a previous run (default false)",
                    "default": False,
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

    def _playbook_definition(self, arguments: dict[str, Any]) -> dict[str, Any]:
        wordlist = arguments.get("wordlist") or "/usr/share/wordlists/dirb/common.txt"
        t = arguments["target"]
        steps = [
            {"id": "validate", "type": "scope_check", "args": {"target": t}},
            {
                "id": "crawl",
                "tool": "katana",
                "depends_on": ["validate"],
                "args": {"target": "{{target}}"},
            },
            {
                "id": "params",
                "tool": "arjun",
                "depends_on": ["crawl"],
                "args": {"target": "{{target}}"},
            },
            {
                "id": "ffuf",
                "tool": "ffuf",
                "depends_on": ["crawl"],
                "args": {"target": "{{target}}", "wordlist": wordlist},
                "parallel": True,
            },
            {
                "id": "nuclei",
                "tool": "nuclei",
                "depends_on": ["crawl", "params", "ffuf"],
                "args": {"target": "{{target}}"},
            },
            {
                "id": "sqlmap",
                "tool": "sqlmap",
                "depends_on": ["params"],
                "args": {"target": "{{target}}"},
                "parallel": True,
            },
            {
                "id": "commix",
                "tool": "commix",
                "depends_on": ["params"],
                "args": {"target": "{{target}}"},
                "parallel": True,
            },
            {
                "id": "correlate",
                "type": "finding_correlation",
                "depends_on": ["nuclei", "sqlmap", "commix"],
                "args": {},
            },
            {
                "id": "report",
                "type": "assessment_report",
                "depends_on": ["correlate"],
                "args": {},
            },
        ]
        return {
            "name": "playbook_webapp",
            "version": "2.0",
            "inputs": {"target": t},
            "execution": {
                "max_parallel": 4,
                "timeout": arguments.get("timeout", 2400),
                "resume": bool(arguments.get("resume", False)),
            },
            "steps": steps,
        }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        self.validate(arguments)
        from kmcp.workflow import load_playbook, run_playbook_async

        pb = load_playbook(self._playbook_definition(arguments))
        res = await run_playbook_async(pb, resume=bool(arguments.get("resume", False)))
        return wrap_execution_result(res, self.name)
