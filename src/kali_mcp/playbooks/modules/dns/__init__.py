"""``dns.*`` internal modules for Playbook Studio.

Thin wrappers around existing registry tools (e.g. ``dnsx``). No shelling out
directly — execution goes through ``registry.get(name).safe_execute(...)``.
"""

from __future__ import annotations

from typing import Any

from kali_mcp.workflow import modules_runtime as _mr

_tool_lookup = None  # set below


def _default_tool_lookup(name: str):
    from kali_mcp.registry import registry

    return registry.get(name)


_tool_lookup = _default_tool_lookup


async def _resolve(ctx, target: str, tool: str = "dnsx") -> dict[str, Any]:
    """Resolve DNS records for a target via a registered tool."""
    if not target or not isinstance(target, str):
        return {"error": "target must be a non-empty string", "target": target}

    tl = _tool_lookup(tool)
    if tl is None:
        return {"error": f"tool {tool!r} not registered", "target": target, "resolved": []}

    try:
        result = await tl.safe_execute({"target": target})
    except Exception as exc:  # noqa: BLE001 — never propagate tool exceptions
        return {"error": f"{tool} execution failed: {exc}", "target": target, "resolved": []}

    # Normalize: tool results may nest data under various keys
    resolved: list[str] = []
    if isinstance(result, dict):
        if not result.get("isError"):
            resolved = result.get("resolved", result.get("data", result.get("result", [])))
            if isinstance(resolved, str):
                resolved = [resolved]
        else:
            resolved = []
    return {"target": target, "tool": tool, "resolved": resolved, "raw": result if isinstance(result, dict) else {}}


def register() -> None:
    """Register dns.* operations with the module runtime."""
    _mr.register(
        "dns.resolve",
        _resolve,
        input_schema={"type": "object", "required": ["target"], "properties": {"target": {"type": "string"}, "tool": {"type": "string", "default": "dnsx"}}},
        output_schema={"type": "object", "properties": {"target": {"type": "string"}, "tool": {"type": "string"}, "resolved": {"type": "array"}, "error": {"type": "string"}, "raw": {"type": "object"}}},
    )


__all__ = ["_resolve", "register"]