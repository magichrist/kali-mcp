"""MCP resources — server metadata exposed to clients.

Resources (URIs, not tools) give the MCP client a browseable view of:
  - live server configuration
  - registered tool inventory
  - health status
  - execution/server logs (JSON lines)
  - generated artifacts
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from config import config

logger = logging.getLogger("kali_mcp.resources")

RESOURCE_NAMESPACE = "kali"

# Templates registered for template listing (uriTemplate → {name, description})
TEMPLATES: dict[str, dict[str, str]] = {
    "kali://artifacts/{artifact}": {
        "name": "kali_artifact",
        "description": "Read a generated artifact from the artifact directory",
    },
}


def _config_resource() -> str:
    """Live server configuration as JSON."""
    cfg = {
        "server_name": config.server_name,
        "server_version": config.server_version,
        "host": config.host,
        "port": config.port,
        "transport": config.transport,
        "default_timeout": config.default_timeout,
        "max_timeout": config.max_timeout,
        "max_concurrent": config.max_concurrent,
        "log_dir": str(config.log_dir),
        "artifact_dir": str(config.artifact_dir),
        "debug": config.debug,
        "rate_limit_per_minute": config.rate_limit_per_minute,
        "auth_enabled": bool(config.api_token),
    }
    return json.dumps(cfg, indent=2)


def _tools_resource() -> str:
    """Registered tool inventory as JSON."""
    from registry import registry

    tools = []
    for tool in registry.list_all():
        tools.append(
            {
                "name": tool.name,
                "description": tool.description,
                "schema": tool.input_schema(),
            }
        )
    return json.dumps({"count": len(tools), "tools": tools}, indent=2)


def _make_health_resource(health):
    """Build a resource reader returning live health status as JSON."""

    def _read() -> str:
        return json.dumps(health.get_status(), indent=2)

    return _read


def _tail_file(path: Path, max_lines: int = 2000) -> str:
    """Return the tail of a JSON-lines log file as pretty JSON."""
    if not path.exists():
        return json.dumps({"error": f"no log file at {path}"}, indent=2)
    lines: list = []
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    lines.append(json.loads(line))
                except json.JSONDecodeError:
                    lines.append({"raw": line})
    except OSError as exc:
        return json.dumps({"error": str(exc)}, indent=2)
    return json.dumps({"count": len(lines), "tail": lines[-max_lines:]}, indent=2)


def _executions_resource() -> str:
    """Tail of the executions log."""
    return _tail_file(config.log_dir / "executions.jsonl")


def _server_log_resource() -> str:
    """Tail of the server log."""
    return _tail_file(config.log_dir / "server.log")


def _artifacts_index_resource() -> str:
    """List artifacts in the artifact directory."""
    entries = []
    if config.artifact_dir.exists():
        for p in sorted(config.artifact_dir.iterdir()):
            if p.is_file():
                entries.append(
                    {
                        "name": p.name,
                        "size_bytes": p.stat().st_size,
                        "uri": f"{RESOURCE_NAMESPACE}://artifacts/{p.name}",
                    }
                )
    return json.dumps({"count": len(entries), "artifacts": entries}, indent=2)


def _artifact_resource(artifact: str) -> str:
    """Read a single artifact, safely (no path traversal)."""
    name = Path(artifact).name
    if name != artifact:
        return json.dumps({"error": "invalid artifact name"}, indent=2)
    path = config.artifact_dir / name
    if not path.exists() or not path.is_file():
        return json.dumps({"error": f"artifact not found: {name}"}, indent=2)
    if path.stat().st_size > 1_000_000:
        return json.dumps({"error": "artifact too large to read"}, indent=2)
    try:
        content = path.read_text(encoding="utf-8", errors="replace")
    except OSError as exc:
        return json.dumps({"error": str(exc)}, indent=2)
    try:
        payload = json.loads(content)
    except json.JSONDecodeError:
        payload = content
    return json.dumps(payload, indent=2, default=str)


def register_resources(mcp, health=None) -> None:
    """Register all kali:// resources and templates on the FastMCP server."""
    mcp.resource(
        f"{RESOURCE_NAMESPACE}://config",
        name="kali_config",
        description="Live server configuration",
        mime_type="application/json",
    )(_config_resource)

    mcp.resource(
        f"{RESOURCE_NAMESPACE}://tools",
        name="kali_tools",
        description="Registered tool inventory with schemas",
        mime_type="application/json",
    )(_tools_resource)

    mcp.resource(
        f"{RESOURCE_NAMESPACE}://health",
        name="kali_health",
        description="Live server health status",
        mime_type="application/json",
    )(_make_health_resource(health))

    mcp.resource(
        f"{RESOURCE_NAMESPACE}://logs/executions",
        name="kali_executions_log",
        description="Tail of the executions log (JSON lines)",
        mime_type="application/json",
    )(_executions_resource)

    mcp.resource(
        f"{RESOURCE_NAMESPACE}://logs/server",
        name="kali_server_log",
        description="Tail of the server log (JSON lines)",
        mime_type="application/json",
    )(_server_log_resource)

    mcp.resource(
        f"{RESOURCE_NAMESPACE}://artifacts",
        name="kali_artifacts",
        description="List generated artifacts",
        mime_type="application/json",
    )(_artifacts_index_resource)

    mcp.resource(
        f"{RESOURCE_NAMESPACE}://artifacts/{{artifact}}",
        name="kali_artifact",
        description="Read a generated artifact by name",
        mime_type="application/json",
    )(_artifact_resource)

    logger.info(
        "Registered %d resources + %d templates",
        6,
        len(TEMPLATES),
    )
