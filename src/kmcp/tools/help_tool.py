"""kmcp_help — discovery tool so agents can find and learn every other tool.

Solves the two most common first-try failures:

1. Agents don't know which tools exist → call with a ``query`` for a
   fuzzy catalog search ("vault", "scan", "fuzz", "python").
2. Agents don't know how to call a tool correctly → call with ``tool``
   for the full schema, an example arguments dict, and aliases.
"""

from __future__ import annotations

import difflib
from typing import Any

from kmcp.tools.base import BaseTool


class KmcpHelpTool(BaseTool):
    """Self-describing catalog: find tools, see schemas, get examples."""

    _skip_central_persist = True
    _skip_binary_check = True

    @property
    def name(self) -> str:
        return "kmcp_help"

    @property
    def description(self) -> str:
        return (
            "Discover available tools and how to call them correctly. "
            "Pass 'query' to fuzzy-search the catalog (e.g. 'vault', "
            "'scan', 'fuzz', 'python', 'credentials') or 'tool' to get "
            "one tool's full schema, an example arguments dict, and its "
            "alternate names. Call with no arguments to list every tool. "
            "Use this BEFORE guessing a tool name or arguments."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "query": {
                    "type": "string",
                    "description": "Fuzzy search over tool names, aliases, "
                    "and descriptions, e.g. 'vault', 'fuzz', 'python'.",
                },
                "tool": {
                    "type": "string",
                    "description": "Exact (or close) tool name to inspect "
                    "in depth — returns schema + example + aliases.",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max results for query mode (default 10)",
                    "default": 10,
                },
            },
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        pass

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["kmcp_help"]

    # ── implementation ───────────────────────────────────────────────

    def _one_liner(self, tool: BaseTool, registry: Any) -> dict[str, Any]:
        return {
            "name": tool.name,
            "description": tool.description.split(". ")[0].rstrip(".") + ".",
            "aliases": registry.aliases_for(tool.name),
        }

    def _tool_detail(self, tool: BaseTool, registry: Any) -> dict[str, Any]:
        schema = tool.input_schema()
        properties = schema.get("properties", {})
        return {
            "name": tool.name,
            "description": tool.description,
            "aliases": registry.aliases_for(tool.name),
            "required": schema.get("required", []),
            "properties": {
                pname: {
                    "type": prop.get("type", "string"),
                    "description": prop.get("description", ""),
                    **({"default": prop["default"]} if "default" in prop else {}),
                    **({"enum": prop["enum"]} if "enum" in prop else {}),
                }
                for pname, prop in properties.items()
            },
            "example_arguments": self._example_arguments(schema),
            "default_timeout": tool.default_timeout,
        }

    def _catalog(self) -> list[BaseTool]:
        from kmcp.registry import registry

        return registry.list_all()

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from kmcp.registry import registry
        from kmcp.tools.vault_tool import _make_result

        tool_name = str(arguments.get("tool", "") or "").strip()
        query = str(arguments.get("query", "") or "").strip().lower()
        limit = arguments.get("limit", 10)
        try:
            limit = max(1, min(50, int(limit)))
        except (TypeError, ValueError):
            limit = 10

        tools = self._catalog()

        # Mode A — inspect one tool in depth
        if tool_name:
            target = registry.get(tool_name)
            if target is None:
                suggestion = difflib.get_close_matches(
                    tool_name, registry.tool_names(), n=3, cutoff=0.5
                )
                return _make_result(
                    self.name,
                    {
                        "found": False,
                        "tool": tool_name,
                        "did_you_mean": suggestion,
                        "hint": "Re-call kmcp_help with 'tool': <one of "
                        "did_you_mean>, or use 'query' to search.",
                    },
                )
            return _make_result(
                self.name, {"found": True, "tool": self._tool_detail(target, registry)}
            )

        # Mode B — fuzzy query over names, aliases, and descriptions
        if query:
            scored: list[tuple[float, BaseTool]] = []
            for t in tools:
                name_low = t.name.lower()
                hay = " ".join(
                    [name_low, *registry.aliases_for(t.name), t.description.lower()]
                )
                name_score = difflib.SequenceMatcher(None, query, name_low).ratio()
                if query in hay:
                    scored.append((1.0 + name_score, t))
                elif name_score > 0.4:
                    scored.append((name_score, t))
            scored.sort(key=lambda pair: pair[0], reverse=True)
            matches = [self._one_liner(t, registry) for _, t in scored[:limit]]
            return _make_result(
                self.name,
                {
                    "query": query,
                    "total_tools": len(tools),
                    "matches": matches,
                    "hint": "Re-call with {'tool': '<name>'} for full "
                    "schema + example arguments.",
                },
            )

        # Mode C — full catalog, compact
        return _make_result(
            self.name,
            {
                "total_tools": len(tools),
                "tools": [self._one_liner(t, registry) for t in tools],
                "hint": "Re-call with {'query': '<term>'} to search or "
                "{'tool': '<name>'} for full schema + example arguments.",
            },
        )
