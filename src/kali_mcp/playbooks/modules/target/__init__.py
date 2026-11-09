"""``target.*`` internal modules for Playbook Studio.

Pure-Python operations: target format validation and scope checking.
No external binaries are invoked.
"""

from __future__ import annotations

import ipaddress
import re
from typing import Any

from kali_mcp.workflow import modules_runtime as _mr
from kali_mcp.workflow.scope_gate import ScopeViolationError, assert_target_allowed

# Injectable tool lookup (defaults to the live registry) — tests can monkeypatch.
_tool_lookup = None  # set below


def _default_tool_lookup(name: str):
    from kali_mcp.registry import registry

    return registry.get(name)


_tool_lookup = _default_tool_lookup


_DOMAIN_RE = re.compile(
    r"^(?!.{256,})(?:[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?\.)+[A-Za-z]{2,}$"
)
_IP_RE = re.compile(r"^\d{1,3}(\.\d{1,3}){3}$")


async def _validate(ctx, target: str) -> dict[str, Any]:
    """Validate a target string (IP, domain, or URL) without shelling out."""
    if not target or not isinstance(target, str):
        return {"valid": False, "target": target, "error": "target must be a non-empty string"}

    t = target.strip()
    kind = "unknown"
    if _IP_RE.match(t):
        try:
            ipaddress.ip_address(t)
            kind = "ip"
        except ValueError:
            return {"valid": False, "target": t, "error": "invalid IP address"}
    elif _DOMAIN_RE.match(t):
        kind = "domain"
    elif t.startswith(("http://", "https://")):
        kind = "url"
    else:
        return {"valid": False, "target": t, "error": "target is not an IP, domain, or URL"}

    return {"valid": True, "target": t, "kind": kind}


async def _scope_check(ctx, target: str) -> dict[str, Any]:
    """Check a target against the active authorization scope."""
    if not target or not isinstance(target, str):
        return {"allowed": False, "target": target, "error": "target must be a non-empty string"}

    try:
        assert_target_allowed(target.strip())
        return {"allowed": True, "target": target.strip()}
    except ScopeViolationError as exc:
        return {"allowed": False, "target": target.strip(), "error": str(exc)}


def register() -> None:
    """Register target.* operations with the module runtime."""
    _mr.register(
        "target.validate",
        _validate,
        input_schema={
            "type": "object",
            "required": ["target"],
            "properties": {"target": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "properties": {
                "valid": {"type": "boolean"},
                "target": {"type": "string"},
                "kind": {"type": "string"},
                "error": {"type": "string"},
            },
        },
    )
    _mr.register(
        "target.scope_check",
        _scope_check,
        input_schema={
            "type": "object",
            "required": ["target"],
            "properties": {"target": {"type": "string"}},
        },
        output_schema={
            "type": "object",
            "properties": {
                "allowed": {"type": "boolean"},
                "target": {"type": "string"},
                "error": {"type": "string"},
            },
        },
    )


__all__ = ["_scope_check", "_validate", "register"]
