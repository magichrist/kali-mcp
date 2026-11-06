"""``tls.*`` internal modules for Playbook Studio.

Thin wrappers around existing registry tools (e.g. ``nmap`` with TLS scripts).
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


async def _certificate(
    ctx,
    target: str,
    port: int = 443,
    tool: str = "nmap",
) -> dict[str, Any]:
    """Retrieve TLS certificate information for a target via a registered tool."""
    if not target or not isinstance(target, str):
        return {"error": "target must be a non-empty string", "target": target}

    tl = _tool_lookup(tool)
    if tl is None:
        return {"error": f"tool {tool!r} not registered", "target": target, "port": port}

    try:
        result = await tl.safe_execute({"target": target, "ports": port, "script": "ssl-cert"})
    except Exception as exc:  # noqa: BLE001
        return {"error": f"{tool} execution failed: {exc}", "target": target, "port": port}

    cert_info: dict[str, Any] = {}
    if isinstance(result, dict) and not result.get("isError"):
        cert_info = result.get("certificate", result.get("data", {}))

    return {
        "target": target,
        "port": port,
        "tool": tool,
        "certificate": cert_info,
        "raw": result if isinstance(result, dict) else {},
    }


def register() -> None:
    """Register tls.* operations with the module runtime."""
    _mr.register(
        "tls.certificate",
        _certificate,
        input_schema={
            "type": "object",
            "required": ["target"],
            "properties": {
                "target": {"type": "string"},
                "port": {"type": "integer", "default": 443},
                "tool": {"type": "string", "default": "nmap"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "target": {"type": "string"},
                "port": {"type": "integer"},
                "tool": {"type": "string"},
                "certificate": {"type": "object"},
                "error": {"type": "string"},
                "raw": {"type": "object"},
            },
        },
    )


__all__ = ["_certificate", "register"]