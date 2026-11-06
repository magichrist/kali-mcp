"""Playbook registry + status tools for AI agents (v2.0 DAG-aware)."""

from __future__ import annotations

import json
from typing import Any

from kali_mcp.models import ExecutionResult, ToolError, utc_now_iso
from kali_mcp.responses import error_response, success_response
from kali_mcp.tools.base import BaseTool


def _workflow_run_status() -> dict:
    """Lazy import of the workflow RUN_STATUS dict (breaks circular import)."""
    from kali_mcp.workflow import RUN_STATUS

    return RUN_STATUS

BUILTIN_PLAYBOOKS: dict[str, dict[str, Any]] = {
    "playbook_recon": {
        "description": "External recon: validate → subfinder → httpx → masscan → whatweb+nmap (parallel) → nuclei → correlate → report",
        "input": {"target": "domain or host", "skip_nuclei": "optional bool", "resume": "optional bool"},
        "workflow": "external_recon",
    },
    "playbook_webapp": {
        "description": "Web app: validate → katana → arjun+ffuf (parallel) → nuclei → sqlmap+commix (parallel) → correlate → report",
        "input": {"target": "URL", "wordlist": "optional path", "resume": "optional bool"},
        "workflow": "web_assessment",
    },
    "playbook_ad": {
        "description": "AD: validate → enum4linux → bloodhound → netexec+crackmapexec (parallel) → correlate → report",
        "input": {"target": "DC host/IP", "domain": "optional AD domain", "resume": "optional bool"},
        "workflow": "ad_assessment",
    },
}


def _make_result(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Build an MCP success response carrying `payload` as its stdout JSON."""
    result = ExecutionResult(
        tool=tool_name,
        command=tool_name,
        stdout=json.dumps(payload, indent=2),
        stderr="",
        exit_code=0,
        success=True,
        timed_out=False,
        duration=0.0,
        start_time=utc_now_iso(),
        end_time=utc_now_iso(),
    )
    return success_response(result)


class PlaybookListTool(BaseTool):
    @property
    def name(self) -> str:
        return "playbook_list"

    @property
    def description(self) -> str:
        return (
            "List available DAG playbooks with their steps and required inputs. "
            "Execute one via its tool name (e.g. playbook_recon) or via "
            "playbook_engine for custom DAG sequences."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_status": {
                    "type": "boolean",
                    "description": "Include last-run status per playbook (default true)",
                    "default": True,
                },
            },
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        pass

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["playbook_list"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        playbooks = {
            name: {**meta, "last_status": _workflow_run_status().get(name, {}).get("status")}
            for name, meta in BUILTIN_PLAYBOOKS.items()
        }
        return _make_result(self.name, {"playbooks": playbooks})


class PlaybookStatusTool(BaseTool):
    @property
    def name(self) -> str:
        return "playbook_status"

    @property
    def description(self) -> str:
        return (
            "Check the run status of a DAG playbook — which steps completed, "
            "which remain — to decide whether to resume an interrupted run."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Playbook name (omit for all known statuses)",
                },
            },
            "required": [],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        pass

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["playbook_status", arguments.get("name", "")]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        name = arguments.get("name")
        run_status = _workflow_run_status()
        if name and name not in run_status:
            return error_response(
                ToolError(error="Unknown playbook", details=f"no run recorded for '{name}'")
            )
        statuses = {name: run_status[name]} if name else dict(run_status)
        return _make_result(self.name, {"statuses": statuses})
