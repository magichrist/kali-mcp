"""John the Ripper wrapper for password hash cracking."""

from __future__ import annotations

from typing import Any

from tools.base import BaseTool
from tools.normalization import NormalizedToolMixin
from tools.persist import parse_john, run_tool_with_persistence
from validation import validate_required


def _parse(stdout: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    creds = parse_john(stdout)
    findings = [
        {
            "type": "cracked_password",
            "severity": "high",
            "title": f"Cracked hash: {c.get('username') or c.get('hash', '')[:24]}",
            "description": f"password={c['password']}",
            "evidence": str(c),
        }
        for c in creds
    ]
    return findings, creds


class JohnTool(BaseTool, NormalizedToolMixin):
    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "john"

    @property
    def description(self) -> str:
        return (
            "John the Ripper password cracker. Cracked passwords are parsed "
            "from output and stored as credentials."
        )

    @property
    def default_timeout(self) -> int:
        return 900

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "hash_file": {"type": "string", "description": "Path to the hash file"},
                "format": {
                    "type": "string",
                    "description": "Hash format (e.g. md5crypt, raw-sha1)",
                },
                "wordlist": {
                    "type": "string",
                    "description": "Path to wordlist for --wordlist mode",
                },
                "show": {
                    "type": "boolean",
                    "description": "Show cracked passwords (--show)",
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
        cmd = ["john"]
        fmt = arguments.get("format")
        if fmt:
            cmd.extend(["--format", fmt])
        wordlist = arguments.get("wordlist")
        if wordlist:
            cmd.extend(["--wordlist", wordlist])
        if arguments.get("show"):
            cmd.append("--show")
        cmd.append(arguments["hash_file"])
        return cmd

    def normalize(
        self, stdout: str, stderr: str, exit_code: int, **kwargs: Any
    ) -> dict[str, Any]:
        creds = parse_john(stdout)
        return {
            "normalized": {
                "cracked_count": len(creds),
                "credentials": creds,
                "raw_output": (stdout or "").strip()[:2000],
            }
        }

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        return await run_tool_with_persistence(self, arguments, parser=_parse)
