"""Playbook: External Reconnaissance — DAG-based web/network recon.

Uses the v2.0 DAG workflow engine with dependency-aware execution.
Defined in resources/playbooks/external_recon.yaml.
"""

from __future__ import annotations

from typing import Any

from kali_mcp.tools.base import BaseTool
from kali_mcp.tools.persist import wrap_execution_result
from kali_mcp.validation import validate_required


class PlaybookReconTool(BaseTool):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "playbook_recon"

    @property
    def description(self) -> str:
        return (
            "External reconnaissance via DAG workflow: validate scope → "
            "subdomain discovery (subfinder) → HTTP probing (httpx) → "
            "port scan (masscan/nmap) → tech fingerprinting (whatweb) → "
            "vulnerability scan (nuclei). Steps execute in dependency order "
            "with conditional gating and resume support."
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
        return ["playbook_recon", arguments.get("target", "")]

    def _playbook_definition(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Return a DAG playbook definition dict for external recon."""
        t = arguments["target"]
        steps = [
            {"id": "validate", "type": "scope_check", "args": {"target": t}},
            {
                "id": "discover",
                "tool": "subfinder",
                "depends_on": ["validate"],
                "args": {"domain": "{{target}}"},
            },
            {
                "id": "resolve",
                "tool": "httpx",
                "depends_on": ["discover"],
                "args": {"target": "{{target}}"},
            },
            {
                "id": "ports",
                "tool": "masscan",
                "depends_on": ["validate"],
                "args": {"target": "{{target}}"},
            },
            {
                "id": "technologies",
                "tool": "whatweb",
                "depends_on": ["resolve"],
                "args": {"target": "{{target}}"},
            },
            {
                "id": "nmap_scan",
                "tool": "nmap",
                "depends_on": ["ports"],
                "args": {"target": "{{target}}", "scan_type": "-sV"},
            },
        ]
        if not arguments.get("skip_nuclei"):
            steps.append(
                {
                    "id": "vuln_scan",
                    "tool": "nuclei",
                    "depends_on": ["resolve", "technologies"],
                    "args": {"target": "{{target}}"},
                }
            )
        steps.append(
            {
                "id": "correlate",
                "type": "finding_correlation",
                "depends_on": ["resolve", "technologies", "nmap_scan"],
                "args": {},
            }
        )
        steps.append(
            {
                "id": "report",
                "type": "assessment_report",
                "depends_on": ["correlate"],
                "args": {},
            }
        )
        return {
            "name": "playbook_recon",
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
        from kali_mcp.workflow import load_playbook, run_playbook_async

        pb = load_playbook(self._playbook_definition(arguments))
        res = await run_playbook_async(pb, resume=bool(arguments.get("resume", False)))
        return wrap_execution_result(res, self.name)
