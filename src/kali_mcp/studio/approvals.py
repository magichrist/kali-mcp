"""Approval gates for Playbook Studio (Phase 4).

Security-sensitive Studio operations require an explicit approval before they
take effect:

- Publishing a playbook version
- Importing a playbook package
- Changing tool visibility to ``agent_callable``
- Assigning playbooks to agent profiles

Approvals are stored in ``pending_approvals`` and must be confirmed by an
operator before the gated action proceeds. This provides the "operator
approval gates for aggressive operations" required by the security architecture
(07_SECURITY_ARCHITECTURE.md §4.2).
"""

from __future__ import annotations

import logging
from typing import Any

from kali_mcp.db.manager import DBManager

logger = logging.getLogger("kali_mcp.studio.approvals")

# Approval gate names
GATE_PUBLISH = "publish"
GATE_IMPORT = "import"
GATE_VISIBILITY_AGENT_CALLABLE = "visibility:agent_callable"
GATE_PLAYBOOK_ASSIGN = "playbook:assign"


def request_approval(
    db: DBManager,
    *,
    gate: str,
    resource_id: str,
    requested_by: str | None = None,
) -> int:
    """Request an approval for a gated operation.

    Creates or refreshes a pending approval row. Returns the approval row id.
    """
    aid = db.upsert_approval(
        gate=gate,
        resource_id=resource_id,
        status="pending",
        requested_by=requested_by,
    )
    logger.info("APPROVAL requested gate=%s resource=%s by=%s", gate, resource_id, requested_by)
    return aid


def get_pending_approval(
    db: DBManager,
    gate: str,
    resource_id: str,
) -> dict[str, Any] | None:
    """Return the newest pending approval for a gate/resource, or None."""
    return db.get_pending_approval(gate=gate, resource_id=resource_id)


def is_approved(
    db: DBManager,
    gate: str,
    resource_id: str,
) -> bool:
    """Return True when a pending approval exists for the gate/resource."""
    return db.get_pending_approval(gate=gate, resource_id=resource_id) is not None


def approve(
    db: DBManager,
    *,
    approval_id: int,
    approved_by: str,
    status: str = "approved",
) -> bool:
    """Approve or reject a pending approval.

    Returns True on success.
    """
    ok = db.approve(approval_id=approval_id, approved_by=approved_by, status=status)
    if ok:
        logger.info("APPROVAL %s id=%s by=%s", status, approval_id, approved_by)
    return ok


def require_approval_for(
    gate: str,
) -> str:
    """Return a descriptive message for a gated operation.

    Used by API handlers to produce a 403 response when approval is required
    but not yet granted.
    """
    messages = {
        GATE_PUBLISH: "Publishing this playbook version requires operator approval.",
        GATE_IMPORT: "Importing this playbook package requires operator approval.",
        GATE_VISIBILITY_AGENT_CALLABLE: (
            "Changing tool visibility to agent_callable requires operator approval."
        ),
        GATE_PLAYBOOK_ASSIGN: "Assigning this playbook to an agent profile requires operator approval.",
    }
    return messages.get(gate, f"Approval required for gate: {gate}")


__all__ = [
    "GATE_PUBLISH",
    "GATE_IMPORT",
    "GATE_VISIBILITY_AGENT_CALLABLE",
    "GATE_PLAYBOOK_ASSIGN",
    "request_approval",
    "get_pending_approval",
    "is_approved",
    "approve",
    "require_approval_for",
]
