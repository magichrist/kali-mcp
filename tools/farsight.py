"""Farsight domain intelligence and reconnaissance tool."""

from __future__ import annotations

import logging

import shlex
import uuid
from pathlib import Path
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_timeout
from models import ToolError, utc_now_iso
from responses import success_response, error_response

logger = logging.getLogger("kali_mcp.tools")
from config import config


class FarsightTool(BaseTool):
    @property
    def name(self) -> str:
        return "farsight"

    @property
    def description(self) -> str:
        return (
            "Run Farsight domain intelligence scanner. "
            "Performs recon, asset discovery, threat intel, typosquat detection, "
            "and news monitoring against a target domain."
        )

    @property
    def default_timeout(self) -> int:
        return 120

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "domain": {
                    "type": "string",
                    "description": "Target domain to scan (e.g. 'example.com')",
                },
                "depth": {
                    "type": "integer",
                    "description": "Scan depth 1-3 (default 1)",
                    "default": 1,
                },
                "all_modules": {
                    "type": "boolean",
                    "description": "Enable all scan modules (default false)",
                    "default": False,
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 120)",
                    "default": 120,
                },
            },
            "required": ["domain"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "domain")
        domain = arguments["domain"]
        if not isinstance(domain, str) or not domain.strip():
            raise ValueError("Domain must be a non-empty string")
        depth = arguments.get("depth", 1)
        if not isinstance(depth, int) or depth < 1 or depth > 3:
            raise ValueError(f"Depth must be 1-3, got {depth}")
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"], max_val=600)

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd, _report_path = self._build_full(arguments)
        return cmd

    def _build_full(self, arguments: dict[str, Any]) -> tuple[list[str], Path]:
        report_path = config.artifact_dir / f"farsight_{uuid.uuid4().hex[:8]}.md"
        cmd = ["farsight", "scan", arguments["domain"]]
        cmd.extend(["-o", str(report_path)])
        depth = arguments.get("depth", 1)
        cmd.extend(["-d", str(depth)])
        if arguments.get("all_modules"):
            cmd.append("--all")
        return cmd, report_path

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))
        except Exception as e:
            logger.exception("Tool %s failed", self.name)
            return error_response(ToolError(error="Execution failed", details=str(e)))

        timeout = arguments.get("timeout", self.default_timeout)
        cmd, report_path = self._build_full(arguments)

        result = await engine.execute(cmd, tool=self.name, timeout=timeout)

        # Read the report file back with integrity check
        if report_path.exists():
            try:
                file_size = report_path.stat().st_size
                if file_size == 0:
                    result.stderr = "Report file is empty"
                    result.success = False
                else:
                    report_content = report_path.read_text(encoding="utf-8")
                    if not report_content.strip():
                        result.stderr = "Report file contains no content"
                        result.success = False
                    else:
                        result.stdout = f"=== Report: {report_path.name} ({file_size} bytes) ===\n\n{report_content}"
            except (OSError, UnicodeDecodeError) as e:
                result.stderr = f"Failed to read report: {e}"
                result.success = False
        else:
            if result.success:
                result.stderr = "Report file not created by farsight"
                result.success = False

        return success_response(result)
