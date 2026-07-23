"""File read tool — read files from the Kali machine."""

from __future__ import annotations

import os
import json
from typing import Any

from tools.base import BaseTool
from validation import validate_required
from models import ExecutionResult, ToolError, utc_now_iso
from responses import success_response, error_response

# Allowed directories for file reads (configurable via env)
import os as _os
_ALLOWED_DIRS_ENV = _os.getenv("MCP_ALLOWED_READ_DIRS", "/home/kali,/tmp,/var/tmp,/root,/etc,/usr,/opt")
ALLOWED_READ_DIRS = [d.strip() for d in _ALLOWED_DIRS_ENV.split(",") if d.strip()]


class FileReadTool(BaseTool):
    @property
    def name(self) -> str:
        return "file_read"

    @property
    def description(self) -> str:
        return (
            "Read a file from the Kali machine. Returns the file content, "
            "size, and metadata. Use for reading scan results, configs, "
            "wordlists, reports, logs, or any file on the system."
        )

    @property
    def default_timeout(self) -> int:
        return 30

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "path": {
                    "type": "string",
                    "description": "Absolute path to the file to read",
                },
                "max_bytes": {
                    "type": "integer",
                    "description": "Maximum bytes to read (default 1MB). Large files are truncated.",
                    "default": 1048576,
                },
                "offset": {
                    "type": "integer",
                    "description": "Byte offset to start reading from (default 0). Useful for large files.",
                    "default": 0,
                },
            },
            "required": ["path"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "path")
        path = arguments["path"]
        if not isinstance(path, str) or not path.strip():
            raise ValueError("Path must be a non-empty string")
        # Path containment check
        resolved = os.path.realpath(path)
        if not any(resolved.startswith(d + "/") or resolved == d for d in ALLOWED_READ_DIRS):
            raise ValueError(
                f"Path not in allowed directories: {resolved}. "
                f"Allowed: {', '.join(ALLOWED_READ_DIRS)}"
            )

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["cat", arguments["path"]]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))

        path = arguments["path"]
        max_bytes = arguments.get("max_bytes", 1048576)
        offset = arguments.get("offset", 0)

        if not os.path.isfile(path):
            return error_response(ToolError(
                error="File not found",
                details=f"No such file: {path}",
            ))

        try:
            file_size = os.path.getsize(path)

            with open(path, "r", errors="replace") as f:
                if offset > 0:
                    f.seek(offset)
                content = f.read(max_bytes)

            truncated = (offset + len(content.encode("utf-8"))) < file_size

            result = {
                "tool": self.name,
                "path": path,
                "file_size": file_size,
                "offset": offset,
                "bytes_read": len(content.encode("utf-8")),
                "truncated": truncated,
                "content": content,
            }

            result = ExecutionResult(
                tool=self.name,
                command=f"cat {path}",
                stdout=json.dumps({
                    "path": path,
                    "file_size": file_size,
                    "offset": offset,
                    "bytes_read": len(content.encode("utf-8")),
                    "truncated": truncated,
                    "content": content,
                }),
                stderr="",
                exit_code=0,
                success=True,
                timed_out=False,
                duration=0.0,
                start_time=utc_now_iso(),
                end_time=utc_now_iso(),
            )

            return success_response(result)
        except Exception as e:
            return error_response(ToolError(
                error="Read failed",
                details=str(e),
            ))
