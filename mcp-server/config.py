"""Server configuration loaded from environment variables."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path


@dataclass(frozen=True)
class Config:
    # Server
    host: str = field(default_factory=lambda: os.getenv("MCP_HOST", "0.0.0.0"))
    port: int = field(default_factory=lambda: int(os.getenv("MCP_PORT", "8399")))
    server_name: str = field(default_factory=lambda: os.getenv("MCP_SERVER_NAME", "kali-mcp"))
    server_version: str = field(default_factory=lambda: os.getenv("MCP_SERVER_VERSION", "1.0.0"))

    # Execution
    default_timeout: int = field(default_factory=lambda: int(os.getenv("MCP_DEFAULT_TIMEOUT", "300")))
    max_timeout: int = field(default_factory=lambda: int(os.getenv("MCP_MAX_TIMEOUT", "3600")))
    max_concurrent: int = field(default_factory=lambda: int(os.getenv("MCP_MAX_CONCURRENT", "10")))

    # Paths
    log_dir: Path = field(default_factory=lambda: Path(os.getenv("MCP_LOG_DIR", "logs")))
    artifact_dir: Path = field(default_factory=lambda: Path(os.getenv("MCP_ARTIFACT_DIR", "artifacts")))

    # Encoding
    default_encoding: str = field(default_factory=lambda: os.getenv("MCP_ENCODING", "utf-8"))

    # Debug
    debug: bool = field(default_factory=lambda: os.getenv("MCP_DEBUG", "false").lower() in ("1", "true", "yes"))

    def __post_init__(self) -> None:
        self.log_dir.mkdir(parents=True, exist_ok=True)
        self.artifact_dir.mkdir(parents=True, exist_ok=True)


config = Config()
