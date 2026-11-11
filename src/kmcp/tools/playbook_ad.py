"""Playbook: Active Directory Assessment — DAG-based.

Uses the v2.0 DAG workflow engine: validate → enum4linux → bloodhound →
netexec+crackmapexec (parallel) → correlate → report.
"""

from __future__ import annotations

from typing import Any

from kmcp.tools.base import BaseTool
from kmcp.tools.persist import wrap_execution_result
from kmcp.validation import validate_required


class PlaybookAdTool(BaseTool):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "playbook_ad"

    @property
    def description(self) -> str:
        return (
            "Active Directory assessment via DAG workflow: validate scope → "
            "SMB enumeration (enum4linux) → attack path mapping (bloodhound) → "
            "protocol execution (netexec) and auth testing (crackmapexec, "
            "parallel) → finding correlation → assessment report."
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
                "resume": {
                    "type": "boolean",
                    "description": "Skip steps completed in a previous run (default false)",
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
        validate_required(arguments, "target")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["playbook_ad", arguments.get("target", "")]

    def _playbook_definition(self, arguments: dict[str, Any]) -> dict[str, Any]:
        domain = arguments.get("domain") or arguments["target"]
        t = arguments["target"]
        steps = [
            {"id": "validate", "type": "scope_check", "args": {"target": t}},
            {
                "id": "enum4linux",
                "tool": "enum4linux",
                "depends_on": ["validate"],
                "args": {"target": "{{target}}"},
            },
            {
                "id": "bloodhound",
                "tool": "bloodhound",
                "depends_on": ["enum4linux"],
                "args": {"domain": domain},
            },
            {
                "id": "netexec",
                "tool": "netexec",
                "depends_on": ["bloodhound"],
                "args": {"target": "{{target}}", "protocol": "smb"},
                "parallel": True,
            },
            {
                "id": "crackmapexec",
                "tool": "crackmapexec",
                "depends_on": ["bloodhound"],
                "args": {"target": "{{target}}", "protocol": "smb"},
                "parallel": True,
            },
            {
                "id": "correlate",
                "type": "finding_correlation",
                "depends_on": ["netexec", "crackmapexec"],
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
            "name": "playbook_ad",
            "version": "2.0",
            "inputs": {"target": t},
            "execution": {
                "max_parallel": 4,
                "timeout": arguments.get("timeout", 1800),
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
