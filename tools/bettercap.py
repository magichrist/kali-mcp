"""Bettercap wrapper for MITM / network sniffing."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool
from tools.normalization import NormalizedToolMixin
from tools.persist import run_tool_with_persistence
from validation import validate_required


def _parse(stdout: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Extract credential-capture events from bettercap session output."""
    findings = []
    for line in (stdout or "").splitlines():
        if "captured" in line.lower() or ("password" in line.lower() and ">>" in line):
            findings.append({
                "type": "captured_credential",
                "severity": "high",
                "title": "Bettercap captured data",
                "description": line.strip()[:200],
                "evidence": line.strip(),
            })
    return findings, []


class BettercapTool(BaseTool, NormalizedToolMixin):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "bettercap"

    @property
    def description(self) -> str:
        return (
            "Bettercap MITM framework — network sniffing, ARP/DNS spoofing, "
            "credential capture, and WiFi/BLE recon via a caplet or eval commands."
        )

    @property
    def default_timeout(self) -> int:
        return 600

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Target address or CIDR (e.g. '192.168.1.0/24')",
                },
                "interface": {
                    "type": "string",
                    "description": "Network interface to use (e.g. 'eth0')",
                },
                "caplet": {
                    "type": "string",
                    "description": "Path to a .cap caplet file to run",
                },
                "modules": {
                    "type": "string",
                    "description": "Eval commands to activate modules (e.g. 'net.sniff on; arp.spoof on')",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 600)",
                    "default": 600,
                },
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target")
        if not arguments.get("caplet") and not arguments.get("modules"):
            raise ValueError("either 'caplet' or 'modules' must be provided")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["bettercap", "-eval", f"set arp.spoof.targets {arguments['target']}"]
        interface = arguments.get("interface")
        if interface:
            cmd.extend(["-iface", interface])
        caplet = arguments.get("caplet")
        if caplet:
            cmd.extend(["-caplet", caplet])
        modules = arguments.get("modules")
        if modules:
            cmd.extend(["-eval", modules])
        return cmd

    def normalize(self, stdout: str, stderr: str, exit_code: int, **kwargs: Any) -> dict[str, Any]:
        return {"normalized": {"session_output": (stdout or "").strip()[:2000]}}

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await run_tool_with_persistence(self, arguments, parser=_parse)
