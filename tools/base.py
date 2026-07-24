"""BaseTool abstract class — every native tool inherits this."""

from __future__ import annotations

import abc
import logging
import json
from typing import Any

from models import ToolError
from responses import error_response

logger = logging.getLogger("kali_mcp.tools")


class BaseTool(abc.ABC):
    """All native tools implement this interface."""

    @property
    @abc.abstractmethod
    def name(self) -> str:
        ...

    @property
    @abc.abstractmethod
    def description(self) -> str:
        ...

    @property
    def default_timeout(self) -> int:
        return 300

    @abc.abstractmethod
    def input_schema(self) -> dict[str, Any]:
        """Return JSON Schema for tool input parameters."""
        ...

    @abc.abstractmethod
    def validate(self, arguments: dict[str, Any]) -> None:
        """Raise ValueError if arguments are invalid."""
        ...

    @abc.abstractmethod
    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        """Build the command argument list (no shell)."""
        ...

    @abc.abstractmethod
    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Execute the tool and return MCP-formatted result."""
        ...

    async def safe_execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        """Safety net wrapper — catches ALL exceptions from execute().

        No tool should ever propagate an unhandled exception.
        This is the last line of defense.
        """
        try:
            return await self.execute(arguments)
        except Exception as e:
            logger.exception("CRITICAL: unhandled exception in tool %s", self.name)
            return error_response(ToolError(
                error=f"Internal error in {self.name}",
                details=f"{type(e).__name__}: {e}",
            ))
