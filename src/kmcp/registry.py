"""Tool registry — maps tool names to BaseTool instances with visibility modes.

Visibility modes (per docs/visual/01_TARGET_ARCHITECTURE.md §Tool Registry):

- ``agent_callable`` — agents can call the tool directly via MCP (default for
  existing native tools, preserving current behavior per TD-6).
- ``playbook_selectable`` — agents can only use the tool inside an assigned
  playbook, not via direct MCP calls.
- ``internal`` — usable only by the engine internally (modules, playbook steps),
  never exposed to agents directly.
- ``hidden`` — not listed in any catalog; reserved for system use.

Per TD-6, all existing native tools default to ``agent_callable`` so nothing
changes for current agents. Studio users can demote specific tools to
``playbook_selectable`` or ``internal``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any

from kmcp.tools.base import BaseTool

logger = logging.getLogger("kmcp.registry")

#: Valid visibility modes.
VISIBILITY_MODES = frozenset({"agent_callable", "playbook_selectable", "internal", "hidden"})

#: Default visibility for newly registered tools (TD-6: backward compatible).
DEFAULT_VISIBILITY = "agent_callable"


@dataclass
class ToolDefinition:
    """A registered tool with visibility metadata."""

    tool: BaseTool
    visibility: str = DEFAULT_VISIBILITY
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def name(self) -> str:
        return self.tool.name

    @property
    def description(self) -> str:
        return self.tool.description


class ToolRegistry:
    def __init__(self) -> None:
        self._tools: dict[str, ToolDefinition] = {}

    def register(
        self,
        tool: BaseTool,
        *,
        visibility: str = DEFAULT_VISIBILITY,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        """Register a tool instance with an optional visibility mode.

        Overwrites if name already exists. Backward compatible: calling
        ``register(tool)`` with no visibility defaults to ``agent_callable``.
        """
        if visibility not in VISIBILITY_MODES:
            raise ValueError(
                f"invalid visibility {visibility!r}; expected one of {sorted(VISIBILITY_MODES)}"
            )
        if tool.name in self._tools:
            logger.warning("Overwriting tool: %s", tool.name)
        self._tools[tool.name] = ToolDefinition(
            tool=tool,
            visibility=visibility,
            metadata=metadata or {},
        )
        logger.info("Registered tool: %s (visibility=%s)", tool.name, visibility)

    def get(self, name: str) -> BaseTool | None:
        """Return the BaseTool for ``name``, or None if not registered."""
        defn = self._tools.get(name)
        return defn.tool if defn is not None else None

    def get_definition(self, name: str) -> ToolDefinition | None:
        """Return the full :class:`ToolDefinition` for ``name``, or None."""
        return self._tools.get(name)

    def list_all(self) -> list[BaseTool]:
        """Return all registered BaseTool instances (ignores visibility)."""
        return [defn.tool for defn in self._tools.values()]

    def tool_names(self) -> list[str]:
        """Return all registered tool names (ignores visibility)."""
        return list(self._tools.keys())

    def visible_tools(self, visibility: str = DEFAULT_VISIBILITY) -> list[BaseTool]:
        """Return tools visible at the given visibility mode or more permissive.

        Visibility precedence (most to least permissive):
            agent_callable > playbook_selectable > internal > hidden

        A tool is returned if its visibility is *at least as permissive* as
        the requested mode.
        """
        if visibility not in VISIBILITY_MODES:
            raise ValueError(
                f"invalid visibility {visibility!r}; expected one of {sorted(VISIBILITY_MODES)}"
            )
        order = ["hidden", "internal", "playbook_selectable", "agent_callable"]
        min_rank = order.index(visibility)
        return [
            defn.tool for defn in self._tools.values() if order.index(defn.visibility) >= min_rank
        ]

    def visible_tool_names(self, visibility: str = DEFAULT_VISIBILITY) -> list[str]:
        """Return tool names visible at the given visibility mode."""
        return [t.name for t in self.visible_tools(visibility)]

    def set_visibility(self, name: str, visibility: str) -> bool:
        """Change the visibility mode of a registered tool.

        Returns True if the tool was found and updated, False otherwise.
        """
        if visibility not in VISIBILITY_MODES:
            raise ValueError(
                f"invalid visibility {visibility!r}; expected one of {sorted(VISIBILITY_MODES)}"
            )
        defn = self._tools.get(name)
        if defn is None:
            return False
        defn.visibility = visibility
        logger.info("Tool %s visibility set to %s", name, visibility)
        return True

    def set_metadata(self, name: str, metadata: dict[str, Any]) -> bool:
        """Update metadata for a registered tool. Returns True if found."""
        defn = self._tools.get(name)
        if defn is None:
            return False
        defn.metadata.update(metadata)
        return True

    def visibility_of(self, name: str) -> str | None:
        """Return the visibility mode of a tool, or None if not registered."""
        defn = self._tools.get(name)
        return defn.visibility if defn is not None else None


registry = ToolRegistry()

__all__ = [
    "DEFAULT_VISIBILITY",
    "VISIBILITY_MODES",
    "ToolDefinition",
    "ToolRegistry",
    "registry",
]
