"""Core data models for execution results and errors."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any


@dataclass
class ExecutionResult:
    tool: str
    command: str
    stdout: str
    stderr: str
    exit_code: int
    success: bool
    timed_out: bool
    duration: float
    start_time: str
    end_time: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "tool": self.tool,
            "command": self.command,
            "stdout": self.stdout,
            "stderr": self.stderr,
            "exit_code": self.exit_code,
            "success": self.success,
            "timed_out": self.timed_out,
            "duration": self.duration,
            "start_time": self.start_time,
            "end_time": self.end_time,
        }


@dataclass
class ToolError:
    error: str
    details: str = ""

    def to_dict(self) -> dict[str, Any]:
        d: dict[str, Any] = {"success": False, "error": self.error}
        if self.details:
            d["details"] = self.details
        return d


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()
