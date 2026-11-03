"""Hashcat wrapper for GPU-accelerated hash cracking."""

from __future__ import annotations

from typing import Any

from kali_mcp.tools.base import BaseTool
from kali_mcp.tools.normalization import NormalizedToolMixin
from kali_mcp.tools.persist import parse_hashcat, run_tool_with_persistence
from kali_mcp.validation import validate_required


def _parse(stdout: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    creds = parse_hashcat(stdout)
    findings = [
        {
            "type": "cracked_password",
            "severity": "high",
            "title": f"Cracked hash: {c['username'][:24]}…",
            "description": f"password={c['password']}",
            "evidence": str(c),
        }
        for c in creds
    ]
    return findings, creds


class HashcatTool(BaseTool, NormalizedToolMixin):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "hashcat"

    @property
    def description(self) -> str:
        return (
            "Hashcat GPU password recovery. Cracked hash:password pairs are "
            "parsed from output and stored as credentials."
        )

    @property
    def default_timeout(self) -> int:
        return 900

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "hash_file": {"type": "string", "description": "Path to the hash file"},
                "mode": {
                    "type": "integer",
                    "description": "Hash mode number (-m), e.g. 0 for MD5",
                },
                "wordlist": {"type": "string", "description": "Path to wordlist"},
                "rule": {"type": "string", "description": "Rule file (-r)"},
                "show": {
                    "type": "boolean",
                    "description": "Show cracked hashes (--show)",
                    "default": False,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds",
                    "default": 900,
                },
            },
            "required": ["hash_file"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "hash_file")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["hashcat"]
        mode = arguments.get("mode")
        if mode is not None:
            cmd.extend(["-m", str(mode)])
        wordlist = arguments.get("wordlist")
        if wordlist:
            cmd.append(wordlist)
        rule = arguments.get("rule")
        if rule:
            cmd.extend(["-r", rule])
        if arguments.get("show"):
            cmd.append("--show")
        cmd.append(arguments["hash_file"])
        return cmd

    def normalize(self, stdout: str, stderr: str, exit_code: int, **kwargs: Any) -> dict[str, Any]:
        creds = parse_hashcat(stdout)
        return {
            "normalized": {
                "cracked_count": len(creds),
                "credentials": creds,
                "raw_output": (stdout or "").strip()[:2000],
            }
        }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await run_tool_with_persistence(self, arguments, parser=_parse)
