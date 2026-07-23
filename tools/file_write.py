"""File write tool — write/create files on the Kali machine."""

from __future__ import annotations

import os
from typing import Any

from tools.base import BaseTool
from validation import validate_required
from models import ExecutionResult, ToolError, utc_now_iso
from responses import success_response, error_response


class FileWriteTool(BaseTool):
    @property
    def name(self) -> str:
        return "file_write"

    @property
    def description(self) -> str:
        return (
            "Write content to a file on the Kali machine. Creates parent "
            "directories automatically. Use for saving scan results, reports, "
            "scripts, wordlists, configs, or any file output."
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
                    "description": "Absolute path where the file will be written",
                },
                "content": {
                    "type": "string",
                    "description": "Content to write to the file",
                },
                "mode": {
                    "type": "string",
                    "description": "Write mode: 'overwrite' (default) or 'append'",
                    "enum": ["overwrite", "append"],
                    "default": "overwrite",
                },
            },
            "required": ["path", "content"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "path")
        validate_required(arguments, "content")
        path = arguments["path"]
        if not isinstance(path, str) or not path.strip():
            raise ValueError("Path must be a non-empty string")
        content = arguments["content"]
        if not isinstance(content, str):
            raise ValueError("Content must be a string")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["true"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        try:
            self.validate(arguments)
        except ValueError as e:
            return error_response(ToolError(error="Validation error", details=str(e)))

        path = arguments["path"]
        content = arguments["content"]
        mode = arguments.get("mode", "overwrite")

        try:
            os.makedirs(os.path.dirname(path) or ".", exist_ok=True)

            file_mode = "w" if mode == "overwrite" else "a"
            with open(path, file_mode) as f:
                f.write(content)

            file_size = os.path.getsize(path)

            import json
            result = ExecutionResult(
                tool=self.name,
                command=f"write {len(content)} bytes to {path}",
                stdout=json.dumps({
                    "path": path,
                    "mode": mode,
                    "bytes_written": len(content.encode("utf-8")),
                    "file_size": file_size,
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
                error="Write failed",
                details=str(e),
            ))
