"""Studio REST API routes.

Mounts all Studio (Playbook Studio) REST endpoints on the main Starlette app
via ``mount_studio_routes(app)``. Called from ``src/kali_mcp/server.py``
lifespan startup.
"""

from __future__ import annotations

import json
import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse

from kali_mcp.db import manager as db_manager
from kali_mcp.config import config
from kali_mcp.studio import service_connections, service_mcp_connections

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

    return JSONResponse({
        "playbook_id": playbook_id,
        "version_id": vid,
        "status": "published",
    })


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
    return JSONResponse(row)


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
    return JSONResponse({
        "db_path": str(db_path),
        "db_exists": db_exists,
    })


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
    imported_tools = [
        {"tool_id": r[0], "visibility": r[1]} for r in cur.fetchall()
    ]
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
        transport, url=endpoint_url, command=command.split() if command else None,
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
        transport, url=endpoint_url, command=command.split() if command else None,
    )
    imported = await service_mcp_connections.discover_and_import(
        db, connection_id, client, visibility="internal",
    )
    service_connections.set_health(db, connection_id, True)
    return JSONResponse({"imported_tools": imported, "count": len(imported)})


def mount_studio_routes(app) -> None:
    """Mount all Studio REST routes on the given Starlette app."""

    # Playbook routes
    app.add_route("/api/playbooks", list_playbooks, methods=["GET"])
    app.add_route("/api/playbooks", import_playbook, methods=["POST"])
    app.add_route("/api/playbooks/{id}", get_playbook, methods=["GET"])
    app.add_route("/api/playbooks/{id}", delete_playbook, methods=["DELETE"])
    app.add_route("/api/playbooks/{id}/definition", put_definition, methods=["PUT"])
    app.add_route("/api/playbooks/{id}/publish", put_definition_publish, methods=["POST"])
    app.add_route("/api/playbooks/{id}/validate-definition", put_definition, methods=["POST"])
    app.add_route("/api/playbooks/{id}/versions", list_versions, methods=["GET"])
    app.add_route("/api/playbooks/{id}/rollback", rollback_playbook, methods=["POST"])
    app.add_route("/api/playbooks/{id}/export", export_playbook, methods=["GET"])

    # Server info
    app.add_route("/api/server", server_info, methods=["GET"])

    # MCP Connections routes
    app.add_route("/api/connections", list_connections_api, methods=["GET"])
    app.add_route("/api/connections", upsert_connection_api, methods=["POST"])
    app.add_route("/api/connections/{id}", get_connection_api, methods=["GET"])
    app.add_route("/api/connections/{id}", delete_connection_api, methods=["DELETE"])
    app.add_route("/api/connections/{id}/test", test_connection_api, methods=["POST"])
    app.add_route("/api/connections/{id}/discover", discover_connection_api, methods=["POST"])

    # Execution routes
    app.add_route("/api/executions", list_executions, methods=["GET"])
    app.add_route("/api/executions", start_execution, methods=["POST"])
    app.add_route("/api/executions/{id}", get_execution, methods=["GET"])
    app.add_route("/api/executions/{id}/cancel", cancel_execution, methods=["POST"])
    app.add_route("/api/executions/{id}/resume", resume_execution, methods=["POST"])
