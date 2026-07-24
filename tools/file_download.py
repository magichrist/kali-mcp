"""File download tool — generate download links for server-to-agent file transfers."""

from __future__ import annotations

import logging
import os
import shlex
import socket
from typing import Any

from tools.base import BaseTool
from validation import validate_required
from models import ExecutionResult, ToolError, utc_now_iso
from responses import success_response, error_response

logger = logging.getLogger("kali_mcp.tools")


def _get_download_host() -> str:
    """Resolve the externally-reachable host for download URLs."""
    from config import config

    host = config.host
    if host and host not in ("0.0.0.0", "::"):
        return host
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("10.255.255.255", 1))
        ip = s.getsockname()[0]
        s.close()
        return ip
    except Exception:
        return "localhost"


class FileDownloadTool(BaseTool):
    @property
    def name(self) -> str:
        return "file_download"

    @property
    def description(self) -> str:
        return (
            "Generate a download link for a file on the Kali server. "
            "Returns a curl command the agent can run to save the file locally."
        )

    @property
    def default_timeout(self) -> int:
        return 60

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "server_path": {
                    "type": "string",
                    "description": "Absolute path to the file on the Kali server",
                },
                "local_path": {
                    "type": "string",
                    "description": "Local path to save the file (default: basename of server_path)",
                    "default": "",
                },
            },
            "required": ["server_path"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "server_path")
        path = arguments["server_path"]
        if not isinstance(path, str) or not path.strip():
            raise ValueError("server_path must be a non-empty string")
        if not os.path.isfile(path):
            raise ValueError(f"File not found: {path}")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return []

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))

        server_path = os.path.realpath(arguments["server_path"])
        local_path = arguments.get("local_path") or os.path.basename(server_path)
        file_size = os.path.getsize(server_path)

        from config import config

        host = _get_download_host()
        port = config.port
        download_url = f"http://{host}:{port}/download?path={shlex.quote(server_path)}"

        curl_cmd = f"curl -sS -o {shlex.quote(local_path)} {shlex.quote(download_url)}"

        if config.api_token:
            curl_cmd += f' -H "Authorization: Bearer {config.api_token}"'

        stdout = (
            f"Download ready: {server_path} ({file_size:,} bytes)\n\n"
            f"Run this command to save to {local_path}:\n{curl_cmd}"
        )

        result = ExecutionResult(
            tool=self.name,
            command=f"file_download {server_path}",
            stdout=stdout,
            stderr="",
            exit_code=0,
            success=True,
            timed_out=False,
            duration=0.0,
            start_time=utc_now_iso(),
            end_time=utc_now_iso(),
        )

        return success_response(result)
