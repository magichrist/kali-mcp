"""Searchsploit exploit database search tool."""

from __future__ import annotations

import logging

import shlex
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_timeout
from models import ToolError
from responses import success_response, error_response

logger = logging.getLogger("kali_mcp.tools")


class SearchsploitTool(BaseTool):
    @property
    def name(self) -> str:
        return "searchsploit"

    @property
    def description(self) -> str:
        return "Search Exploit-DB for exploits. Search by keyword, CVE, EDB-ID, or title."

    @property
    def default_timeout(self) -> int:
        return 60

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Search terms (e.g. 'apache struts 2.0.0', 'windows kernel 3.2')",
                },
                "cve": {
                    "type": "string",
                    "description": "Search by CVE ID (e.g. '2021-44228')",
                },
                "edb_id": {
                    "type": "string",
                    "description": "Search by Exploit-DB ID (e.g. '39446')",
                },
                "title": {
                    "type": "boolean",
                    "description": "Search title only (slower but more precise)",
                },
                "exact": {
                    "type": "boolean",
                    "description": "Exact title match (requires -t)",
                },
                "exclude": {
                    "type": "string",
                    "description": "Exclude results matching regex (e.g. '(PoC)|/dos/')",
                },
                "json": {
                    "type": "boolean",
                    "description": "Output results as JSON",
                },
                "extra_args": {
                    "type": "string",
                    "description": "Additional searchsploit arguments",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 60)",
                    "default": 60,
                },
            },
            "required": [],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        has_query = bool(arguments.get("query", "").strip())
        has_cve = bool(arguments.get("cve", "").strip())
        has_edb = bool(arguments.get("edb_id", "").strip())
        if not has_query and not has_cve and not has_edb:
            raise ValueError("At least one of query, cve, or edb_id is required")
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"])

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["searchsploit"]

        if arguments.get("title"):
            cmd.append("-t")
        if arguments.get("exact"):
            cmd.extend(["-t", "-e"])
        if arguments.get("json"):
            cmd.append("-j")
        if arguments.get("exclude"):
            cmd.extend(["--exclude", arguments["exclude"]])

        if "cve" in arguments and arguments["cve"].strip():
            cmd.extend(["--cve", arguments["cve"].strip()])
        elif "edb_id" in arguments and arguments["edb_id"].strip():
            cmd.extend(["-p", arguments["edb_id"].strip()])

        if "query" in arguments and arguments["query"].strip():
            cmd.extend(shlex.split(arguments["query"]))

        if "extra_args" in arguments:
            cmd.extend(shlex.split(arguments["extra_args"]))

        return cmd

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))
        except Exception as e:
            logger.exception("Tool %s failed", self.name)
            return error_response(ToolError(error="Execution failed", details=str(e)))

        timeout = arguments.get("timeout", self.default_timeout)
        cmd = self.build_command(arguments)

        result = await engine.execute(cmd, tool=self.name, timeout=timeout)
        return success_response(result)
