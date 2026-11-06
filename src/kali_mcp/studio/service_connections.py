"""External MCP connection storage ops (Phase 3 Task E).

Persistence layer over the ``mcp_connections`` table. Complements
:mod:`kali_mcp.studio.service_mcp_connections`, which handles probe/discovery
logic against the actual external server.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from kali_mcp.db.manager import DBManager

logger = logging.getLogger("kali_mcp.studio.service_connections")


def list_connections(db: DBManager) -> list[dict[str, Any]]:
    """List all registered external MCP connections, newest first."""
    cur = db.conn.cursor()
    rows = cur.execute(
        "SELECT * FROM mcp_connections ORDER BY updated_at DESC"
    ).fetchall()
    out: list[dict[str, Any]] = []
    for r in rows:
        row = dict(r)
        # args/auth_config are stored as JSON blobs; surface parsed values
        for field in ("args", "auth_config"):
            raw = row.get(field)
            if raw:
                try:
                    row[field] = json.loads(raw)
                except (TypeError, ValueError):
                    pass
        tool_count = cur.execute(
            "SELECT COUNT(*) FROM tool_definitions WHERE provider = ?",
            (row["connection_id"],),
        ).fetchone()[0]
        row["imported_tool_count"] = tool_count
        out.append(row)
    return out


def upsert_connection(
    db: DBManager,
    connection_id: str,
    name: str,
    transport: str,
    *,
    description: str | None = None,
    endpoint_url: str | None = None,
    command: str | list[str] | None = None,
    args: list[str] | None = None,
    auth_type: str | None = None,
    auth_config: dict[str, Any] | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    """Create or update an external MCP connection row. Returns the row.

    ``command`` accepts either a string ("npx --arg x") or a list
    (["npx", "--arg", "x"]); lists are joined with spaces for storage
    (``command TEXT`` column).
    """
    if isinstance(command, list):
        command = " ".join(str(c) for c in command)
    now = db._now_utc()
    cur = db.conn.cursor()
    cur.execute(
        "SELECT id FROM mcp_connections WHERE connection_id = ?", (connection_id,)
    )
    exists = cur.fetchone() is not None
    if exists:
        cur.execute(
            """
            UPDATE mcp_connections
            SET name=?, description=?, transport=?, endpoint_url=?, command=?,
                args=?, auth_type=?, auth_config=?, enabled=?, updated_at=?
            WHERE connection_id=?
            """,
            (
                name, description, transport, endpoint_url, command,
                json.dumps(args) if args else None,
                auth_type,
                json.dumps(auth_config) if auth_config else None,
                int(bool(enabled)), now, connection_id,
            ),
        )
    else:
        cur.execute(
            """
            INSERT INTO mcp_connections
            (connection_id, name, description, transport, endpoint_url, command,
             args, auth_type, auth_config, enabled, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
            """,
            (
                connection_id, name, description, transport, endpoint_url, command,
                json.dumps(args) if args else None,
                auth_type,
                json.dumps(auth_config) if auth_config else None,
                int(bool(enabled)), now, now,
            ),
        )
    db.conn.commit()
    cur.execute(
        "SELECT * FROM mcp_connections WHERE connection_id = ?", (connection_id,)
    )
    return dict(cur.fetchone() or {})


def delete_connection(db: DBManager, connection_id: str) -> bool:
    """Delete a connection row. Returns True when a row was removed."""
    cur = db.conn.cursor()
    cur.execute(
        "DELETE FROM mcp_connections WHERE connection_id = ?", (connection_id,)
    )
    deleted = cur.rowcount > 0
    db.conn.commit()
    return deleted


def set_health(db: DBManager, connection_id: str, ok: bool) -> None:
    """Record the last connectivity probe result."""
    cur = db.conn.cursor()
    status = "healthy" if ok else "unreachable"
    cur.execute(
        "UPDATE mcp_connections SET health_status=?, last_connected_at=?, updated_at=? "
        "WHERE connection_id=?",
        (
            status,
            db._now_utc() if ok else None,
            db._now_utc(),
            connection_id,
        ),
    )
    db.conn.commit()


__all__ = [
    "list_connections",
    "upsert_connection",
    "delete_connection",
    "set_health",
]
