"""Playbook registry + status tools for AI agents."""

from __future__ import annotations

import json
from typing import Any

from kali_mcp.models import ExecutionResult, ToolError, utc_now_iso
from kali_mcp.responses import error_response, success_response
from kali_mcp.tools.base import BaseTool

BUILTIN_PLAYBOOKS: dict[str, dict[str, Any]] = {
    "playbook_recon": {
        "description": "External recon: subfinder → httpx → masscan → whatweb+nmap (parallel) → nuclei",
        "input": {"target": "domain or host"},
    },
    "playbook_webapp": {
        "description": "Web app: katana → arjun+ffuf (parallel) → nuclei → sqlmap+commix (parallel)",
        "input": {"target": "URL", "wordlist": "optional"},
    },
    "playbook_ad": {
        "description": "AD: enum4linux → bloodhound → netexec+crackmapexec (parallel)",
        "input": {"target": "DC host/IP", "domain": "AD domain"},
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
            "List available playbooks with their pipelines and required inputs. "
            "Execute one via its tool name (e.g. playbook_recon) or via "
            "playbook_engine for custom step sequences."
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
        from kali_mcp.tools.playbook_engine import RUN_STATUS

        playbooks = {
            name: {**meta, "last_status": RUN_STATUS.get(name, {}).get("status")}
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
            "Check the run status of a playbook — which steps completed, which "
            "remain — to decide whether to resume an interrupted run."
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
        from kali_mcp.tools.playbook_engine import RUN_STATUS

        name = arguments.get("name")
        if name and name not in RUN_STATUS:
            return error_response(
                ToolError(error="Unknown playbook", details=f"no run recorded for '{name}'")
            )
        statuses = {name: RUN_STATUS[name]} if name else dict(RUN_STATUS)
        return _make_result(self.name, {"statuses": statuses})
