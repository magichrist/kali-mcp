"""BaseTool abstract class — every native tool inherits this."""

from __future__ import annotations

import abc
from typing import Any


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
