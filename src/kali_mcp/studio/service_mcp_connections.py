"""External MCP connection management (Phase 3 Task E).

CRUD over external MCP server connections plus discovery/import helpers that
delegate to :mod:`kali_mcp.studio.mcp_client`.
"""

from __future__ import annotations

import logging
from typing import Any

from kali_mcp.db.manager import DBManager
from kali_mcp.studio.mcp_client import ExternalMCPClient, MCPClientError
from kali_mcp.studio.service_tools import import_external_mcp_tools

logger = logging.getLogger("kali_mcp.studio.service_mcp_connections")


def add_connection(
    db: DBManager,
    connection_id: str,
    transport: str,
    *,
    url: str | None = None,
    command: list[str] | None = None,
    timeout: float = 30.0,
    headers: dict[str, str] | None = None,
) -> dict[str, Any]:
    ExternalMCPClient(transport, url=url, command=command, timeout=timeout, headers=headers)
    # Validate construction (raises MCPClientError on bad config)
    return {
        "connection_id": connection_id,
        "transport": transport,
        "url": url,
        "command": command,
        "timeout": timeout,
    }


async def discover_and_import(
    db: DBManager,
    connection_id: str,
    client: ExternalMCPClient,
    *,
    visibility: str = "internal",
) -> list[dict[str, Any]]:
    """Discover tools from an external MCP server and import them into the DB."""
    try:
        return await import_external_mcp_tools(db, connection_id, client, visibility=visibility)
    except MCPClientError as exc:
        logger.error("External MCP discovery failed for %s: %s", connection_id, exc)
        raise


def test_connection(client: ExternalMCPClient) -> bool:
    """Best-effort connectivity check."""
    try:
        import asyncio

        async def _probe() -> bool:
            async with client:
                await client.list_tools()
            return True

        return asyncio.run(_probe())
    except Exception:  # noqa: BLE001
        return False


__all__ = ["add_connection", "discover_and_import", "test_connection"]
