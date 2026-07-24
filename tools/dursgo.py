"""DursGo web application security scanner tool."""

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


class DursgoTool(BaseTool):
    @property
    def name(self) -> str:
        return "dursgo"

    @property
    def description(self) -> str:
        return (
            "Run DursGo web application security scanner. "
            "Supports XSS, SQLi, LFI, SSRF, IDOR, CSRF, command injection, SSTI, "
            "CORS, file upload, BOLA, mass assignment, GraphQL, DOM XSS, and more."
        )

    @property
    def default_timeout(self) -> int:
        return 900

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "target": {
                    "type": "string",
                    "description": "Target URL to scan (e.g. 'http://example.com')",
                },
                "scanners": {
                    "type": "string",
                    "description": (
                        "Comma-separated scanners: xss,sqli,lfi,openredirect,ssrf,exposed,"
                        "idor,csrf,cmdinjection,ssti,securityheaders,cors,fileupload,"
                        "bola,massassignment,graphql,blindssrf,domxss,subdomain. "
                        "Use 'all' for all scanners, 'none' for crawling only."
                    ),
                    "default": "all",
                },
                "concurrency": {
                    "type": "integer",
                    "description": "Number of concurrent workers (default 0 = auto)",
                    "default": 0,
                },
                "depth": {
                    "type": "integer",
                    "description": "Maximum crawling depth (default 0 = unlimited)",
                    "default": 0,
                },
                "delay": {
                    "type": "integer",
                    "description": "Delay between requests in milliseconds",
                },
                "retries": {
                    "type": "integer",
                    "description": "Maximum retries for failed requests",
                },
                "oast": {
                    "type": "boolean",
                    "description": "Enable OAST for blind vulnerabilities (Blind SSRF, Blind CMDi)",
                },
                "render_js": {
                    "type": "boolean",
                    "description": "Enable JS rendering via headless browser (required for domxss)",
                },
                "enrich": {
                    "type": "boolean",
                    "description": "Enable vulnerability enrichment with CISA KEV data",
                },
                "enable_ai": {
                    "type": "boolean",
                    "description": "Enable AI-powered analysis for found vulnerabilities",
                },
                "output_json": {
                    "type": "string",
                    "description": "Path to save JSON report (e.g. 'report.json')",
                },
                "insecure": {
                    "type": "boolean",
                    "description": "Skip TLS certificate verification",
                },
                "extra_args": {
                    "type": "string",
                    "description": "Additional DursGo arguments not covered above",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Timeout in seconds (default 900)",
                    "default": 900,
                },
            },
            "required": ["target"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "target")
        if "timeout" in arguments:
            validate_timeout(arguments["timeout"], max_val=3600)

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        cmd = ["dursgo", "-u", arguments["target"]]

        scanners = arguments.get("scanners", "all")
        cmd.extend(["-s", scanners])

        if arguments.get("concurrency"):
            cmd.extend(["-c", str(arguments["concurrency"])])
        if arguments.get("depth"):
            cmd.extend(["-d", str(arguments["depth"])])
        if arguments.get("delay"):
            cmd.extend(["-delay", str(arguments["delay"])])
        if arguments.get("retries"):
            cmd.extend(["-r", str(arguments["retries"])])
        if arguments.get("oast"):
            cmd.append("-oast")
        if arguments.get("render_js"):
            cmd.append("-render-js")
        if arguments.get("enrich"):
            cmd.append("-enrich")
        if arguments.get("enable_ai"):
            cmd.append("--enable-ai")
        if arguments.get("output_json"):
            cmd.extend(["-output-json", arguments["output_json"]])
        if arguments.get("insecure"):
            cmd.append("-insecure")

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
