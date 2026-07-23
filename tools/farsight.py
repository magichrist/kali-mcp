"""Farsight domain intelligence and reconnaissance tool."""

from __future__ import annotations

import shlex
import uuid
from pathlib import Path
from typing import Any

from tools.base import BaseTool
from execution import engine
from validation import validate_required, validate_timeout
from models import ToolError, utc_now_iso
from responses import success_response, error_response
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
                    "description": "Scan depth level 1-3 (default 1)",
                    "default": 1,
                },
                "modules": {
                    "type": "string",
                    "description": "Comma-separated modules: org,recon,threat,typosquat,news",
                },
                "all_modules": {
                    "type": "boolean",
                    "description": "Run all available modules",
                },
                "threat_intel": {
                    "type": "boolean",
                    "description": "Include threat intelligence",
                },
                "typosquat": {
                    "type": "boolean",
                    "description": "Include typosquatting detection",
                },
                "news": {
                    "type": "boolean",
                    "description": "Include news monitoring",
                },
                "verbose": {
                    "type": "boolean",
                    "description": "Verbose output",
                },
                "force": {
                    "type": "boolean",
                    "description": "Force overwrite output file if exists",
                },
                "concurrency": {
                    "type": "integer",
                    "description": "Maximum concurrent requests (default 10)",
                    "default": 10,
                },
                "extra_args": {
                    "type": "string",
                    "description": "Additional Farsight arguments",
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
        depth = arguments.get("depth", 1)
        if depth < 1 or depth > 3:
            raise ValueError(f"Depth must be 1-3, got {depth}")
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"], max_val=600)

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd, _report_path = self._build_full(arguments)
        return cmd

    def _build_full(self, arguments: dict[str, Any]) -> tuple[list[str], Path]:
        report_path = config.artifact_dir / f"farsight_{uuid.uuid4().hex[:8]}.md"

        cmd = ["python3", "-m", "farsight", "scan", arguments["domain"]]
        cmd.extend(["-o", str(report_path)])

        depth = arguments.get("depth", 1)
        cmd.extend(["-d", str(depth)])

        if arguments.get("all_modules"):
            cmd.append("--all")
        if arguments.get("modules"):
            cmd.extend(["-m", arguments["modules"]])
        if arguments.get("threat_intel"):
            cmd.append("--threat-intel")
        if arguments.get("typosquat"):
            cmd.append("--typosquat")
        if arguments.get("news"):
            cmd.append("--news")
        if arguments.get("verbose"):
            cmd.append("--verbose")
        if arguments.get("force"):
            cmd.append("--force")
        if arguments.get("concurrency"):
            cmd.extend(["-c", str(arguments["concurrency"])])

        if "extra_args" in arguments:
            cmd.extend(shlex.split(arguments["extra_args"]))

        return cmd, report_path

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))

        timeout = arguments.get("timeout", self.default_timeout)
        cmd, report_path = self._build_full(arguments)

        result = await engine.execute(cmd, tool=self.name, timeout=timeout)

        # Read the report file back and return it in stdout
        if report_path.exists():
            try:
                report_content = report_path.read_text(encoding="utf-8")
                result.stdout = f"=== Report: {report_path.name} ===\n\n{report_content}"
            except Exception:
                pass

        return success_response(result)
