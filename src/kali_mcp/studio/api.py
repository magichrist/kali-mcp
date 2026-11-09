"""Studio REST API routes.

Mounts all Studio (Playbook Studio) REST endpoints on the main Starlette app
via ``mount_studio_routes(app)``. Called from ``src/kali_mcp/server.py``
lifespan startup.
"""

from __future__ import annotations

import json
import logging

from starlette.requests import Request
from starlette.responses import JSONResponse

from kali_mcp.config import config
from kali_mcp.db import manager as db_manager
from kali_mcp.studio import service_agents, service_connections, service_mcp_connections

logger = logging.getLogger("kali_mcp.studio.api")


# ══════════════════════════════════════════════════════════════════════════════
# Playbook CRUD routes
# ══════════════════════════════════════════════════════════════════════════════


async def list_playbooks(request: Request) -> JSONResponse:
    """List playbooks (with optional status/builtin filtering)."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)

    status = request.query_params.get("status")
    is_builtin = request.query_params.get("is_builtin")
    limit = int(request.query_params.get("limit", "50"))
    offset = int(request.query_params.get("offset", "0"))

    rows = db_manager.DBManager.list_playbooks(db, status=status)

    if is_builtin is not None:
        want = is_builtin.lower() in ("1", "true", "yes")
        rows = [r for r in rows if bool(r.get("is_builtin", 0)) == want]

    rows = rows[offset : offset + limit]
    return JSONResponse({"playbooks": rows, "limit": limit, "offset": offset})


async def get_playbook(request: Request) -> JSONResponse:
    """Get playbook metadata."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)

    playbook_id = request.path_params["id"]
    row = db.get_playbook(playbook_id)
    if row is None:
        return JSONResponse({"error": "playbook not found"}, status_code=404)
    return JSONResponse(row)


async def put_definition(request: Request) -> JSONResponse:
    """Save playbook definition (draft)."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)

    playbook_id = request.path_params["id"]
    body = await request.json()
    definition = body.get("definition")
    if not isinstance(definition, dict):
        return JSONResponse({"error": "definition is required"}, status_code=422)

    from kali_mcp.studio import playbook_service

    validation = playbook_service.validate_definition(db, playbook_id, definition)
    if not validation["valid"]:
        return JSONResponse(
            {"error": "definition failed validation", "details": validation["findings"]},
            status_code=422,
        )

    playbook_service.update_playbook(
        db, playbook_id, status="draft", draft_definition=json.dumps(definition)
    )

    return JSONResponse({"playbook_id": playbook_id, "valid": True})


async def get_definition_api(request: Request) -> JSONResponse:
    """Get playbook definition (draft if present, else latest published version)."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)

    playbook_id = request.path_params["id"]
    row = db.get_playbook(playbook_id)
    if row is None:
        return JSONResponse({"error": "playbook not found"}, status_code=404)

    # Prefer draft_definition if present
    draft = row.get("draft_definition")
    if draft:
        try:
            definition = json.loads(draft) if isinstance(draft, str) else draft
            return JSONResponse({"definition": definition, "draft": True})
        except (TypeError, ValueError):
            pass

    # Fall back to latest published version
    versions = db.list_playbook_versions(playbook_id)
    if versions:
        version = versions[-1]  # ordered oldest-first; last is latest
        definition = version.get("definition")
        if isinstance(definition, str):
            try:
                definition = json.loads(definition)
            except (TypeError, ValueError):
                definition = None
        return JSONResponse({"definition": definition, "draft": False})

    return JSONResponse({"error": "no definition found"}, status_code=404)


async def put_definition_publish(request: Request) -> JSONResponse:
    """Publish playbook definition."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)

    playbook_id = request.path_params["id"]
    body = await request.json()
    definition = body.get("definition")
    version = body.get("version", "1.0.0")

    if not isinstance(definition, dict):
        return JSONResponse({"error": "definition is required"}, status_code=422)

    from kali_mcp.studio import playbook_service

    validation = playbook_service.validate_definition(db, playbook_id, definition, for_publish=True)
    if not validation["valid"]:
        return JSONResponse(
            {"error": "definition failed validation", "details": validation["findings"]},
            status_code=422,
        )

    vid = playbook_service.publish_version(
        db, playbook_id, version, definition, published_by="studio"
    )

    return JSONResponse(
        {
            "playbook_id": playbook_id,
            "version_id": vid,
            "status": "published",
        }
    )


async def list_versions(request: Request) -> JSONResponse:
    """List playbook versions."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)

    playbook_id = request.path_params["id"]
    versions = db.list_playbook_versions(playbook_id)
    return JSONResponse({"versions": versions})


async def rollback_playbook(request: Request) -> JSONResponse:
    """Rollback playbook to a previous version."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)

    playbook_id = request.path_params["id"]
    body = await request.json()
    version_id = body.get("version_id")

    from kali_mcp.studio import playbook_service

    try:
        playbook_service.rollback_version(db, playbook_id, version_id)
    except (ValueError, LookupError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    return JSONResponse({"status": "rolled_back", "version_id": str(version_id)})


async def export_playbook(request: Request) -> JSONResponse:
    """Export playbook."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)

    playbook_id = request.path_params["id"]
    from kali_mcp.studio import playbook_service

    pkg = playbook_service.export_playbook(db, playbook_id)
    if pkg is None:
        return JSONResponse({"error": "playbook not found"}, status_code=404)

    return JSONResponse(pkg)


async def import_playbook(request: Request) -> JSONResponse:
    """Import playbook."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)

    body = await request.json()
    package = body.get("package")
    if not package:
        return JSONResponse({"error": "package is required"}, status_code=422)

    from kali_mcp.studio import playbook_service

    result = playbook_service.import_playbook(db, package)
    return JSONResponse(result)


async def delete_playbook(request: Request) -> JSONResponse:
    """Delete playbook."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)

    playbook_id = request.path_params["id"]
    from kali_mcp.studio import playbook_service

    ok = playbook_service.delete_playbook(db, playbook_id)
    if not ok:
        return JSONResponse({"error": "playbook not found"}, status_code=404)

    return JSONResponse({"status": "deleted"})


# ══════════════════════════════════════════════════════════════════════════════
# Execution routes
# ══════════════════════════════════════════════════════════════════════════════


async def list_executions(request: Request) -> JSONResponse:
    """List workflow executions."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)

    from kali_mcp.studio import service_executions

    status = request.query_params.get("status")
    playbook_id = request.query_params.get("playbook_id")
    limit = int(request.query_params.get("limit", "50"))
    offset = int(request.query_params.get("offset", "0"))

    rows = service_executions.list_executions(
        db, status=status, playbook_id=playbook_id, limit=limit, offset=offset
    )
    return JSONResponse({"executions": rows, "limit": limit, "offset": offset})


async def start_execution(request: Request) -> JSONResponse:
    """Start a playbook execution."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)

    from kali_mcp.studio import service_executions

    try:
        body = await request.json()
    except Exception:
        return JSONResponse({"error": "invalid JSON"}, status_code=400)

    playbook_id = body.get("playbook_id")
    inputs = body.get("inputs")
    debug = body.get("debug", False)
    trigger = body.get("trigger", "studio")

    try:
        result = await service_executions.start_execution(
            db, playbook_id, inputs=inputs, debug=debug, trigger=trigger
        )
    except (LookupError, ValueError) as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    return JSONResponse(result)


async def get_execution(request: Request) -> JSONResponse:
    """Get execution detail."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)

    from kali_mcp.studio import service_executions

    execution_id = request.path_params["id"]
    row = service_executions.get_execution(db, execution_id)
    if row is None:
        return JSONResponse({"error": "execution not found"}, status_code=404)
    return JSONResponse({"execution": row})


async def cancel_execution(request: Request) -> JSONResponse:
    """Cancel execution."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)

    from kali_mcp.studio import service_executions

    execution_id = request.path_params["id"]
    try:
        await service_executions.cancel_execution(db, execution_id)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    return JSONResponse({"status": "cancelled"})


async def resume_execution(request: Request) -> JSONResponse:
    """Resume execution."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)

    from kali_mcp.studio import service_executions

    execution_id = request.path_params["id"]
    try:
        await service_executions.resume_execution(db, execution_id)
    except Exception as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)

    return JSONResponse({"status": "resumed"})


# ══════════════════════════════════════════════════════════════════════════════
# mount_studio_routes — mounts all studio routes on a Starlette app
# ══════════════════════════════════════════════════════════════════════════════


async def server_info(request: Request) -> JSONResponse:
    """Return server info for the UI."""
    from pathlib import Path

    db_path = Path(config.db_path)
    db_exists = db_path.exists()
    return JSONResponse(
        {
            "db_path": str(db_path),
            "db_exists": db_exists,
            "server_name": getattr(config, "server_name", "kali-mcp"),
            "server_version": getattr(config, "server_version", "2.0.0"),
            "host": getattr(config, "host", "127.0.0.1"),
            "port": getattr(config, "port", 8399),
            "transport": getattr(config, "transport", "streamable-http"),
            "auth_enabled": bool(getattr(config, "mcp_api_token", None))
            and not getattr(config, "kali_mcp_insecure", False),
            "default_timeout": getattr(config, "default_timeout", 300),
            "max_timeout": getattr(config, "max_timeout", 600),
            "max_concurrent": getattr(config, "max_concurrent", 10),
            "debug": bool(getattr(config, "debug", False)),
        }
    )


async def list_connections_api(request: Request) -> JSONResponse:
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)
    conns = service_connections.list_connections(db)
    return JSONResponse({"connections": conns, "count": len(conns)})


async def upsert_connection_api(request: Request) -> JSONResponse:
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)
    body = await request.json()
    connection_id = body.get("connection_id")
    name = body.get("name")
    transport = body.get("transport")
    if not connection_id or not name or not transport:
        return JSONResponse({"error": "connection_id, name, transport required"}, status_code=400)
    row = service_connections.upsert_connection(
        db,
        connection_id=connection_id,
        name=name,
        transport=transport,
        description=body.get("description"),
        endpoint_url=body.get("endpoint_url"),
        command=body.get("command"),
        args=body.get("args"),
        auth_type=body.get("auth_type"),
        auth_config=body.get("auth_config"),
        enabled=body.get("enabled", True),
    )
    return JSONResponse(row, status_code=201)


async def get_connection_api(request: Request) -> JSONResponse:
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)
    connection_id = request.path_params["id"]
    cur = db.conn.cursor()
    row = cur.execute(
        "SELECT * FROM mcp_connections WHERE connection_id = ?", (connection_id,)
    ).fetchone()
    if row is None:
        return JSONResponse({"error": "connection not found"}, status_code=404)
    c = dict(row)
    for field in ("args", "auth_config"):
        raw = c.get(field)
        if raw:
            try:
                c[field] = json.loads(raw)
            except (TypeError, ValueError):
                pass
    cur.execute(
        "SELECT tool_id, visibility FROM tool_definitions WHERE provider = ?",
        (connection_id,),
    )
    imported_tools = [{"tool_id": r[0], "visibility": r[1]} for r in cur.fetchall()]
    c["imported_tools"] = imported_tools
    c["imported_tool_count"] = len(imported_tools)
    return JSONResponse({"connection": c})


async def delete_connection_api(request: Request) -> JSONResponse:
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)
    connection_id = request.path_params["id"]
    deleted = service_connections.delete_connection(db, connection_id)
    if not deleted:
        return JSONResponse({"error": "connection not found"}, status_code=404)
    return JSONResponse({"status": "deleted"})


async def test_connection_api(request: Request) -> JSONResponse:
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)
    connection_id = request.path_params["id"]
    cur = db.conn.cursor()
    row = cur.execute(
        "SELECT transport, endpoint_url, command FROM mcp_connections WHERE connection_id = ?",
        (connection_id,),
    ).fetchone()
    if row is None:
        return JSONResponse({"error": "connection not found"}, status_code=404)
    transport, endpoint_url, command = row
    from kali_mcp.studio.mcp_client import ExternalMCPClient

    client = ExternalMCPClient(
        transport,
        url=endpoint_url,
        command=command.split() if command else None,
    )
    ok = service_mcp_connections.test_connection(client)
    service_connections.set_health(db, connection_id, ok)
    return JSONResponse({"ok": ok, "healthy": ok})


async def discover_connection_api(request: Request) -> JSONResponse:
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)
    connection_id = request.path_params["id"]
    cur = db.conn.cursor()
    row = cur.execute(
        "SELECT transport, endpoint_url, command FROM mcp_connections WHERE connection_id = ?",
        (connection_id,),
    ).fetchone()
    if row is None:
        return JSONResponse({"error": "connection not found"}, status_code=404)
    transport, endpoint_url, command = row
    from kali_mcp.studio.mcp_client import ExternalMCPClient

    client = ExternalMCPClient(
        transport,
        url=endpoint_url,
        command=command.split() if command else None,
    )
    imported = await service_mcp_connections.discover_and_import(
        db,
        connection_id,
        client,
        visibility="internal",
    )
    service_connections.set_health(db, connection_id, True)
    return JSONResponse({"imported_tools": imported, "count": len(imported)})


async def overview_api(request: Request) -> JSONResponse:
    """Aggregate dashboard overview stats from across the studio."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)

    cur = db.conn.cursor()

    # Playbooks
    pb_rows = db_manager.DBManager.list_playbooks(db)
    pb_by_status: dict[str, int] = {}
    for r in pb_rows:
        st = r.get("status") or "unknown"
        pb_by_status[st] = pb_by_status.get(st, 0) + 1

    # Executions
    from kali_mcp.studio import service_executions

    exec_rows = service_executions.list_executions(db, limit=500)
    ex_by_status: dict[str, int] = {}
    for r in exec_rows:
        st = r.get("status") or "unknown"
        ex_by_status[st] = ex_by_status.get(st, 0) + 1
    recent_executions = [
        {
            "execution_id": r.get("execution_id"),
            "playbook_id": r.get("playbook_id"),
            "status": r.get("status"),
            "started_at": r.get("started_at"),
        }
        for r in exec_rows[:10]
    ]

    # Tools
    td_rows = db.list_tool_definitions()
    td_by_visibility: dict[str, int] = {}
    for r in td_rows:
        vis = r.get("visibility") or "unknown"
        td_by_visibility[vis] = td_by_visibility.get(vis, 0) + 1

    # Connections
    conn_rows = service_connections.list_connections(db)
    conn_healthy = sum(1 for c in conn_rows if c.get("health_status") == "healthy")

    # Agents
    try:
        agent_rows = db.list_agent_profiles()
    except Exception:
        agent_rows = []

    # Findings
    findings_total = 0
    try:
        ft = cur.execute("SELECT COALESCE(SUM(findings_count), 0) FROM scans").fetchone()[0]
        findings_total = int(ft or 0)
    except Exception:
        findings_total = 0

    try:
        finding_rows = cur.execute(
            "SELECT tool, command, findings_count, started_at FROM scans ORDER BY started_at DESC LIMIT 10"
        ).fetchall()
        recent_findings = [
            {
                "port_state": r[0] or "—",
                "tool": r[1] or "—",
                "severity": "info",
                "test_name": f"scan ({r[2] or 0} findings)",
            }
            for r in finding_rows
        ]
    except Exception:
        recent_findings = []

    return JSONResponse(
        {
            "playbooks": {"total": len(pb_rows), "by_status": pb_by_status},
            "executions": {"total": len(exec_rows), "by_status": ex_by_status},
            "tools": {"total": len(td_rows), "by_visibility": td_by_visibility},
            "findings": {"total": findings_total, "by_severity": {}},
            "connections": {"total": len(conn_rows), "healthy": conn_healthy},
            "agents": {"total": len(agent_rows)},
            "recent_executions": recent_executions,
            "recent_findings": recent_findings,
        }
    )


# ══════════════════════════════════════════════════════════════════════════════
# Tool Registry handlers
# ══════════════════════════════════════════════════════════════════════════════


async def list_tools_api(request: Request) -> JSONResponse:
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)
    limit = int(request.query_params.get("limit", 500))
    visibility = request.query_params.get("visibility")
    enabled = request.query_params.get("enabled")
    enabled_bool = None
    if enabled is not None:
        enabled_bool = enabled.lower() == "true"
    rows = db.list_tool_definitions(
        visibility=visibility,
        enabled=enabled_bool,
    )
    tools = []
    for r in rows[:limit]:
        tools.append(
            {
                "tool_id": r["tool_id"],
                "name": r["name"],
                "description": r["description"],
                "provider": r["provider"],
                "visibility": r["visibility"],
                "enabled": bool(r["enabled"]),
                "input_schema": r["input_schema"],
            }
        )
    return JSONResponse({"tools": tools, "count": len(tools)})


async def set_tool_visibility_api(request: Request) -> JSONResponse:
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)
    tool_id = request.path_params["id"]
    body = await request.json()
    visibility = body.get("visibility")
    if not visibility:
        return JSONResponse({"error": "visibility required"}, status_code=400)
    db.upsert_tool_definition(
        tool_id=tool_id,
        name=tool_id,
        description=None,
        provider="native",
        visibility=visibility,
        enabled=True,
    )
    from kali_mcp.registry import registry as global_registry

    global_registry.set_visibility(tool_id, visibility)
    return JSONResponse({"tool_id": tool_id, "visibility": visibility})


async def findings_api(request: Request) -> JSONResponse:
    """Query normalized findings with optional filters."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)
    target = request.query_params.get("target")
    severity = request.query_params.get("severity")
    tool = request.query_params.get("tool")
    limit = int(request.query_params.get("limit", "100"))
    offset = int(request.query_params.get("offset", "0"))
    result = db.query_findings(
        target=target,
        severity=severity,
        tool=tool,
        limit=limit,
        offset=offset,
    )
    return JSONResponse(result)


# ══════════════════════════════════════════════════════════════════════════════
# Agent Profiles routes
# ══════════════════════════════════════════════════════════════════════════════


async def list_agents_api(request: Request) -> JSONResponse:
    """List all agent profiles."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)
    rows = service_agents.list_profiles(db)
    agents = []
    for r in rows:
        agents.append(
            {
                "profile_id": r.get("profile_id"),
                "name": r.get("name"),
                "description": r.get("description"),
                "default_visibility": r.get("default_visibility"),
                "max_parallel_operations": r.get("max_parallel_operations"),
                "max_execution_seconds": r.get("max_execution_seconds"),
            }
        )
    return JSONResponse({"agents": agents})


async def create_agent_api(request: Request) -> JSONResponse:
    """Create an agent profile."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)
    body = await request.json()
    profile_id = body.get("profile_id")
    name = body.get("name")
    if not profile_id or not name:
        return JSONResponse({"error": "profile_id and name required"}, status_code=400)
    try:
        service_agents.create_profile(
            db,
            profile_id,
            name,
            description=body.get("description"),
        )
    except ValueError as exc:
        return JSONResponse({"error": str(exc)}, status_code=400)
    return JSONResponse(service_agents.get_profile(db, profile_id), status_code=201)


async def get_agent_api(request: Request) -> JSONResponse:
    """Get agent profile with effective catalog, permissions and assignments."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)
    profile_id = request.path_params["id"]
    agent = service_agents.get_profile(db, profile_id)
    if agent is None:
        return JSONResponse({"error": "agent profile not found"}, status_code=404)
    catalog = service_agents.effective_catalog(db, profile_id)
    permissions = service_agents.list_tool_permission_rows(db, profile_id)
    for p in permissions:
        p["profile_id"] = profile_id
    assignments = service_agents.list_playbook_assignments(db, profile_id)
    for a in assignments:
        a["profile_id"] = profile_id
    return JSONResponse(
        {
            "agent": agent,
            "effective_catalog": catalog,
            "permissions": permissions,
            "assignments": assignments,
        }
    )


async def delete_agent_api(request: Request) -> JSONResponse:
    """Delete an agent profile."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)
    profile_id = request.path_params["id"]
    deleted = service_agents.delete_profile(db, profile_id)
    if not deleted:
        return JSONResponse({"error": "agent profile not found"}, status_code=404)
    return JSONResponse({"status": "deleted"})


async def grant_agent_tool_api(request: Request) -> JSONResponse:
    """Grant a tool to an agent profile."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)
    profile_id = request.path_params["id"]
    tool_id = request.path_params["tool_id"]
    service_agents.grant_tool(db, profile_id, tool_id, granted=True)
    return JSONResponse({"profile_id": profile_id, "tool_id": tool_id, "granted": True})


async def revoke_agent_tool_api(request: Request) -> JSONResponse:
    """Revoke a tool from an agent profile."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)
    profile_id = request.path_params["id"]
    tool_id = request.path_params["tool_id"]
    service_agents.revoke_tool(db, profile_id, tool_id)
    return JSONResponse({"profile_id": profile_id, "tool_id": tool_id, "revoked": True})


async def assign_agent_playbook_api(request: Request) -> JSONResponse:
    """Assign a playbook to an agent profile."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)
    profile_id = request.path_params["id"]
    playbook_id = request.path_params["playbook_id"]
    service_agents.assign_playbook(db, profile_id, playbook_id, granted=True)
    return JSONResponse({"profile_id": profile_id, "playbook_id": playbook_id, "assigned": True})


async def unassign_agent_playbook_api(request: Request) -> JSONResponse:
    """Unassign a playbook from an agent profile."""
    db = db_manager.get_db()
    if db is None:
        return JSONResponse({"error": "database unavailable"}, status_code=500)
    profile_id = request.path_params["id"]
    playbook_id = request.path_params["playbook_id"]
    service_agents.unassign_playbook(db, profile_id, playbook_id)
    return JSONResponse({"profile_id": profile_id, "playbook_id": playbook_id, "unassigned": True})


def mount_studio_routes(app) -> None:
    """Mount all Studio REST routes on the given Starlette app."""

    # Playbook routes
    app.add_route("/api/playbooks", list_playbooks, methods=["GET"])
    app.add_route("/api/playbooks", import_playbook, methods=["POST"])
    app.add_route("/api/playbooks/{id}", get_playbook, methods=["GET"])
    app.add_route("/api/playbooks/{id}", delete_playbook, methods=["DELETE"])
    app.add_route("/api/playbooks/{id}/definition", put_definition, methods=["PUT"])
    app.add_route("/api/playbooks/{id}/definition", get_definition_api, methods=["GET"])
    app.add_route("/api/playbooks/{id}/publish", put_definition_publish, methods=["POST"])
    app.add_route("/api/playbooks/{id}/validate-definition", put_definition, methods=["POST"])
    app.add_route("/api/playbooks/{id}/versions", list_versions, methods=["GET"])
    app.add_route("/api/playbooks/{id}/rollback", rollback_playbook, methods=["POST"])
    app.add_route("/api/playbooks/{id}/export", export_playbook, methods=["GET"])

    # Server info
    app.add_route("/api/server", server_info, methods=["GET"])

    # Overview
    app.add_route("/api/overview", overview_api, methods=["GET"])

    # MCP Connections routes
    app.add_route("/api/connections", list_connections_api, methods=["GET"])
    app.add_route("/api/connections", upsert_connection_api, methods=["POST"])
    app.add_route("/api/connections/{id}", get_connection_api, methods=["GET"])
    app.add_route("/api/connections/{id}", delete_connection_api, methods=["DELETE"])
    app.add_route("/api/connections/{id}/test", test_connection_api, methods=["POST"])
    app.add_route("/api/connections/{id}/discover", discover_connection_api, methods=["POST"])

    # Tool Registry routes
    app.add_route("/api/tools", list_tools_api, methods=["GET"])
    app.add_route("/api/tools/{id}/visibility", set_tool_visibility_api, methods=["PUT"])

    # Findings routes
    app.add_route("/api/findings", findings_api, methods=["GET"])

    # Agent Profiles routes
    app.add_route("/api/agents", list_agents_api, methods=["GET"])
    app.add_route("/api/agents", create_agent_api, methods=["POST"])
    app.add_route("/api/agents/{id}", get_agent_api, methods=["GET"])
    app.add_route("/api/agents/{id}", delete_agent_api, methods=["DELETE"])
    app.add_route("/api/agents/{id}/tools/{tool_id}", grant_agent_tool_api, methods=["PUT"])
    app.add_route("/api/agents/{id}/tools/{tool_id}", revoke_agent_tool_api, methods=["DELETE"])
    app.add_route(
        "/api/agents/{id}/playbooks/{playbook_id}", assign_agent_playbook_api, methods=["PUT"]
    )
    app.add_route(
        "/api/agents/{id}/playbooks/{playbook_id}", unassign_agent_playbook_api, methods=["DELETE"]
    )

    # Execution routes
    app.add_route("/api/executions", list_executions, methods=["GET"])
    app.add_route("/api/executions", start_execution, methods=["POST"])
    app.add_route("/api/executions/{id}", get_execution, methods=["GET"])
    app.add_route("/api/executions/{id}/cancel", cancel_execution, methods=["POST"])
    app.add_route("/api/executions/{id}/resume", resume_execution, methods=["POST"])
