"""``web.*`` internal modules for Playbook Studio.

Thin wrappers around existing registry tools (e.g. ``httpx``).
No shelling out directly.
"""

from __future__ import annotations

from typing import Any

from kali_mcp.workflow import modules_runtime as _mr

_tool_lookup = None  # set below


def _default_tool_lookup(name: str):
    from kali_mcp.registry import registry

    return registry.get(name)


_tool_lookup = _default_tool_lookup


async def _http_probe(
    ctx,
    url: str,
    tool: str = "httpx",
) -> dict[str, Any]:
    """Probe an HTTP(S) endpoint via a registered tool."""
    if not url or not isinstance(url, str):
        return {"error": "url must be a non-empty string", "url": url}

    tl = _tool_lookup(tool)
    if tl is None:
        return {"error": f"tool {tool!r} not registered", "url": url}

    try:
        result = await tl.safe_execute({"url": url})
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{tool} execution failed: {exc}", "url": url}

    status: int | None = None
    title: str | None = None
    if isinstance(result, dict) and not result.get("isError"):
        status = result.get("status_code", result.get("status"))
        title = result.get("title", result.get("data", {}).get("title"))

    return {
        "url": url,
        "tool": tool,
        "status_code": status,
        "title": title,
        "reachable": status is not None and 200 <= status < 400,
        "raw": result if isinstance(result, dict) else {},
    }


def register() -> None:
    """Register web.* operations with the module runtime."""
    _mr.register(
        "web.http_probe",
        _http_probe,
        input_schema={
            "type": "object",
            "required": ["url"],
            "properties": {
                "url": {"type": "string"},
                "tool": {"type": "string", "default": "httpx"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "url": {"type": "string"},
                "tool": {"type": "string"},
                "status_code": {"type": "integer"},
                "title": {"type": "string"},
                "reachable": {"type": "boolean"},
                "error": {"type": "string"},
                "raw": {"type": "object"},
            },
        },
    )


__all__ = ["_http_probe", "register"]
