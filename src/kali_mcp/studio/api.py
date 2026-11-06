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
from kali_mcp.studio import approvals, audit, playbook_service, redaction, service_tools
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
