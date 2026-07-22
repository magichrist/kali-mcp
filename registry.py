"""Tool registry — maps tool names to BaseTool instances."""

from __future__ import annotations

import logging
from typing import Any

from tools.base import BaseTool

logger = logging.getLogger("kali_mcp.registry")


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool instance. Overwrites if name already exists."""
        if tool.name in self._tools:
            logger.warning("Overwriting tool: %s", tool.name)
        self._tools[tool.name] = tool
        logger.info("Registered tool: %s", tool.name)

    def get(self, name: str) -> BaseTool | None:
        return self._tools.get(name)

    def list_all(self) -> list[BaseTool]:
        return list(self._tools.values())

    def tool_names(self) -> list[str]:
        return list(self._tools.keys())


registry = ToolRegistry()
