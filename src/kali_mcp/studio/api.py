"""Studio REST API routes (Phase 4).

Mounts all Playbook Studio REST endpoints on the existing Starlette/FastMCP
app in ``src/kali_mcp/server.py``. Routes are additive — existing MCP,
CLI, and TUI behavior is unchanged.

Operator-only endpoints (not MCP tools):
- Playbook CRUD, validate, preview, test, publish, rollback, export, import
- Tool CRUD, visibility management
- MCP connections (discover, import)
- Agent profiles, permissions, assignments, catalog
- Executions: list, detail, start, cancel, steps, artifacts, graph

All mutating endpoints require authentication when MCP_API_TOKEN is set
(existing TokenAuthMiddleware applies to HTTP routes).
"""

from __future__ import annotations

import json
import logging
from typing import Any

from starlette.requests import Request
from starlette.responses import JSONResponse
from starlette.routing import Route

from kali_mcp.db import manager as db_manager
from kali_mcp.studio import (
    approvals,
    audit,
    playbook_service,
    redaction,
    service_agents,
    service_tools,
)
from kali_mcp.studio.mcp_client import ExternalMCPClient
from kali_mcp.workflow.dsl import compile_dsl, deserialize as dsl_serialize

logger = logging.getLogger("kali_mcp.studio.api")


# ── Helpers ────────────────────────────────────────────────────────────────


def _db() -> Any:
    """Get the DB manager singleton."""
    return db_manager.get_db()


async def _json_body(request: Request) -> dict[str, Any]:
    """Parse JSON body, returning {} on failure."""
    try:
        raw = await request.body()
        return json.loads(raw) if raw else {}
    except Exception:  # noqa: BLE001
        return {}


def _ok(data: Any = None, status: int = 200) -> JSONResponse:
    return JSONResponse({"ok": True, "data": data or {}}, status_code=status)


def _error(message: str, status: int = 400, code: str = "error", details: Any = None) -> JSONResponse:
    body: dict[str, Any] = {"ok": False, "error": {"code": code, "message": message}}
    if details is not None:
        body["error"]["details"] = details
    return JSONResponse(body, status_code=status)


# ── Playbook endpoints ────────────────────────────────────────────────────


async def list_playbooks(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    status = request.query_params.get("status")
    is_builtin = request.query_params.get("is_builtin")
    limit = int(request.query_params.get("limit", "50"))
    offset = int(request.query_params.get("offset", "0"))
    rows = playbook_service.list_playbooks(db, status=status)
    # Apply client-side filters DBManager doesn't support
    if is_builtin is not None:
        want = is_builtin.lower() in ("1", "true", "yes")
        rows = [r for r in rows if bool(r.get("is_builtin", 0)) == want]
    rows = rows[offset : offset + limit]
    return _ok({"playbooks": rows, "limit": limit, "offset": offset})


async def create_playbook(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    body = await _json_body(request)
    playbook_id = body.get("playbook_id") or body.get("id")
    name = body.get("name")
    if not playbook_id or not name:
        return _error("playbook_id and name are required", 422)
    try:
        row_id = playbook_service.create_playbook(
            db,
            playbook_id=playbook_id,
            name=name,
            description=body.get("description"),
            category=body.get("category"),
            author=body.get("author"),
            is_builtin=bool(body.get("is_builtin", False)),
            status=body.get("status", "draft"),
        )
    except ValueError as exc:
        return _error(str(exc), 422)
    audit.record_audit(
        db, event="playbook.create", entity_type="playbook", entity_id=playbook_id,
        details={"name": name},
    )
    return _ok({"playbook_id": playbook_id, "row_id": row_id, "status": "draft"}, 201)


async def get_playbook(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    playbook_id = request.path_params["id"]
    row = playbook_service.get_playbook(db, playbook_id)
    if row is None:
        return _error("playbook not found", 404)
    return _ok(row)


async def update_playbook(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    playbook_id = request.path_params["id"]
    body = await _json_body(request)
    ok = playbook_service.update_playbook(
        db, playbook_id,
        name=body.get("name"),
        description=body.get("description"),
        category=body.get("category"),
        author=body.get("author"),
        status=body.get("status"),
        current_version_id=body.get("current_version_id"),
    )
    if not ok:
        return _error("playbook not found", 404)
    audit.record_audit(
        db, event="playbook.update", entity_type="playbook", entity_id=playbook_id,
        details={k: v for k, v in body.items() if v is not None},
    )
    return _ok({"playbook_id": playbook_id})


async def delete_playbook(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    playbook_id = request.path_params["id"]
    ok = playbook_service.delete_playbook(db, playbook_id)
    if not ok:
        return _error("playbook not found", 404)
    audit.record_audit(
        db, event="playbook.delete", entity_type="playbook", entity_id=playbook_id,
    )
    return _ok({"playbook_id": playbook_id})


async def validate_playbook_endpoint(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    playbook_id = request.path_params["id"]
    body = await _json_body(request)
    definition = body.get("definition")
    if not isinstance(definition, dict):
        return _error("definition is required", 422)
    for_publish = body.get("for_publish", False)
    result = playbook_service.validate_definition(db, playbook_id, definition, for_publish=for_publish)
    audit.record_audit(
        db, event="playbook.validate", entity_type="playbook", entity_id=playbook_id,
        details={"for_publish": for_publish, "valid": result["valid"]},
    )
    return _ok(result)


async def preview_playbook_endpoint(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    playbook_id = request.path_params["id"]
    body = await _json_body(request)
    definition = body.get("definition")
    if not isinstance(definition, dict):
        return _error("definition is required", 422)
    result = playbook_service.preview_playbook(db, playbook_id, definition)
    return _ok(result)


async def test_playbook_endpoint(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    playbook_id = request.path_params["id"]
    body = await _json_body(request)
    definition = body.get("definition")
    if not isinstance(definition, dict):
        return _error("definition is required", 422)
    inputs = body.get("inputs")
    result = playbook_service.test_playbook(db, playbook_id, definition, inputs=inputs)
    return _ok(result)


async def publish_playbook(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    playbook_id = request.path_params["id"]
    body = await _json_body(request)
    version = body.get("version")
    definition = body.get("definition")
    notes = body.get("notes")
    if not version:
        return _error("version is required", 422)
    if not isinstance(definition, dict):
        return _error("definition is required", 422)

    # Require approval before publishing
    if not approvals.is_approved(db, approvals.GATE_PUBLISH, playbook_id):
        return _error(
            approvals.require_approval_for(approvals.GATE_PUBLISH),
            403, code="approval_required",
        )

    # Validate first (publish-time rules)
    validation = playbook_service.validate_definition(
        db, playbook_id, definition, for_publish=True
    )
    if not validation["valid"]:
        return _error(
            "definition failed validation", 422, code="validation_error",
            details={"findings": validation["findings"]},
        )

    try:
        vid = playbook_service.publish_version(
            db, playbook_id, version, definition=definition, notes=notes,
        )
    except ValueError as exc:
        return _error(str(exc), 422)

    approvals.approve(db, approval_id=approvals.get_pending_approval(
        approvals.GATE_PUBLISH, playbook_id
    )["id"], approved_by="studio", status="approved")
    audit.record_audit(
        db, event="playbook.publish", entity_type="playbook", entity_id=playbook_id,
        details={"version": version, "version_id": vid},
    )
    return _ok({
        "version_id": vid,
        "version": version,
        "playbook_id": playbook_id,
        "status": "published",
    })


async def list_versions(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    playbook_id = request.path_params["id"]
    versions = playbook_service.list_versions(db, playbook_id)
    return _ok({"playbook_id": playbook_id, "versions": versions})


async def rollback_playbook(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    playbook_id = request.path_params["id"]
    body = await _json_body(request)
    version_id = body.get("version_id")
    if version_id is None:
        return _error("version_id is required", 422)
    try:
        row = playbook_service.rollback_version(db, playbook_id, version_id)
    except ValueError as exc:
        return _error(str(exc), 404)
    audit.record_audit(
        db, event="playbook.rollback", entity_type="playbook", entity_id=playbook_id,
        details={"version_id": version_id},
    )
    return _ok({"playbook_id": playbook_id, "version_id": version_id, "version": row.get("version")})


async def export_playbook_endpoint(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    playbook_id = request.path_params["id"]
    package = playbook_service.export_playbook(db, playbook_id)
    if package is None:
        return _error("playbook not found", 404)
    audit.record_audit(
        db, event="playbook.export", entity_type="playbook", entity_id=playbook_id,
    )
    return _ok(package)


async def import_playbook_endpoint(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    body = await _json_body(request)
    package = body.get("package")
    if not isinstance(package, dict):
        return _error("package is required", 422)

    # Require approval before import activation
    playbook_id = package.get("playbook", {}).get("playbook_id", "")
    if not approvals.is_approved(db, approvals.GATE_IMPORT, playbook_id or "import"):
        return _error(
            approvals.require_approval_for(approvals.GATE_IMPORT),
            403, code="approval_required",
        )

    result = playbook_service.import_playbook(db, package, require_approval=False)
    if not result["ok"]:
        return _error(result["error"], 422)
    approvals.approve(db, approval_id=approvals.get_pending_approval(
        approvals.GATE_IMPORT, playbook_id or "import"
    )["id"], approved_by="studio", status="approved")
    audit.record_audit(
        db, event="playbook.import", entity_type="playbook", entity_id=playbook_id,
        details={"versions_imported": result.get("versions_imported")},
    )
    return _ok(result)


# ── Definition endpoints (visual editor / DSL round-trip) ─────────────────


async def get_definition(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    playbook_id = request.path_params["id"]
    row = playbook_service.get_playbook(db, playbook_id)
    if row is None:
        return _error("playbook not found", 404)
    vid = row.get("current_version_id")
    definition = None
    if vid:
        vrow = db_manager.DBManager.get_playbook_version(db, vid) if False else None
        # Use service layer
        vrow = playbook_service.get_version(db, vid)
        if vrow:
            definition = json.loads(vrow["definition"]) if isinstance(vrow.get("definition"), str) else vrow.get("definition")
    return _ok({"playbook_id": playbook_id, "definition": definition, "version_id": vid})


async def put_definition(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    playbook_id = request.path_params["id"]
    body = await _json_body(request)
    definition = body.get("definition")
    if not isinstance(definition, dict):
        return _error("definition is required", 422)
    # Validate before saving
    validation = playbook_service.validate_definition(db, playbook_id, definition)
    if not validation["valid"]:
        return _error("definition failed validation", 422, code="validation_error",
                      details={"findings": validation["findings"]})
    # Update playbook metadata (definition is stored as a version on publish)
    playbook_service.update_playbook(db, playbook_id, status="draft")
    audit.record_audit(
        db, event="playbook.definition.update", entity_type="playbook", entity_id=playbook_id,
    )
    return _ok({"playbook_id": playbook_id, "valid": True})


async def compile_dsl_endpoint(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    body = await _json_body(request)
    dsl_text = body.get("dsl")
    if not isinstance(dsl_text, str):
        return _error("dsl text is required", 422)
    try:
        defn = compile_dsl(dsl_text)
        # Serialize back to DSL for round-trip check
        dsl_back = dsl_serialize(defn)
        return _ok({
            "definition": {
                "name": defn.name,
                "version": defn.version,
                "inputs": defn.inputs,
                "execution": defn.execution,
                "steps": [
                    {
                        "id": s.id, "tool": s.tool, "type": s.type,
                        "depends_on": s.depends_on, "when": s.when,
                        "parallel": s.parallel, "foreach": s.foreach,
                        "output_mapping": s.output_mapping, "retry": s.retry,
                        "on_failure": s.on_failure, "checkpoint": s.checkpoint,
                        "budget": s.budget, "args": s.args,
                    } for s in defn.steps
                ],
                "raw": defn.raw,
            },
            "dsl_roundtrip": dsl_back,
        })
    except Exception as exc:  # noqa: BLE001
        return _error(f"DSL compilation failed: {exc}", 422, code="compile_error")


async def validate_definition_endpoint(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    playbook_id = request.path_params["id"]
    body = await _json_body(request)
    definition = body.get("definition")
    if not isinstance(definition, dict):
        return _error("definition is required", 422)
    result = playbook_service.validate_definition(db, playbook_id, definition)
    return _ok(result)


# ── Tool endpoints ────────────────────────────────────────────────────────


async def list_tools(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    provider = request.query_params.get("provider")
    visibility = request.query_params.get("visibility")
    enabled = request.query_params.get("enabled")
    enabled_bool = None
    if enabled is not None:
        enabled_bool = enabled.lower() in ("1", "true", "yes")
    rows = service_tools.list_tool_definitions(
        db, provider=provider, visibility=visibility, enabled=enabled_bool
    )
    # Redact secrets in schemas
    for row in rows:
        if row.get("input_schema"):
            try:
                row["input_schema"] = redaction.redact(json.loads(row["input_schema"]) if isinstance(row["input_schema"], str) else row["input_schema"])
            except Exception:  # noqa: BLE001
                pass
    return _ok({"tools": rows})


async def get_tool(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    tool_id = request.path_params["id"]
    row = service_tools.get_tool_definition(db, tool_id)
    if row is None:
        return _error("tool not found", 404)
    return _ok(row)


async def upsert_tool(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    body = await _json_body(request)
    tool_id = body.get("tool_id")
    if not tool_id:
        return _error("tool_id is required", 422)
    try:
        row_id = service_tools.upsert_tool_definition(
            db, tool_id=tool_id, name=body.get("name", tool_id),
            description=body.get("description"), provider=body.get("provider", "native"),
            provider_ref=body.get("provider_ref"),
            input_schema=body.get("input_schema"), output_schema=body.get("output_schema"),
            visibility=body.get("visibility", "agent_callable"),
            enabled=body.get("enabled", True),
            requires_binary=body.get("requires_binary"),
            default_timeout=body.get("default_timeout", 300),
            execution_policy=body.get("execution_policy"),
            scope_required=body.get("scope_required", False),
        )
    except ValueError as exc:
        return _error(str(exc), 422)
    audit.record_audit(
        db, event="tool.upsert", entity_type="tool", entity_id=tool_id,
        details={"visibility": body.get("visibility"), "enabled": body.get("enabled")},
    )
    return _ok({"tool_id": tool_id, "row_id": row_id}, 201)


async def set_tool_visibility_endpoint(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    tool_id = request.path_params["id"]
    body = await _json_body(request)
    visibility = body.get("visibility")
    if visibility not in ("agent_callable", "playbook_selectable", "internal", "hidden"):
        return _error("invalid visibility", 422)
    if visibility == "agent_callable":
        # Require approval for promoting to agent_callable
        if not approvals.is_approved(db, approvals.GATE_VISIBILITY_AGENT_CALLABLE, tool_id):
            return _error(
                approvals.require_approval_for(approvals.GATE_VISIBILITY_AGENT_CALLABLE),
                403, code="approval_required",
            )
    ok = service_tools.set_tool_visibility(db, tool_id, visibility)
    if not ok:
        return _error("tool not found", 404)
    audit.record_audit(
        db, event="tool.visibility", entity_type="tool", entity_id=tool_id,
        details={"visibility": visibility},
    )
    return _ok({"tool_id": tool_id, "visibility": visibility})


# ── Execution endpoints ───────────────────────────────────────────────────


async def list_executions(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    from kali_mcp.studio import service_executions

    status = request.query_params.get("status")
    playbook_id = request.query_params.get("playbook_id")
    try:
        limit = min(int(request.query_params.get("limit", "50")), 500)
        offset = max(int(request.query_params.get("offset", "0")), 0)
    except ValueError:
        return _error("limit/offset must be integers", 422)
    rows = service_executions.list_executions(
        db, status=status, playbook_id=playbook_id, limit=limit, offset=offset
    )
    return _ok({"executions": rows, "limit": limit, "offset": offset})


async def get_execution(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    from kali_mcp.studio import service_executions

    execution_id = request.path_params["id"]
    row = service_executions.get_execution(db, execution_id)
    if row is None:
        return _error("execution not found", 404)
    steps = service_executions.list_steps(db, execution_id)
    artifacts = service_executions.list_artifacts(db, execution_id)
    return _ok({"execution": row, "steps": steps, "artifacts": artifacts})


async def cancel_execution(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    from kali_mcp.studio import service_executions

    execution_id = request.path_params["id"]
    ok = service_executions.cancel_execution(db, execution_id)
    if not ok:
        return _error("execution not found or not cancellable", 404)
    audit.record_audit(
        db, event="execution.cancel", entity_type="execution", entity_id=execution_id,
    )
    return _ok({"execution_id": execution_id, "status": "cancelled"})


async def resume_execution(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    from kali_mcp.studio import service_executions

    execution_id = request.path_params["id"]
    try:
        result = service_executions.resume_execution(db, execution_id)
    except ValueError as exc:
        return _error(str(exc), 422)
    if result is None:
        return _error("execution not found or no checkpoint", 404)
    audit.record_audit(
        db, event="execution.resume", entity_type="execution", entity_id=execution_id,
    )
    return _ok({"execution": result["execution"], "checkpoint": result["checkpoint"]})


# ── Findings endpoints ────────────────────────────────────────────────────


async def query_findings(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    qp = request.query_params
    try:
        limit = min(int(qp.get("limit", "100")), 1000)
        offset = max(int(qp.get("offset", "0")), 0)
    except ValueError:
        return _error("limit/offset must be integers", 422)
    result = db.query_findings(
        target=qp.get("target") or None,
        severity=qp.get("severity") or None,
        validation_status=qp.get("validation_status") or None,
        tool=qp.get("tool") or None,
        asset_id=qp.get("asset_id") or None,
        limit=limit,
        offset=offset,
    )
    return _ok(result)


# ── Connection endpoints ──────────────────────────────────────────────────


async def list_connections(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    from kali_mcp.studio import service_connections

    return _ok({"connections": service_connections.list_connections(db)})


def _connection_transport_from_body(body: dict[str, Any]) -> dict[str, Any]:
    """Extract transport parameters from a connection payload."""
    transport = body.get("transport", "sse")
    if transport not in ("stdio", "sse", "streamable-http"):
        raise ValueError(
            f"invalid transport {transport!r}; expected stdio, sse, or streamable-http"
        )
    command = body.get("command")
    if isinstance(command, str):
        command = command.split()
    args = body.get("args") or []
    if not isinstance(args, list):
        raise ValueError("args must be a list")
    return {
        "transport": transport,
        "endpoint_url": body.get("endpoint_url") or body.get("url"),
        "command": command,
        "args": args,
        "auth_type": body.get("auth_type"),
        "auth_config": body.get("auth_config") or {},
        "timeout": body.get("timeout", 30.0) if transport != "stdio" else 30.0,
    }


def _build_external_client(conn_row: dict[str, Any], timeout: float = 30.0) -> ExternalMCPClient:
    """Build an ExternalMCPClient from a stored connection row."""
    command = conn_row.get("command")
    args = conn_row.get("args") or []
    if isinstance(args, str):
        try:
            args = json.loads(args)
        except (TypeError, ValueError):
            args = []
    cmd_list = command.split() if isinstance(command, str) and command else None
    if cmd_list is not None and args:
        cmd_list = cmd_list + [str(a) for a in args]
    return ExternalMCPClient(
        conn_row.get("transport", "sse"),
        url=conn_row.get("endpoint_url"),
        command=cmd_list,
        timeout=timeout,
    )


async def create_connection(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    from kali_mcp.studio import service_connections

    body = await _json_body(request)
    connection_id = body.get("connection_id") or body.get("id")
    name = body.get("name")
    if not connection_id or not name:
        return _error("connection_id and name are required", 422)
    try:
        transport = _connection_transport_from_body(body)
    except ValueError as exc:
        return _error(str(exc), 422)
    if transport["transport"] in ("sse", "streamable-http") and not transport["endpoint_url"]:
        return _error(f"endpoint_url is required for {transport['transport']} transport", 422)
    if transport["transport"] == "stdio" and not transport["command"]:
        return _error("command is required for stdio transport", 422)
    row = service_connections.upsert_connection(
        db, connection_id, name, transport["transport"],
        description=body.get("description"),
        endpoint_url=transport["endpoint_url"],
        command=transport["command"],
        args=transport["args"],
        auth_type=transport["auth_type"],
        auth_config=transport["auth_config"],
        enabled=bool(body.get("enabled", True)),
    )
    audit.record_audit(
        db, event="connection.create", entity_type="connection", entity_id=connection_id,
        details={"transport": transport["transport"]},
    )
    return _ok(row, 201)


async def get_connection(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    connection_id = request.path_params["id"]
    from kali_mcp.studio import service_connections

    conns = {c["connection_id"]: c for c in service_connections.list_connections(db)}
    row = conns.get(connection_id)
    if row is None:
        return _error("connection not found", 404)
    tools = service_tools.list_tool_definitions(db, provider=connection_id)
    return _ok({"connection": row, "imported_tools": tools})


async def delete_connection(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    from kali_mcp.studio import service_connections

    connection_id = request.path_params["id"]
    ok = service_connections.delete_connection(db, connection_id)
    if not ok:
        return _error("connection not found", 404)
    audit.record_audit(
        db, event="connection.delete", entity_type="connection", entity_id=connection_id,
    )
    return _ok({"connection_id": connection_id, "deleted": True})


async def test_connection_endpoint(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    from kali_mcp.studio import service_connections

    connection_id = request.path_params["id"]
    conns = {c["connection_id"]: c for c in service_connections.list_connections(db)}
    row = conns.get(connection_id)
    if row is None:
        return _error("connection not found", 404)
    try:
        client = _build_external_client(row)
        async with client:
            tools = await client.list_tools()
        ok = True
        error_msg = None
    except Exception as exc:  # noqa: BLE001
        ok = False
        error_msg = str(exc)
        tools = []
    service_connections.set_health(db, connection_id, ok)
    audit.record_audit(
        db, event="connection.test", entity_type="connection", entity_id=connection_id,
        details={"ok": ok},
    )
    return _ok({
        "connection_id": connection_id,
        "ok": ok,
        "health_status": "healthy" if ok else "unreachable",
        "error": error_msg,
        "tool_count": len(tools),
    })


async def discover_connection(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    from kali_mcp.studio import service_connections

    connection_id = request.path_params["id"]
    body = await _json_body(request)
    visibility = body.get("visibility", "internal")
    conns = {c["connection_id"]: c for c in service_connections.list_connections(db)}
    row = conns.get(connection_id)
    if row is None:
        return _error("connection not found", 404)
    client = _build_external_client(row)
    try:
        imported = await service_mcp_tools_import(db, connection_id, client, visibility=visibility)
    except Exception as exc:  # noqa: BLE001
        service_connections.set_health(db, connection_id, False)
        return _error(f"discovery failed: {exc}", 502, code="discover_error")
    service_connections.set_health(db, connection_id, True)
    audit.record_audit(
        db, event="connection.discover", entity_type="connection", entity_id=connection_id,
        details={"imported": len(imported), "visibility": visibility},
    )
    return _ok({"connection_id": connection_id, "imported_tools": imported})


async def service_mcp_tools_import(db, connection_id, client, *, visibility: str = "internal"):
    """Bridge to async import (Phase 3)."""
    from kali_mcp.studio.service_tools import import_external_mcp_tools

    return await import_external_mcp_tools(
        db, connection_id, client, visibility=visibility
    )


# ── Agent endpoints ───────────────────────────────────────────────────────


def _agent_permission_rows(db: Any, profile_id: str) -> list[dict[str, Any]]:
    cur = db.conn.cursor()
    rows = cur.execute(
        """
        SELECT p.tool_id, p.granted, p.granted_at, d.name AS tool_name,
               d.visibility AS tool_visibility, d.enabled AS tool_enabled
        FROM agent_tool_permissions p
        LEFT JOIN tool_definitions d ON d.tool_id = p.tool_id
        WHERE p.profile_id = ?
        ORDER BY p.tool_id
        """,
        (profile_id,),
    ).fetchall()
    return [dict(r) for r in rows]


def _agent_assignment_rows(db: Any, profile_id: str) -> list[dict[str, Any]]:
    cur = db.conn.cursor()
    rows = cur.execute(
        """
        SELECT a.playbook_id, a.granted, a.granted_at, pb.name AS playbook_name
        FROM agent_playbook_assignments a
        LEFT JOIN playbooks pb ON pb.playbook_id = a.playbook_id
        WHERE a.profile_id = ?
        ORDER BY a.playbook_id
        """,
        (profile_id,),
    ).fetchall()
    return [dict(r) for r in rows]


async def list_agents(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    rows = service_agents.list_profiles(db)
    for row in rows:
        row["tool_grants"] = sum(
            1 for p in _agent_permission_rows(db, row["profile_id"]) if p["granted"]
        )
        row["playbook_grants"] = sum(
            1 for a in _agent_assignment_rows(db, row["profile_id"]) if a["granted"]
        )
    return _ok({"agents": rows})


async def create_agent(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    body = await _json_body(request)
    profile_id = body.get("profile_id") or body.get("id")
    name = body.get("name")
    if not profile_id or not name:
        return _error("profile_id and name are required", 422)
    try:
        row = service_agents.create_profile(
            db, profile_id, name,
            description=body.get("description"),
            default_visibility=body.get("default_visibility", "internal"),
            max_parallel_operations=int(body.get("max_parallel_operations", 4)),
            max_execution_seconds=int(body.get("max_execution_seconds", 900)),
        )
    except (ValueError, TypeError) as exc:
        return _error(str(exc), 422)
    audit.record_audit(
        db, event="agent.create", entity_type="agent_profile", entity_id=profile_id,
    )
    return _ok(row, 201)


async def get_agent(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    profile_id = request.path_params["id"]
    row = service_agents.get_profile(db, profile_id)
    if row is None:
        return _error("agent profile not found", 404)
    stats = service_agents.effective_catalog(db, profile_id)
    return _ok({
        "agent": row,
        "permissions": _agent_permission_rows(db, profile_id),
        "assignments": _agent_assignment_rows(db, profile_id),
        "effective_catalog": stats,
    })


async def update_agent(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    profile_id = request.path_params["id"]
    body = await _json_body(request)
    allowed_fields = (
        "name", "description", "default_visibility",
        "max_parallel_operations", "max_execution_seconds",
    )
    fields = {k: body[k] for k in allowed_fields if k in body}
    if not fields:
        return _error("no updatable fields supplied", 422)
    try:
        ok = service_agents.update_profile(db, profile_id, **fields)
    except (ValueError, TypeError) as exc:
        return _error(str(exc), 422)
    if not ok:
        return _error("agent profile not found", 404)
    audit.record_audit(
        db, event="agent.update", entity_type="agent_profile", entity_id=profile_id,
        details={k: str(v) for k, v in fields.items()},
    )
    return _ok({"profile_id": profile_id})


async def delete_agent(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    profile_id = request.path_params["id"]
    ok = service_agents.delete_profile(db, profile_id)
    if not ok:
        return _error("agent profile not found", 404)
    audit.record_audit(
        db, event="agent.delete", entity_type="agent_profile", entity_id=profile_id,
    )
    return _ok({"profile_id": profile_id, "deleted": True})


async def assign_agent_tool(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    profile_id = request.path_params["id"]
    tool_id = request.path_params["tool_id"]
    if service_agents.get_profile(db, profile_id) is None:
        return _error("agent profile not found", 404)
    body = await _json_body(request)
    granted = bool(body.get("granted", True))
    service_agents.grant_tool(db, profile_id, tool_id, granted)
    audit.record_audit(
        db, event="agent.tool.grant", entity_type="agent_profile", entity_id=profile_id,
        details={"tool_id": tool_id, "granted": granted},
    )
    return _ok({"profile_id": profile_id, "tool_id": tool_id, "granted": granted})


async def unassign_agent_tool(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    profile_id = request.path_params["id"]
    tool_id = request.path_params["tool_id"]
    service_agents.revoke_tool(db, profile_id, tool_id)
    audit.record_audit(
        db, event="agent.tool.revoke", entity_type="agent_profile", entity_id=profile_id,
        details={"tool_id": tool_id},
    )
    return _ok({"profile_id": profile_id, "tool_id": tool_id, "granted": False})


async def assign_agent_playbook(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    profile_id = request.path_params["id"]
    playbook_id = request.path_params["playbook_id"]
    if service_agents.get_profile(db, profile_id) is None:
        return _error("agent profile not found", 404)
    body = await _json_body(request)
    granted = bool(body.get("granted", True))
    service_agents.assign_playbook(db, profile_id, playbook_id, granted)
    audit.record_audit(
        db, event="agent.playbook.assign", entity_type="agent_profile", entity_id=profile_id,
        details={"playbook_id": playbook_id, "granted": granted},
    )
    return _ok({"profile_id": profile_id, "playbook_id": playbook_id, "granted": granted})


async def unassign_agent_playbook(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    profile_id = request.path_params["id"]
    playbook_id = request.path_params["playbook_id"]
    service_agents.unassign_playbook(db, profile_id, playbook_id)
    audit.record_audit(
        db, event="agent.playbook.unassign", entity_type="agent_profile", entity_id=profile_id,
        details={"playbook_id": playbook_id},
    )
    return _ok({"profile_id": profile_id, "playbook_id": playbook_id})


async def agent_catalog(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    profile_id = request.path_params["id"]
    if service_agents.get_profile(db, profile_id) is None:
        return _error("agent profile not found", 404)
    return _ok(service_agents.effective_catalog(db, profile_id))


# ── Overview / Scope / Server endpoints ───────────────────────────────────


async def overview(request: Request) -> JSONResponse:
    db = _db()
    if db is None:
        return _error("database unavailable", 500)
    from kali_mcp.studio import service_executions

    cur = db.conn.cursor()

    def _count(sql: str, params: tuple = ()) -> int:
        return cur.execute(sql, params).fetchone()[0]

    playbook_counts: dict[str, int] = {}
    for row in cur.execute(
        "SELECT status, COUNT(*) AS n FROM playbooks GROUP BY status"
    ):
        playbook_counts[row["status"] or "draft"] = row["n"]
    execution_counts: dict[str, int] = {}
    for row in cur.execute(
        "SELECT status, COUNT(*) AS n FROM workflow_executions GROUP BY status"
    ):
        execution_counts[row["status"] or "unknown"] = row["n"]
    tool_counts: dict[str, int] = {}
    for row in cur.execute(
        "SELECT visibility, COUNT(*) AS n FROM tool_definitions GROUP BY visibility"
    ):
        tool_counts[row["visibility"] or "unknown"] = row["n"]
    finding_counts: dict[str, int] = {}
    for row in cur.execute(
        "SELECT severity, COUNT(*) AS n FROM findings GROUP BY severity"
    ):
        finding_counts[row["severity"] or "unknown"] = row["n"]

    recent = service_executions.list_executions(db, limit=5)
    recent_findings = db.query_findings(limit=5)["findings"]
    overview_data = {
        "playbooks": {
            "total": sum(playbook_counts.values()),
            "by_status": playbook_counts,
        },
        "executions": {
            "total": sum(execution_counts.values()),
            "by_status": execution_counts,
        },
        "tools": {
            "total": sum(tool_counts.values()),
            "by_visibility": tool_counts,
        },
        "findings": {
            "total": sum(finding_counts.values()),
            "by_severity": finding_counts,
        },
        "connections": {
            "total": _count("SELECT COUNT(*) FROM mcp_connections"),
            "healthy": _count(
                "SELECT COUNT(*) FROM mcp_connections WHERE health_status = 'healthy'"
            ),
        },
        "agents": {"total": _count("SELECT COUNT(*) FROM agent_profiles")},
        "recent_executions": recent,
        "recent_findings": recent_findings,
    }
    return _ok(overview_data)


async def get_scope(request: Request) -> JSONResponse:
    from kali_mcp.scope import load_scope

    scope = load_scope()
    return _ok({
        "allowed_targets": list(scope.allowed_targets),
        "excluded_targets": list(scope.excluded_targets),
        "allowed_operations": list(scope.allowed_operations),
        "expiration": scope.expiration,
        "policy": scope.policy,
        "is_empty": scope.is_empty(),
        "is_expired": scope.is_expired(),
    })


async def get_server_info(request: Request) -> JSONResponse:
    from kali_mcp.config import config
    return _ok({
        "server_name": config.server_name,
        "server_version": config.server_version,
        "host": config.host,
        "port": config.port,
        "transport": config.transport,
        "debug": config.debug,
        "auth_enabled": bool(config.api_token) and not config.insecure,
        "default_timeout": config.default_timeout,
        "max_timeout": config.max_timeout,
        "max_concurrent": config.max_concurrent,
    })


# ── Mounting ───────────────────────────────────────────────────────────────


routes = [
    # Playbooks
    Route("/api/playbooks", list_playbooks, methods=["GET"]),
    Route("/api/playbooks", create_playbook, methods=["POST"]),
    Route("/api/playbooks/{id}", get_playbook, methods=["GET"]),
    Route("/api/playbooks/{id}", update_playbook, methods=["PUT"]),
    Route("/api/playbooks/{id}", delete_playbook, methods=["DELETE"]),
    Route("/api/playbooks/{id}/validate", validate_playbook_endpoint, methods=["POST"]),
    Route("/api/playbooks/{id}/preview", preview_playbook_endpoint, methods=["POST"]),
    Route("/api/playbooks/{id}/test", test_playbook_endpoint, methods=["POST"]),
    Route("/api/playbooks/{id}/publish", publish_playbook, methods=["POST"]),
    Route("/api/playbooks/{id}/versions", list_versions, methods=["GET"]),
    Route("/api/playbooks/{id}/rollback", rollback_playbook, methods=["POST"]),
    Route("/api/playbooks/{id}/export", export_playbook_endpoint, methods=["GET"]),
    Route("/api/playbooks/import", import_playbook_endpoint, methods=["POST"]),
    # Definition (DSL / visual editor round-trip)
    Route("/api/playbooks/{id}/definition", get_definition, methods=["GET"]),
    Route("/api/playbooks/{id}/definition", put_definition, methods=["PUT"]),
    Route("/api/playbooks/{id}/compile", compile_dsl_endpoint, methods=["POST"]),
    Route("/api/playbooks/{id}/validate-definition", validate_definition_endpoint, methods=["POST"]),
    # Tools
    Route("/api/tools", list_tools, methods=["GET"]),
    Route("/api/tools/{id}", get_tool, methods=["GET"]),
    Route("/api/tools", upsert_tool, methods=["POST"]),
    Route("/api/tools/{id}", upsert_tool, methods=["PUT"]),
    Route("/api/tools/{id}/visibility", set_tool_visibility_endpoint, methods=["PUT"]),
    # Executions
    Route("/api/executions", list_executions, methods=["GET"]),
    Route("/api/executions/{id}", get_execution, methods=["GET"]),
    Route("/api/executions/{id}/cancel", cancel_execution, methods=["POST"]),
    Route("/api/executions/{id}/resume", resume_execution, methods=["POST"]),
    # Findings
    Route("/api/findings", query_findings, methods=["GET"]),
    # connections (must precede the {id} route)
    Route("/api/connections", list_connections, methods=["GET"]),
    Route("/api/connections", create_connection, methods=["POST"]),
    Route("/api/connections/{id}", get_connection, methods=["GET"]),
    Route("/api/connections/{id}", delete_connection, methods=["DELETE"]),
    Route("/api/connections/{id}/test", test_connection_endpoint, methods=["POST"]),
    Route("/api/connections/{id}/discover", discover_connection, methods=["POST"]),
    # Agents
    Route("/api/agents", list_agents, methods=["GET"]),
    Route("/api/agents", create_agent, methods=["POST"]),
    Route("/api/agents/{id}", get_agent, methods=["GET"]),
    Route("/api/agents/{id}", update_agent, methods=["PUT"]),
    Route("/api/agents/{id}", delete_agent, methods=["DELETE"]),
    Route("/api/agents/{id}/tools/{tool_id}", assign_agent_tool, methods=["PUT"]),
    Route("/api/agents/{id}/tools/{tool_id}", unassign_agent_tool, methods=["DELETE"]),
    Route(
        "/api/agents/{id}/playbooks/{playbook_id}",
        assign_agent_playbook, methods=["PUT"],
    ),
    Route(
        "/api/agents/{id}/playbooks/{playbook_id}",
        unassign_agent_playbook, methods=["DELETE"],
    ),
    Route("/api/agents/{id}/catalog", agent_catalog, methods=["GET"]),
    # Overview / Scope / Server
    Route("/api/overview", overview, methods=["GET"]),
    Route("/api/scope", get_scope, methods=["GET"]),
    Route("/api/server", get_server_info, methods=["GET"]),
]


def mount_studio_routes(app: Any) -> None:
    """Mount Studio REST routes on the Starlette app.

    Called from ``src/kali_mcp/server.py`` main(). Routes are inserted at the
    front so they take precedence over MCP catch-all routes.
    """
    from starlette.routing import Route as StarletteRoute

    studio_routes = [
        StarletteRoute(r.path, r.endpoint, methods=list(r.methods or []))
        for r in routes
    ]
    for route in reversed(studio_routes):
        app.routes.insert(0, route)
    logger.info("Mounted %d Studio REST routes", len(studio_routes))


__all__ = ["routes", "mount_studio_routes"]
