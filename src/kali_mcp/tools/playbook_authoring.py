"""Agent-facing playbook authoring tools (draft → validate → publish).

These MCP tools let AI agents author reusable playbooks into the Studio
catalog — previously human-only through the Studio UI/API/CLI:

- ``playbook_create``   create a draft row (invisible to playbook_run)
- ``playbook_validate`` validate a definition (optionally with the stricter
                        publish-time rules)
- ``playbook_publish``  publish an immutable version (validation first)

They wrap ``kali_mcp.studio.playbook_service`` and run through the same
SQLite DB the Studio UI uses, so drafts/published versions are visible in
both places. The DSL itself is documented in
``kali_mcp.playbook_dsl.PLAYBOOK_DSL_GUIDE`` (also exposed as the
``kali://playbook/dsl`` resource and the ``playbook_authoring`` prompt).
"""

from __future__ import annotations

import json
from typing import Any

from kali_mcp.db import manager as db_manager
from kali_mcp.models import ExecutionResult, ToolError, utc_now_iso
from kali_mcp.responses import error_response, success_response
from kali_mcp.tools.base import BaseTool


def _make_result(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Build an MCP success response carrying ``payload`` as its stdout JSON."""
    result = ExecutionResult(
        tool=tool_name,
        command=tool_name,
        stdout=json.dumps(payload, indent=2),
        stderr="",
        exit_code=0,
        success=True,
        timed_out=False,
        duration=0.0,
        start_time=utc_now_iso(),
        end_time=utc_now_iso(),
    )
    return success_response(result)


def _make_error(tool_name: str, error: str, details: str | None = None) -> dict[str, Any]:
    """Build an MCP error response for the authoring tools."""
    return error_response(ToolError(error=f"{tool_name}: {error}", details=details))


def _validate_definition(playbook_id: str, definition: dict[str, Any], for_publish: bool) -> dict[str, Any]:
    """Run studio playbook validation; returns ``{"valid": ..., "findings": [...]}``."""
    from kali_mcp.studio import playbook_service

    db = db_manager.get_db()
    if db is None:
        return {
            "valid": False,
            "findings": [
                {
                    "severity": "error",
                    "step_id": None,
                    "field": "definition",
                    "message": "database unavailable — cannot resolve tool/module catalogs",
                }
            ],
        }
    return playbook_service.validate_definition(
        db, playbook_id, definition, for_publish=for_publish
    )


def _findings_text(findings: list[dict[str, Any]]) -> str:
    """Render validation findings as a compact readable list."""
    lines = []
    for f in findings:
        lines.append(
            f"[{f.get('severity')}] {f.get('step_id') or '-'}:"
            f"{f.get('field') or '-'} {f.get('message')}"
        )
    return "\n".join(lines)


class PlaybookCreateTool(BaseTool):
    """Create a draft playbook row in the Studio catalog."""

    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "playbook_create"

    @property
    def description(self) -> str:
        return (
            "Create a DRAFT playbook in the Studio catalog so it can later be\n"
            "published and run via playbook_run. Drafts are invisible to\n"
            "playbook_run until published. Workflow:\n"
            "  1. playbook_create (playbook_id, name)\n"
            "  2. playbook_validate (definition) — fix all error findings\n"
            "  3. playbook_publish (version, definition)\n"
            "The DSL is documented in the kali://playbook/dsl resource and the\n"
            "playbook_authoring prompt."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "playbook_id": {
                    "type": "string",
                    "description": "Unique catalog id, e.g. 'quick_http_probe'",
                },
                "name": {
                    "type": "string",
                    "description": "Human-readable name, e.g. 'Quick HTTP Probe'",
                },
                "description": {
                    "type": "string",
                    "description": "What the playbook does (optional)",
                },
                "category": {
                    "type": "string",
                    "description": "Catalog category, e.g. recon/webapp/network (optional)",
                },
                "author": {
                    "type": "string",
                    "description": "Author name (optional; defaults to 'agent')",
                },
            },
            "required": ["playbook_id", "name"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        for field in ("playbook_id", "name"):
            value = arguments.get(field)
            if not isinstance(value, str) or not value.strip():
                raise ValueError(f"'{field}' is required and must be a non-empty string")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return [self.name]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from kali_mcp.studio import playbook_service

        playbook_id = arguments["playbook_id"].strip()
        name = arguments["name"].strip()

        db = db_manager.get_db()
        if db is None:
            return _make_error(self.name, "database unavailable — cannot access the Studio catalog")
        existing = playbook_service.get_playbook(db, playbook_id)
        if existing is not None:
            return _make_error(
                self.name,
                f"playbook '{playbook_id}' already exists",
                details=(
                    f"status: {existing.get('status')!r}. Choose a different "
                    "playbook_id, or publish a new version via playbook_publish."
                ),
            )
        try:
            row = playbook_service.create_playbook(
                db,
                playbook_id=playbook_id,
                name=name,
                description=arguments.get("description"),
                category=arguments.get("category"),
                author=arguments.get("author") or "agent",
            )
        except ValueError as exc:
            return _make_error(self.name, str(exc))

        return _make_result(
            self.name,
            {
                "created": True,
                "playbook_id": row.get("playbook_id", playbook_id),
                "name": row.get("name", name),
                "status": row.get("status", "draft"),
                "next": "Write the DSL definition, validate it with playbook_validate, then publish with playbook_publish.",
            },
        )


class PlaybookValidateTool(BaseTool):
    """Validate a playbook definition against the workflow DSL rules."""

    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "playbook_validate"

    @property
    def description(self) -> str:
        return (
            "Validate a playbook definition (the DSL from kali://playbook/dsl)\n"
            "against the workflow engine rules: step types, depends_on refs,\n"
            "when-condition grammar, required fields, etc. returns\n"
            "{valid, findings[]}. Use for_publish: true for the stricter\n"
            "publish-time checks (every tool must exist in the server catalog;\n"
            "every custom/module step must declare a module). Always run this\n"
            "before playbook_publish — publishing re-validates and fails on\n"
            "errors."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "playbook_id": {
                    "type": "string",
                    "description": "Catalog id the definition will belong to (used for validation context)",
                },
                "definition": {
                    "type": "object",
                    "description": (
                        "Playbook definition dict: {name, version, inputs, "
                        "execution, steps}. YAML string is also accepted."
                    ),
                },
                "for_publish": {
                    "type": "boolean",
                    "description": "Apply stricter publish-time validation (default true)",
                    "default": True,
                },
            },
            "required": ["playbook_id", "definition"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        playbook_id = arguments.get("playbook_id")
        if not isinstance(playbook_id, str) or not playbook_id.strip():
            raise ValueError("'playbook_id' is required and must be a non-empty string")
        definition = arguments.get("definition")
        if definition is None:
            raise ValueError("'definition' is required (dict or object)")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return [self.name]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        definition = arguments["definition"]
        if not isinstance(definition, dict):
            # Accept a JSON/YAML string for convenience.
            try:
                import yaml

                definition = yaml.safe_load(definition)
            except Exception as exc:  # noqa: BLE001
                return _make_error(self.name, "definition must be an object", details=str(exc))
            if not isinstance(definition, dict):
                return _make_error(self.name, "definition must be an object")

        playbook_id = arguments["playbook_id"].strip()
        for_publish = bool(arguments.get("for_publish", True))

        validation = _validate_definition(
            playbook_id, dict(definition), for_publish=for_publish
        )

        payload: dict[str, Any] = {
            "valid": validation["valid"],
            "for_publish": for_publish,
            "findings": validation["findings"],
            "next": (
                "publish with playbook_publish"
                if validation["valid"]
                else "fix every severity=error finding, then re-validate"
            ),
        }
        if not validation["valid"]:
            payload["readable"] = _findings_text(validation["findings"])
        return _make_result(self.name, payload)


class PlaybookPublishTool(BaseTool):
    """Publish an immutable version of a playbook into the Studio catalog."""

    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "playbook_publish"

    @property
    def description(self) -> str:
        return (
            "Publish an immutable playbook version to the Studio catalog,\n"
            "making it runnable via playbook_run. Runs publish-time validation\n"
            "first and refuses to publish invalid definitions (returns the\n"
            "findings instead). Bump the version when re-publishing after\n"
            "changes — published versions are never mutated."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "playbook_id": {
                    "type": "string",
                    "description": "Catalog id (must exist — create drafts with playbook_create)",
                },
                "version": {
                    "type": "string",
                    "description": "Semantic version string, e.g. '1.0'",
                },
                "definition": {
                    "type": "object",
                    "description": "Playbook definition {name, version, inputs, execution, steps}",
                },
                "notes": {
                    "type": "string",
                    "description": "Release notes for this version (optional)",
                },
            },
            "required": ["playbook_id", "version", "definition"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        playbook_id = arguments.get("playbook_id")
        if not isinstance(playbook_id, str) or not playbook_id.strip():
            raise ValueError("'playbook_id' is required and must be a non-empty string")
        version = arguments.get("version")
        if not isinstance(version, str) or not version.strip():
            raise ValueError("'version' is required and must be a non-empty string")
        if arguments.get("definition") is None:
            raise ValueError("'definition' is required (dict or object)")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return [self.name]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from kali_mcp.studio import playbook_service

        playbook_id = arguments["playbook_id"].strip()
        version = arguments["version"].strip()
        definition = arguments["definition"]
        if not isinstance(definition, dict):
            try:
                import yaml

                definition = yaml.safe_load(definition)
            except Exception as exc:  # noqa: BLE001
                return _make_error(self.name, "definition must be an object", details=str(exc))
            if not isinstance(definition, dict):
                return _make_error(self.name, "definition must be an object")

        db = db_manager.get_db()
        if db is None:
            return _make_error(self.name, "database unavailable — cannot access the Studio catalog")
        row = playbook_service.get_playbook(db, playbook_id)
        if row is None:
            return _make_error(
                self.name,
                f"playbook '{playbook_id}' does not exist",
                details="Create the draft first with playbook_create.",
            )

        validation = playbook_service.validate_definition(
            db, playbook_id, definition, for_publish=True
        )
        if not validation["valid"]:
            return _make_result(
                self.name,
                {
                    "published": False,
                    "valid": False,
                    "findings": validation["findings"],
                    "readable": _findings_text(validation["findings"]),
                    "next": "fix every error finding, re-validate with playbook_validate, then publish again",
                },
            )

        try:
            version_id = playbook_service.publish_version(
                db,
                playbook_id=playbook_id,
                version=version,
                definition=definition,
                notes=arguments.get("notes"),
                published_by="agent",
            )
        except ValueError as exc:
            return _make_error(self.name, str(exc))

        return _make_result(
            self.name,
            {
                "published": True,
                "playbook_id": playbook_id,
                "version": version,
                "version_id": version_id,
                "next": f"run it with playbook_run (playbook: {playbook_id}) against a target in scope",
            },
        )
