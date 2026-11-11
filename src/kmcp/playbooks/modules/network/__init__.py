"""``network.*`` internal modules for Playbook Studio.

Thin wrappers around existing registry tools (e.g. ``naabu``, ``nmap``).
No shelling out directly.
"""

from __future__ import annotations

from typing import Any

from kmcp.workflow import modules_runtime as _mr

_tool_lookup = None  # set below


def _default_tool_lookup(name: str):
    from kmcp.registry import registry

    return registry.get(name)


_tool_lookup = _default_tool_lookup


async def _port_discovery(
    ctx,
    target: str,
    ports: str | None = None,
    tool: str = "naabu",
) -> dict[str, Any]:
    """Discover open ports on a target via a registered tool."""
    if not target or not isinstance(target, str):
        return {"error": "target must be a non-empty string", "target": target}

    tl = _tool_lookup(tool)
    if tl is None:
        return {"error": f"tool {tool!r} not registered", "target": target, "open_ports": []}

    args: dict[str, Any] = {"target": target}
    if ports:
        args["ports"] = ports

    try:
        result = await tl.safe_execute(args)
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{tool} execution failed: {exc}", "target": target, "open_ports": []}

    open_ports: list[int] = []
    if isinstance(result, dict) and not result.get("isError"):
        raw = result.get("open_ports", result.get("data", result.get("result", [])))
        if isinstance(raw, list):
            open_ports = [int(p) for p in raw if isinstance(p, (int, str)) and str(p).isdigit()]
        elif isinstance(raw, str):
            open_ports = [int(p) for p in raw.split(",") if p.strip().isdigit()]

    return {
        "target": target,
        "tool": tool,
        "open_ports": open_ports,
        "raw": result if isinstance(result, dict) else {},
    }


def register() -> None:
    """Register network.* operations with the module runtime."""
    _mr.register(
        "network.port_discovery",
        _port_discovery,
        input_schema={
            "type": "object",
            "required": ["target"],
            "properties": {
                "target": {"type": "string"},
                "ports": {"type": "string"},
                "tool": {"type": "string", "default": "naabu"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "tool": {"type": "string"},
                "open_ports": {"type": "array"},
                "error": {"type": "string"},
                "raw": {"type": "object"},
            },
        },
    )


__all__ = ["_port_discovery", "register"]
