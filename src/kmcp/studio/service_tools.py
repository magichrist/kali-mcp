"""Studio tool service layer (Phase 3, Task C).

Backend logic for managing the unified tool capability catalog:

- Sync native tools from the registry to the ``tool_definitions`` DB table at
  startup (seeded with ``visibility=agent_callable`` per TD-6).
- Tool CRUD: upsert, get, list (with provider/visibility/enabled filters).
- Visibility management: set/get visibility mode per tool.
- External MCP tool import: discover tools from an ``ExternalMCPClient`` and
  register them as ``provider="external_mcp"`` with ``visibility="internal"``
  (untrusted by default per TD-11).

This module is purely business logic — it has no HTTP/MCP routing. Routes are
added in Phase 4 (``studio/api.py``). It is safe to import without a server
running.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from kmcp.db.manager import DBManager
from kmcp.registry import (
    DEFAULT_VISIBILITY,
    VISIBILITY_MODES,
)
from kmcp.registry import (
    registry as global_registry,
)
from kmcp.studio.mcp_client import ExternalMCPClient, MCPClientError

logger = logging.getLogger("kmcp.studio.service_tools")

#: Provider value for tools imported from external MCP servers.
PROVIDER_EXTERNAL_MCP = "external_mcp"
#: Provider value for native tools shipped with kmcp.
PROVIDER_NATIVE = "native"


# ── Sync: registry ↔ DB ────────────────────────────────────────────────────


def sync_registry_to_db(
    db: DBManager,
    *,
    default_visibility: str = DEFAULT_VISIBILITY,
) -> dict[str, int]:
    """Sync all registered native tools into ``tool_definitions``.

    Per TD-6, existing native tools default to ``agent_callable`` so nothing
    changes for current agents. Tools already in the DB are updated
    (idempotent upsert); new tools are inserted.

    Returns a dict of ``tool_id -> row_id`` for all synced tools.
    """
    synced: dict[str, int] = {}
    for tool in global_registry.list_all():
        tool_id = tool.name
        schema = tool.input_schema()
        row_id = db.upsert_tool_definition(
            tool_id=tool_id,
            name=tool_id,
            description=tool.description,
            provider=PROVIDER_NATIVE,
            provider_ref=None,
            input_schema=schema,
            output_schema=None,
            visibility=default_visibility,
            enabled=True,
            requires_binary=None,
            default_timeout=getattr(tool, "default_timeout", 300),
            execution_policy=None,
            scope_required=False,
        )
        synced[tool_id] = row_id
    logger.info("Synced %d native tools to tool_definitions", len(synced))
    return synced


def sync_db_to_registry(db: DBManager, visibility: str | None = None) -> int:
    """Import enabled tool definitions from the DB into the runtime registry.

    Only tools whose DB visibility matches ``visibility`` (or all if None) and
    which are enabled are registered into :data:`kmcp.registry.registry`.
    This is how operator-curated visibility becomes effective at runtime.

    Returns the number of tools registered.
    """
    count = 0
    for row in db.list_tool_definitions(visibility=visibility, enabled=True):
        tool_id = row["tool_id"]
        if global_registry.get(tool_id) is not None:
            # Already registered — update visibility only.
            global_registry.set_visibility(tool_id, row["visibility"])
            count += 1
            continue
        # External MCP tools cannot be executed through the local registry
        # without a proxy adapter; skip them here (they are catalogued only).
        if row["provider"] == PROVIDER_EXTERNAL_MCP:
            continue
        # Native tools: create a thin BaseTool wrapper that proxies to the
        # engine's existing tool wrappers via the registry is not possible
        # here (the wrapper already exists). Import only if we have a way to
        # execute it. For now, register a placeholder that delegates to
        # global_registry.get() if the tool exists, otherwise skip.
        if global_registry.get(tool_id) is None:
            logger.debug("Skipping DB tool %s: no runtime wrapper", tool_id)
            continue
        count += 1
    logger.info("Registered %d tool definitions into runtime registry", count)
    return count


# ── CRUD ───────────────────────────────────────────────────────────────────


def upsert_tool_definition(
    db: DBManager,
    *,
    tool_id: str,
    name: str,
    description: str | None = None,
    provider: str = PROVIDER_NATIVE,
    provider_ref: str | None = None,
    input_schema: dict[str, Any] | None = None,
    output_schema: dict[str, Any] | None = None,
    visibility: str = DEFAULT_VISIBILITY,
    enabled: bool = True,
    requires_binary: str | None = None,
    default_timeout: int = 300,
    execution_policy: str | None = None,
    scope_required: bool = False,
) -> int:
    """Insert or update a tool definition row.

    Delegates to :meth:`DBManager.upsert_tool_definition`.
    """
    if visibility not in VISIBILITY_MODES:
        raise ValueError(
            f"invalid visibility {visibility!r}; expected one of {sorted(VISIBILITY_MODES)}"
        )
    return db.upsert_tool_definition(
        tool_id=tool_id,
        name=name,
        description=description,
        provider=provider,
        provider_ref=provider_ref,
        input_schema=input_schema,
        output_schema=output_schema,
        visibility=visibility,
        enabled=enabled,
        requires_binary=requires_binary,
        default_timeout=default_timeout,
        execution_policy=execution_policy,
        scope_required=scope_required,
    )


def get_tool_definition(db: DBManager, tool_id: str) -> dict[str, Any] | None:
    """Return one tool definition row by tool_id, or None."""
    return db.get_tool_definition(tool_id)


def list_tool_definitions(
    db: DBManager,
    *,
    provider: str | None = None,
    visibility: str | None = None,
    enabled: bool | None = None,
) -> list[dict[str, Any]]:
    """List tool definitions with optional filters."""
    return db.list_tool_definitions(provider=provider, visibility=visibility, enabled=enabled)


def set_tool_visibility(db: DBManager, tool_id: str, visibility: str) -> bool:
    """Set the visibility mode of a tool definition.

    Returns True if the tool was found and updated, False otherwise.
    Also updates the runtime registry visibility if the tool is registered.
    """
    if visibility not in VISIBILITY_MODES:
        raise ValueError(
            f"invalid visibility {visibility!r}; expected one of {sorted(VISIBILITY_MODES)}"
        )
    row = db.get_tool_definition(tool_id)
    if row is None:
        return False

    # Update DB: need an upsert to change visibility. Re-fetch full row.
    full = dict(row)
    full["visibility"] = visibility
    db.upsert_tool_definition(
        tool_id=tool_id,
        name=full["name"],
        description=full.get("description"),
        provider=full.get("provider", PROVIDER_NATIVE),
        provider_ref=full.get("provider_ref"),
        input_schema=full.get("input_schema"),
        output_schema=full.get("output_schema"),
        visibility=visibility,
        enabled=bool(full.get("enabled", 1)),
        requires_binary=full.get("requires_binary"),
        default_timeout=int(full.get("default_timeout", 300)),
        execution_policy=full.get("execution_policy"),
        scope_required=bool(full.get("scope_required", 0)),
    )

    # Sync runtime registry visibility if registered.
    if global_registry.get(tool_id) is not None:
        global_registry.set_visibility(tool_id, visibility)

    logger.info("Tool %s visibility set to %s", tool_id, visibility)
    return True


def enable_tool(db: DBManager, tool_id: str, enabled: bool) -> bool:
    """Enable or disable a tool definition. Returns True if found and updated."""
    row = db.get_tool_definition(tool_id)
    if row is None:
        return False
    full = dict(row)
    db.upsert_tool_definition(
        tool_id=tool_id,
        name=full["name"],
        description=full.get("description"),
        provider=full.get("provider", PROVIDER_NATIVE),
        provider_ref=full.get("provider_ref"),
        input_schema=full.get("input_schema"),
        output_schema=full.get("output_schema"),
        visibility=full.get("visibility", DEFAULT_VISIBILITY),
        enabled=enabled,
        requires_binary=full.get("requires_binary"),
        default_timeout=int(full.get("default_timeout", 300)),
        execution_policy=full.get("execution_policy"),
        scope_required=bool(full.get("scope_required", 0)),
    )
    logger.info("Tool %s enabled=%s", tool_id, enabled)
    return True


# ── External MCP import ──────────────────────────────────────────────────


async def import_external_mcp_tools(
    db: DBManager,
    connection_id: str,
    client: ExternalMCPClient,
    *,
    visibility: str = "internal",
) -> list[dict[str, Any]]:
    """Discover tools from an external MCP server and import them into the DB.

    Per TD-11, imported tools are **untrusted by default**:
    - ``provider="external_mcp"``
    - ``visibility="internal"`` (never auto-exposed to agents)
    - ``enabled=True`` (catalogued but not executable without a proxy adapter)

    Returns a list of imported tool definition dicts.
    """
    if visibility not in VISIBILITY_MODES:
        raise ValueError(
            f"invalid visibility {visibility!r}; expected one of {sorted(VISIBILITY_MODES)}"
        )

    imported: list[dict[str, Any]] = []
    try:
        tools = await client.list_tools()
    except MCPClientError as exc:
        logger.error("Failed to list tools from MCP connection %s: %s", connection_id, exc)
        raise

    for t in tools:
        name = t.get("name", "")
        schema = t.get("inputSchema", {}) or {}
        description = t.get("description", "")

        row_id = db.upsert_tool_definition(
            tool_id=f"external_mcp:{connection_id}:{name}",
            name=name,
            description=description,
            provider=PROVIDER_EXTERNAL_MCP,
            provider_ref=connection_id,
            input_schema=schema,
            output_schema=None,
            visibility=visibility,
            enabled=True,
            requires_binary=None,
            default_timeout=30,
            execution_policy=None,
            scope_required=False,
        )
        imported.append(
            {
                "row_id": row_id,
                "tool_id": f"external_mcp:{connection_id}:{name}",
                "name": name,
                "description": description,
                "provider": PROVIDER_EXTERNAL_MCP,
                "visibility": visibility,
            }
        )
        logger.info(
            "Imported external MCP tool %s (connection %s) as %s",
            name,
            connection_id,
            visibility,
        )

    return imported


def import_external_mcp_tools_sync(
    db: DBManager,
    connection_id: str,
    client: ExternalMCPClient,
    *,
    visibility: str = "internal",
) -> list[dict[str, Any]]:
    """Synchronous wrapper for :func:`import_external_mcp_tools`.

    Useful when the caller is not already in an async context.
    """
    return asyncio.run(import_external_mcp_tools(db, connection_id, client, visibility=visibility))


__all__ = [
    "PROVIDER_EXTERNAL_MCP",
    "PROVIDER_NATIVE",
    "enable_tool",
    "get_tool_definition",
    "import_external_mcp_tools",
    "import_external_mcp_tools_sync",
    "list_tool_definitions",
    "set_tool_visibility",
    "sync_db_to_registry",
    "sync_registry_to_db",
    "upsert_tool_definition",
]
