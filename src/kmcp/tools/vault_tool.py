"""Vault MCP tools — inter-agent knowledge sharing via SQLite.

Agents and subagents use these tools to store, read, query, and delete
rows (findings, credentials, evidence, notes, handoff/task payloads) so
that work can be passed between agents.

These tools are pure Python — no subprocess. Storage is SQLite
(VAULT_ROOT/vault.sqlite) via utils/vault.py.
"""

from __future__ import annotations

import json
from typing import Any

from kmcp.models import ExecutionResult, ToolError, utc_now_iso
from kmcp.responses import error_response, success_response
from kmcp.tools.base import BaseTool
from kmcp.validation import validate_required


def _make_result(tool_name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Build an MCP success response carrying `payload` as its stdout JSON."""
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


def _error(tool_name: str, error: str, details: str = "") -> dict[str, Any]:
    return error_response(ToolError(error=error, details=details))


def _parse_content(value: Any) -> Any:
    """Store plain text verbatim (key=value fields); keep structured data as-is."""
    if isinstance(value, str):
        if not value.strip():
            raise ValueError("content must not be empty")
        return value  # verbatim key=value fields — never wrapped in JSON
    if value is None:
        raise ValueError("content must not be null")
    return value


class VaultWriteTool(BaseTool):
    """Store data in the vault for other agents to consume."""

    _skip_central_persist = True  # vault tools ARE the persistence layer

    @property
    def name(self) -> str:
        return "vault_write"

    @property
    def description(self) -> str:
        return (
            "Store one row in the shared vault so other agents (or "
            "subagents) can discover and read it. Rows are keyed by "
            "(category, name) and overwritten on re-write — use unique row "
            "keys like vuln:VULN-001, ev:<vuln_id>, poc:<vuln_id>, cred:<id>, "
            "sys:<host>, path:AP-001, repo:<org>/<name>, or "
            "task:<stage>/status:<stage> for orchestration. Content is the "
            "row's plain key=value fields (verbatim text), a JSON object, or "
            "a JSON array — all round-trip exactly on read. Tag rows with "
            "agent:x, phase:n, severity:critical, superseded, etc."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Row category — the phase-output area, e.g. "
                    "scope, vulnerabilities, evidence, credentials, notes, "
                    "handoff. May include subpaths (e.g. findings/10.0.0.1).",
                },
                "name": {
                    "type": "string",
                    "description": "Unique row key within the category, e.g. "
                    "vuln:VULN-001, task:2, ssh_creds_stage2",
                },
                "content": {
                    "type": "string",
                    "description": "The row's content: plain key=value fields "
                    "(verbatim text), or a JSON string (object/array).",
                },
                "target": {
                    "type": "string",
                    "description": "Optional asset/host/domain the row belongs "
                    "to, for later filtering.",
                },
                "tool": {
                    "type": "string",
                    "description": "Optional producing tool name.",
                },
                "tags": {
                    "type": ["string", "array"],
                    "description": "Space/comma-separated tags for search, "
                    "e.g. 'agent:recon phase:2 severity:critical superseded'. "
                    "Pass an array of strings and it will be joined with commas.",
                },
            },
            "required": ["category", "name", "content"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "category", "name")
        if arguments.get("content") is None:
            raise ValueError("Missing required parameter: content")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["vault_write"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from kmcp.utils.vault import vault_write

        try:
            content = _parse_content(arguments.get("content"))
            tags = arguments.get("tags", "")
            if isinstance(tags, list):
                tags = ",".join(str(t) for t in tags)
            path = vault_write(
                arguments["category"],
                arguments["name"],
                content,
                target=arguments.get("target", ""),
                tool=arguments.get("tool", self.name),
                tags=tags,
            )
        except ValueError as e:
            return _error(self.name, "Validation error", str(e))
        except Exception as e:  # noqa: BLE001 — never crash the server
            return _error(self.name, "Vault write failed", str(e))
        return _make_result(
            self.name,
            {
                "status": "stored",
                "category": arguments["category"],
                "name": arguments["name"],
                "path": path,
                "hint": "Other agents can read it with vault_read "
                f"(category={arguments['category']!r}, "
                f"name={arguments['name']!r}) or find it with vault_query.",
            },
        )


class VaultReadTool(BaseTool):
    """Read a vault row by category + name (exact pickup)."""

    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "vault_read"

    @property
    def description(self) -> str:
        return (
            "Read a stored vault row by category and name. Use vault_query "
            "first if you don't know the exact name. JSON rows come back "
            "parsed; plain key=value rows are returned verbatim in the "
            "'content' field. Rows larger than max_bytes (default 1MB) are "
            "truncated with a 'truncated' flag and the full mirror path — "
            "page through the rest with file_read(path, offset)."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Row category, e.g. vulnerabilities, handoff",
                },
                "name": {
                    "type": "string",
                    "description": "Row key within the category",
                },
                "max_bytes": {
                    "type": "integer",
                    "description": "Maximum bytes of content to return "
                    "(default 1MB). Oversized rows are truncated — the "
                    "response carries 'truncated': true, 'total_bytes', and "
                    "the mirror 'path' for paging via file_read.",
                    "default": 1048576,
                },
            },
            "required": ["category", "name"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "category", "name")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["vault_read"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from kmcp.utils.vault import vault_path, vault_read

        try:
            raw = vault_read(arguments["category"], arguments["name"])
        except Exception as e:  # noqa: BLE001
            return _error(self.name, "Vault read failed", str(e))
        if raw == json.dumps({"error": "not found"}):
            return _error(
                self.name,
                "Entry not found",
                f"no vault row {arguments['category']}/{arguments['name']} — "
                "use vault_query to discover names",
            )

        max_bytes = arguments.get("max_bytes", 1048576)
        total = len(raw.encode("utf-8"))
        if total > max_bytes:
            # Oversized row — return a truncated view + paging pointers
            return _make_result(
                self.name,
                {
                    "category": arguments["category"],
                    "name": arguments["name"],
                    "content": raw[:max_bytes],
                    "truncated": True,
                    "total_bytes": total,
                    "returned_bytes": max_bytes,
                    "path": vault_path(arguments["category"], arguments["name"]),
                    "hint": "Full row continues — page through it with "
                    f"file_read(path=<path above>, offset={max_bytes}) or "
                    "raise max_bytes on the next vault_read.",
                },
            )

        try:
            payload = json.loads(raw)  # machine-generated rows come back as JSON
        except (json.JSONDecodeError, TypeError):
            # key=value field rows are returned verbatim, wrapped for transport
            payload = {
                "category": arguments["category"],
                "name": arguments["name"],
                "content": raw,
            }
        return _make_result(self.name, payload)


class VaultQueryTool(BaseTool):
    """Search vault rows by category / target / tool / free text."""

    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "vault_query"

    @property
    def description(self) -> str:
        return (
            "Search the shared vault for rows another agent stored. "
            "Filter by one or more categories (comma-separated), target, or "
            "tool; or free-text search across names, tags, and content. "
            "Returns row metadata (read full rows with vault_read). "
            "Search is literal substring matching, not tokenized: JSON rows "
            'store JSON text (e.g. \'"level": "info"\') and key=value rows '
            "store key=value text — search for distinctive strings "
            "(hostnames, CVE IDs, ports, markers) rather than assuming a "
            "format."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Category filter — one category or "
                    "comma-separated several, e.g. 'web, active_directory, "
                    "source_code' (optional)",
                },
                "target": {
                    "type": "string",
                    "description": "Exact target filter (optional)",
                },
                "tool": {
                    "type": "string",
                    "description": "Exact tool filter (optional)",
                },
                "search": {
                    "type": "string",
                    "description": "Case-insensitive substring search over "
                    "name, tags, and content (optional)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows to return (default 100)",
                    "default": 100,
                },
            },
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        pass

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["vault_query"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from kmcp.utils.vault import vault_query

        try:
            payload = vault_query(
                category=arguments.get("category"),
                target=arguments.get("target"),
                tool=arguments.get("tool"),
                search=arguments.get("search"),
                limit=arguments.get("limit", 100),
            )
        except Exception as e:  # noqa: BLE001
            return _error(self.name, "Vault query failed", str(e))
        payload["hint"] = "Read a full row with vault_read(category=…, name=…)."
        return _make_result(self.name, payload)


class VaultListTool(BaseTool):
    """List vault rows, optionally per category."""

    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "vault_list"

    @property
    def description(self) -> str:
        return (
            "List vault rows (metadata only, newest-created first). Omit "
            "category to list across all categories. Use vault_query for "
            "filtered/full-text search instead."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "List only this category (optional)",
                },
                "limit": {
                    "type": "integer",
                    "description": "Max rows to return (default 200)",
                    "default": 200,
                },
                "offset": {
                    "type": "integer",
                    "description": "Skip this many rows (default 0)",
                    "default": 0,
                },
            },
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        pass

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["vault_list"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from kmcp.utils.vault import vault_list

        try:
            payload = vault_list(
                category=arguments.get("category"),
                limit=arguments.get("limit", 200),
                offset=arguments.get("offset", 0),
            )
        except Exception as e:  # noqa: BLE001
            return _error(self.name, "Vault list failed", str(e))
        return _make_result(self.name, payload)


class VaultDeleteTool(BaseTool):
    """Delete a vault row (orchestrator-only cleanup)."""

    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "vault_delete"

    @property
    def description(self) -> str:
        return (
            "Delete a vault row by category and name (removes it from the "
            "SQLite store and the JSON mirror). Reserved for the "
            "orchestrator — used to clean up stale task:/status: rows and "
            "superseded run rows; regular agents should not delete shared "
            "rows."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "category": {
                    "type": "string",
                    "description": "Row category",
                },
                "name": {
                    "type": "string",
                    "description": "Row key within the category",
                },
            },
            "required": ["category", "name"],
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        validate_required(arguments, "category", "name")

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["vault_delete"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from kmcp.utils.vault import vault_delete

        try:
            payload = vault_delete(arguments["category"], arguments["name"])
        except Exception as e:  # noqa: BLE001
            return _error(self.name, "Vault delete failed", str(e))
        if not payload.get("deleted"):
            return _error(
                self.name,
                "Entry not found",
                f"nothing deleted for {arguments['category']}/{arguments['name']}",
            )
        return _make_result(self.name, {**payload, "status": "deleted"})


class VaultStatsTool(BaseTool):
    """Vault summary statistics."""

    _skip_central_persist = True

    @property
    def name(self) -> str:
        return "vault_stats"

    @property
    def description(self) -> str:
        return (
            "Vault summary: total rows, per-category counts (GROUP BY "
            "category), per-tool counts, and storage size. Use to orient "
            "before querying — e.g. verify your categories are populated "
            "before finishing a stage."
        )

    def input_schema(self) -> dict[str, Any]:
        return {
            "type": "object",
            "properties": {
                "include_index": {
                    "type": "boolean",
                    "description": "Also include the full row index in the "
                    "response (default false)",
                    "default": False,
                },
            },
        }

    def validate(self, arguments: dict[str, Any]) -> None:
        pass

    def build_command(self, arguments: dict[str, Any]) -> list[str]:
        return ["vault_stats"]

    async def execute(self, arguments: dict[str, Any]) -> dict[str, Any]:
        from kmcp.utils.vault import get_index, vault_stats

        try:
            payload = vault_stats()
            if arguments.get("include_index"):
                payload["index"] = get_index()
        except Exception as e:  # noqa: BLE001
            return _error(self.name, "Vault stats failed", str(e))
        return _make_result(self.name, payload)
