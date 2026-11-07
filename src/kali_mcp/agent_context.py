"""Per-request agent-profile context (Playbook Studio Phase 6 enforcement).

Resolves the agent profile for an MCP request from the ``X-Agent-Profile``
request header, exposes the resolved profile to tool implementations through a
``ContextVar``, and provides the deny-by-default permission checks required by
``07_SECURITY_ARCHITECTURE.md`` (Layer 2) and ``06_MCP_ARCHITECTURE.md`` (§6).

Rules
-----
- No ``X-Agent-Profile`` header → no agent context → every tool behaves exactly
  as before (backward compatibility; operators, CLI, and existing agents keep
  the full default surface).
- A header naming a profile that does not exist in ``agent_profiles`` is
  ignored (treated as no context) and logged once per call — a client cannot
  gain or lose permissions by inventing profile ids.
- When a profile IS resolved, the server-side checks are authoritative:
  * every MCP tool call must have an explicit ``agent_tool_permissions`` grant
    (deny-by-default),
  * ``playbook_run`` additionally requires an ``agent_playbook_assignments``
    grant for the playbook.

This module never trusts client-supplied permissions: everything resolves
through :func:`kali_mcp.db.manager.get_db`.
"""

from __future__ import annotations

import logging
from collections.abc import Mapping
from contextvars import ContextVar, Token
from typing import Any

logger = logging.getLogger("kali_mcp.agent_context")

HEADER_PROFILE = "x-agent-profile"

_profile_var: ContextVar[str | None] = ContextVar(
    "kmcp_agent_profile", default=None
)


# ── Request-context helpers ──────────────────────────────────────────────


def _db() -> Any:
    """Lazily resolve the shared DBManager (None when DB is disabled)."""
    from kali_mcp.db import manager as db_manager

    try:
        return db_manager.get_db()
    except Exception:
        logger.exception("agent_context: DB resolution failed")
        return None


def get_current_profile() -> str | None:
    """Return the resolved profile id for the current request, or ``None``."""
    return _profile_var.get()


def set_current_profile(profile_id: str) -> Token[str | None]:
    """Bind the profile id to the current context. Returns the reset token."""
    return _profile_var.set(profile_id)


def reset_current_profile(token: Token[str | None]) -> None:
    """Restore the previous profile binding."""
    _profile_var.reset(token)


def resolve_profile_from_headers(headers: Mapping[str, Any]) -> str | None:
    """Resolve the agent profile from request headers.

    Returns the profile id only when the header is present AND the profile
    exists in ``agent_profiles``. Any other value (missing header, unknown
    profile, unreachable DB) yields ``None``.
    """
    if headers is None:
        return None
    try:
        profile_id = headers.get(HEADER_PROFILE)
    except AttributeError:
        return None
    if not profile_id:
        return None
    profile_id = str(profile_id).strip()
    if not profile_id:
        return None

    db = _db()
    if db is None:
        logger.debug("agent_context: DB unavailable; profile %r ignored", profile_id)
        return None
    row = db.get_agent_profile(profile_id)
    if row is None:
        logger.debug("agent_context: unknown profile %r ignored", profile_id)
        return None
    return profile_id


def resolve_from_context(ctx: Any) -> str | None:
    """Resolve the profile from a FastMCP ``Context`` (best-effort).

    Resolution order:
    1. Token-bound profile (``config.agent_profile_id`` / ``MCP_AGENT_PROFILE_ID``)
       — when configured, the profile applies to every request and cannot be
       overridden by the client.
    2. ``X-Agent-Profile`` request header (multi-profile deployments).

    Safe for stdio transports where there is no HTTP request at all: returns
    ``None`` in that case (no agent context — default behavior).
    """
    try:
        from kali_mcp.config import config

        bound = getattr(config, "agent_profile_id", "")
    except Exception:  # noqa: BLE001
        bound = ""
    if bound:
        # Validate the bound profile exists in the DB (fail-closed: unknown
        # bound profile disables context rather than inventing permissions).
        db = _db()
        if db is not None and db.get_agent_profile(bound) is not None:
            return bound
        logger.warning(
            "agent_context: configured MCP_AGENT_PROFILE_ID %r not found in DB",
            bound,
        )
        # Fall through to header resolution (still restricts nothing unless
        # a valid profile resolves; safer than honoring an invalid binding).
    request_context = getattr(ctx, "request_context", None)
    request = getattr(request_context, "request", None)
    headers = getattr(request, "headers", None)
    if headers is None:
        return None
    return resolve_profile_from_headers(headers)


# ── Permission checks (deny-by-default) ──────────────────────────────────


def can_call_tool(profile_id: str, tool_id: str) -> bool:
    """Return True only when the profile has an explicit grant for the tool."""
    if not profile_id or not tool_id:
        return False
    db = _db()
    if db is None:
        return False
    try:
        return bool(db.can_agent_call_tool(profile_id, tool_id))
    except Exception:
        logger.exception("agent_context: tool permission check failed")
        return False


def is_playbook_assigned(profile_id: str, playbook_id: str) -> bool:
    """Return True only when the playbook is explicitly assigned (granted)."""
    if not profile_id or not playbook_id:
        return False
    db = _db()
    if db is None:
        return False
    try:
        return bool(db.is_playbook_assigned(profile_id, playbook_id))
    except Exception:
        logger.exception("agent_context: playbook assignment check failed")
        return False


def assigned_playbooks(profile_id: str) -> list[dict[str, Any]]:
    """List playbook rows explicitly assigned (granted) to the profile."""
    if not profile_id:
        return []
    db = _db()
    if db is None:
        return []
    try:
        rows = db.list_playbook_assignments(profile_id)
    except Exception:  # noqa: BLE001
        rows = []
    out: list[dict[str, Any]] = []
    for row in rows:
        if not row.get("granted"):
            continue
        pb = db.get_playbook(row["playbook_id"])
        if isinstance(pb, dict):
            out.append(pb)
    return out


def forbidden_tool_payload(tool_name: str, profile_id: str) -> dict[str, Any]:
    """Payload text for a denied tool call (403-equivalent at MCP level)."""
    import json

    return json.dumps(
        {
            "success": False,
            "error": f"tool {tool_name!r} is not granted to agent profile {profile_id!r}",
            "forbidden": True,
            "profile_id": profile_id,
            "code": 403,
        },
        indent=2,
    )


def forbidden_playbook_payload(playbook_id: str, profile_id: str) -> dict[str, Any]:
    """Payload text for a denied playbook run."""
    import json

    return json.dumps(
        {
            "success": False,
            "error": (
                f"playbook {playbook_id!r} is not assigned to agent "
                f"profile {profile_id!r}"
            ),
            "forbidden": True,
            "profile_id": profile_id,
            "playbook_id": playbook_id,
            "code": 403,
        },
        indent=2,
    )


__all__ = [
    "HEADER_PROFILE",
    "agent_context",
    "assigned_playbooks",
    "can_call_tool",
    "forbidden_playbook_payload",
    "forbidden_tool_payload",
    "get_current_profile",
    "is_playbook_assigned",
    "reset_current_profile",
    "resolve_from_context",
    "resolve_profile_from_headers",
    "set_current_profile",
]


class _AgentContextFacade:
    """Importable facade: ``from kali_mcp.agent_context import agent_context``."""

    HEADER_PROFILE = HEADER_PROFILE

    assigned_playbooks = staticmethod(assigned_playbooks)
    can_call_tool = staticmethod(can_call_tool)
    forbidden_playbook_payload = staticmethod(forbidden_playbook_payload)
    forbidden_tool_payload = staticmethod(forbidden_tool_payload)
    get_current_profile = staticmethod(get_current_profile)
    is_playbook_assigned = staticmethod(is_playbook_assigned)
    reset_current_profile = staticmethod(reset_current_profile)
    resolve_from_context = staticmethod(resolve_from_context)
    resolve_profile_from_headers = staticmethod(resolve_profile_from_headers)
    set_current_profile = staticmethod(set_current_profile)


agent_context = _AgentContextFacade()
