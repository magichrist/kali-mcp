"""Server configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path

# Optional: dotenv for local development. If not installed, fall back gracefully.
try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - optional dependency missing in test env # noqa: BLE001

    def load_dotenv(*args, **kwargs):
        return None


load_dotenv(verbose=True)


def _int_env(key: str, default: int) -> int:
    """Parse int from env var with safe fallback."""
    val = os.getenv(key, "")
    if not val:
        return default
    try:
        return int(val)
    except ValueError:
        return default


def _bool_env(key: str, default: bool) -> bool:
    """Parse bool from env var with safe fallback."""
    val = os.getenv(key, "")
    if not val:
        return default
    return val.lower() in ("1", "true", "yes")


@dataclass(frozen=True)
class Config:
    # Server
    host: str = field(default_factory=lambda: os.getenv("MCP_HOST", "127.0.0.1"))
    port: int = field(default_factory=lambda: _int_env("MCP_PORT", 8399))
    server_name: str = field(default_factory=lambda: os.getenv("MCP_SERVER_NAME", "kmcp"))
    server_version: str = field(default_factory=lambda: os.getenv("MCP_SERVER_VERSION", "1.0.0"))

    # Execution
    default_timeout: int = field(default_factory=lambda: _int_env("MCP_DEFAULT_TIMEOUT", 300))
    max_timeout: int = field(default_factory=lambda: _int_env("MCP_MAX_TIMEOUT", 3600))
    max_concurrent: int = field(default_factory=lambda: _int_env("MCP_MAX_CONCURRENT", 10))

    # Paths
    log_dir: Path = field(default_factory=lambda: Path(os.getenv("MCP_LOG_DIR", "logs")))
    artifact_dir: Path = field(
        default_factory=lambda: Path(os.getenv("MCP_ARTIFACT_DIR", "artifacts"))
    )

    # Encoding
    default_encoding: str = field(default_factory=lambda: os.getenv("MCP_ENCODING", "utf-8"))

    # Debug
    debug: bool = field(default_factory=lambda: _bool_env("MCP_DEBUG", False))

    # Transport: "sse" (default) or "streamable-http"
    transport: str = field(default_factory=lambda: os.getenv("MCP_TRANSPORT", "sse"))

    # Auth
    api_token: str = field(default_factory=lambda: os.getenv("MCP_API_TOKEN", ""))
    insecure: bool = field(default_factory=lambda: _bool_env("KALI_MCP_INSECURE", False))
    token_in_query: bool = field(
        default_factory=lambda: _bool_env("KALI_MCP_TOKEN_IN_QUERY", False)
    )

    # CORS
    allowed_origins: str = field(default_factory=lambda: os.getenv("MCP_ALLOWED_ORIGINS", "*"))

    # Rate limiting (0 = unlimited)
    rate_limit_per_minute: int = field(default_factory=lambda: _int_env("MCP_RATE_LIMIT", 0))

    # Vault
    vault_max_row_bytes: int = field(
        default_factory=lambda: _int_env("MCP_VAULT_MAX_ROW_BYTES", 26_214_400)
    )  # 25MB ceiling per vault row (0 = unlimited)

    # Studio
    studio_enabled: bool = field(default_factory=lambda: _bool_env("STUDIO_ENABLED", True))
    # Agent profile bound to this server's auth token (Playbook Studio Phase
    # 6). When set, EVERY MCP request resolves to this agent profile and the
    # deny-by-default permission model is enforced — the client cannot opt
    # out by omitting the X-Agent-Profile header. The header (multi-agent
    # setups) takes precedence only when this is empty.
    agent_profile_id: str = field(
        default_factory=lambda: os.getenv("MCP_AGENT_PROFILE_ID", "").strip()
    )
    studio_db_path: str = field(default_factory=lambda: os.getenv("STUDIO_DB_PATH", ""))
    # Dedicated port for the Studio web UI (0 = share the main MCP server port)
    studio_port: int = field(default_factory=lambda: _int_env("STUDIO_PORT", 0))
    studio_default_visibility: str = field(
        default_factory=lambda: os.getenv("STUDIO_DEFAULT_VISIBILITY", "agent_callable")
    )
    external_mcp_timeout: int = field(default_factory=lambda: _int_env("EXTERNAL_MCP_TIMEOUT", 30))
    studio_mcp_import_timeout: int = field(
        default_factory=lambda: _int_env("STUDIO_MCP_IMPORT_TIMEOUT", 30)
    )

    # Database
    db_path: Path = field(
        default_factory=lambda: Path(os.getenv("MCP_DB_PATH", "data/kmcp.sqlite"))
    )
    db_enabled: bool = field(default_factory=lambda: _bool_env("MCP_DB_ENABLED", True))

    def __post_init__(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)
        if self.db_enabled:
            self.db_path.parent.mkdir(parents=True, exist_ok=True)


config = Config()
