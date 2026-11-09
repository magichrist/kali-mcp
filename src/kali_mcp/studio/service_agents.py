"""Agent Studio service layer (Phase 6).

Profile CRUD, permission + playbook assignment mutation, effective catalog
computation. Enforces deny-by-default: an agent may only call tools/playbooks
explicitly granted to its profile.
"""

from __future__ import annotations

import logging
from typing import Any

from kali_mcp.db.manager import DBManager
from kali_mcp.studio.service_tools import list_tool_definitions

logger = logging.getLogger("kali_mcp.studio.service_agents")


def create_profile(db: DBManager, profile_id: str, name: str, **kwargs: Any) -> dict[str, Any]:
    if not profile_id or not name:
        raise ValueError("profile_id and name are required")
    db.create_agent_profile(profile_id, name, **kwargs)
    return db.get_agent_profile(profile_id) or {"profile_id": profile_id, "name": name}


def get_profile(db: DBManager, profile_id: str) -> dict[str, Any] | None:
    return db.get_agent_profile(profile_id)


def list_profiles(db: DBManager) -> list[dict[str, Any]]:
    return db.list_agent_profiles()


def update_profile(db: DBManager, profile_id: str, **fields: Any) -> bool:
    return db.update_agent_profile(profile_id, **fields)


def delete_profile(db: DBManager, profile_id: str) -> bool:
    return db.delete_agent_profile(profile_id)


def grant_tool(db: DBManager, profile_id: str, tool_id: str, granted: bool = True) -> None:
    db.grant_tool_permission(profile_id, tool_id, granted)


def revoke_tool(db: DBManager, profile_id: str, tool_id: str) -> None:
    db.revoke_tool_permission(profile_id, tool_id)


def can_call_tool(db: DBManager, profile_id: str, tool_id: str) -> bool:
    return db.can_agent_call_tool(profile_id, tool_id)


def assign_playbook(db: DBManager, profile_id: str, playbook_id: str, granted: bool = True) -> None:
    db.assign_playbook_to_profile(profile_id, playbook_id, granted)


def unassign_playbook(db: DBManager, profile_id: str, playbook_id: str) -> None:
    db.unassign_playbook_from_profile(profile_id, playbook_id)


def is_playbook_assigned(db: DBManager, profile_id: str, playbook_id: str) -> bool:
    return db.is_playbook_assigned(profile_id, playbook_id)


def effective_catalog(db: DBManager, profile_id: str) -> dict[str, Any]:
    """Compute the effective tool + playbook catalog for a profile (deny-by-default)."""
    tools = []
    for row in list_tool_definitions(db, enabled=True):
        if db.can_agent_call_tool(profile_id, row["tool_id"]):
            tools.append(row["tool_id"])
    playbooks = []
    for row in db.list_playbooks():
        pid = row.get("playbook_id") or row.get("id")
        if pid and db.is_playbook_assigned(profile_id, pid):
            playbooks.append(pid)
    return {"profile_id": profile_id, "tools": tools, "playbooks": playbooks}


__all__ = [
    "assign_playbook",
    "can_call_tool",
    "create_profile",
    "delete_profile",
    "effective_catalog",
    "get_profile",
    "grant_tool",
    "is_playbook_assigned",
    "list_profiles",
    "revoke_tool",
    "unassign_playbook",
    "update_profile",
]
