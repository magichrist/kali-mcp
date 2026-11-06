"""Audit logging for Playbook Studio (Phase 4).

Records security-relevant Studio events to the ``studio_audit`` DB table:
publish, rollback, import, export, visibility changes, tool registration,
and agent permission changes. Append-only — records are never modified or
deleted.

Delegates record creation to :meth:`kali_mcp.db.manager.DBManager.record_audit`
and provides listing/filtering that DBManager does not yet expose.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from kali_mcp.db.manager import DBManager

logger = logging.getLogger("kali_mcp.studio.audit")


def record_audit(
    db: DBManager,
    *,
    event: str,
    entity_type: str | None = None,
    entity_id: str | None = None,
    actor: str | None = None,
    details: dict[str, Any] | None = None,
) -> int:
    """Append an audit record to ``studio_audit``.

    Delegates to :meth:`DBManager.record_audit`. Returns the new audit row id.
    """
    return db.record_audit(
        event=event,
        entity_type=entity_type,
        entity_id=entity_id,
        actor=actor,
        data=details,
    )


def list_audit(
    db: DBManager,
    *,
    event: str | None = None,
    entity_type: str | None = None,
    actor: str | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[dict[str, Any]]:
    """List audit records with optional filters, newest first."""
    cur = db.conn.cursor()
    clauses: list[str] = []
    params: list[Any] = []
    if event:
        clauses.append("event = ?")
        params.append(event)
    if entity_type:
        clauses.append("entity_type = ?")
        params.append(entity_type)
    if actor:
        clauses.append("actor = ?")
        params.append(actor)
    where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
    rows = cur.execute(
        f"SELECT * FROM studio_audit {where} "
        f"ORDER BY id DESC LIMIT ? OFFSET ?",
        (*params, limit, offset),
    ).fetchall()
    results: list[dict[str, Any]] = []
    for r in rows:
        d = dict(r)
        try:
            d["details"] = json.loads(d.get("data") or "{}")
        except Exception:  # noqa: BLE001
            d["details"] = {}
        results.append(d)
    return results


__all__ = ["record_audit", "list_audit"]
