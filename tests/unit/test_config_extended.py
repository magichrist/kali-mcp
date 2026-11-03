"""Unit tests for config.py edge cases (env parsing, path creation, __post_init__)."""

from __future__ import annotations

import os
from dataclasses import FrozenInstanceError
from pathlib import Path
from unittest.mock import patch

import pytest

from kali_mcp.config import Config, config


class TestConfigEnvParsing:
    def test_int_env_default(self) -> None:
        with patch.dict(os.environ, {}):
            c = Config()
            assert c.port == 8399
            assert c.default_timeout == 300
            assert c.max_concurrent == 10

    def test_int_env_override(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MCP_PORT": "9999",
                "MCP_DEFAULT_TIMEOUT": "60",
                "MCP_MAX_TIMEOUT": "7200",
                "MCP_MAX_CONCURRENT": "25",
                "MCP_RATE_LIMIT": "120",
            },
            clear=True,
        ):
            c = Config()
            assert c.port == 9999
            assert c.default_timeout == 60
            assert c.max_timeout == 7200
            assert c.max_concurrent == 25
            assert c.rate_limit_per_minute == 120

    def test_int_env_invalid_falls_back_to_default(self) -> None:
        with patch.dict(os.environ, {"MCP_PORT": "not-a-number"}):
            c = Config()
            assert c.port == 8399

    def test_bool_env_true_values(self) -> None:
        for val in ("1", "true", "yes"):
            with patch.dict(os.environ, {"MCP_DEBUG": val}):
                c = Config()
                assert c.debug is True, f"expected True for {val!r}"

    def test_bool_env_false_values(self) -> None:
        for val in ("0", "false", "no", ""):
            with patch.dict(os.environ, {"MCP_DEBUG": val}):
                c = Config()
                assert c.debug is False, f"expected False for {val!r}"

    def test_paths_default(self) -> None:
        with patch.dict(os.environ, {}):
            c = Config()
            assert c.log_dir == Path("logs")
            assert c.artifact_dir == Path("artifacts")
            assert c.db_path == Path("data/kali-mcp.sqlite")

    def test_paths_override(self) -> None:
        with patch.dict(
            os.environ,
            {
                "MCP_LOG_DIR": "/tmp/custom_logs",
                "MCP_ARTIFACT_DIR": "/tmp/custom_artifacts",
                "MCP_DB_PATH": "/tmp/custom.db",
            },
            clear=True,
        ):
            c = Config()
            assert c.log_dir == Path("/tmp/custom_logs")
            assert c.artifact_dir == Path("/tmp/custom_artifacts")
            assert c.db_path == Path("/tmp/custom.db")

    def test_transport_defaults_to_sse(self) -> None:
        with patch.dict(os.environ, {}):
            assert config.transport == "sse"

    def test_api_token_default_empty(self) -> None:
        with patch.dict(os.environ, {}):
            c = Config()
            assert c.api_token == ""

    def test_allowed_origins_default_star(self) -> None:
        with patch.dict(os.environ, {}):
            c = Config()
            assert c.allowed_origins == "*"


class TestConfigPostInit:
    def test_post_init_creates_directories(self, tmp_path) -> None:
        with patch.dict(
            os.environ,
            {
                "MCP_LOG_DIR": str(tmp_path / "logs"),
                "MCP_ARTIFACT_DIR": str(tmp_path / "artifacts"),
                "MCP_DB_PATH": str(tmp_path / "data" / "kali-mcp.sqlite"),
                "MCP_DB_ENABLED": "true",
            },
            clear=True,
        ):
            Config()
            assert (tmp_path / "logs").is_dir()
            assert (tmp_path / "artifacts").is_dir()
            assert (tmp_path / "data").is_dir()

    def test_post_init_skips_db_dir_when_disabled(self, tmp_path) -> None:
        with patch.dict(
            os.environ,
            {
                "MCP_LOG_DIR": str(tmp_path / "logs"),
                "MCP_ARTIFACT_DIR": str(tmp_path / "artifacts"),
                "MCP_DB_ENABLED": "false",
            },
            clear=True,
        ):
            c = Config()
            assert c.db_enabled is False
            # db_path parent not created when disabled
            assert not (tmp_path / "data").exists()

    def test_server_name_and_version_defaults(self) -> None:
        with patch.dict(os.environ, {}):
            c = Config()
            assert c.server_name == "kali-mcp"
            assert c.server_version == "1.0.0"

    def test_server_name_and_version_override(self) -> None:
        with patch.dict(
            os.environ,
            {"MCP_SERVER_NAME": "my-kali", "MCP_SERVER_VERSION": "2.0.0"},
            clear=True,
        ):
            c = Config()
            assert c.server_name == "my-kali"
            assert c.server_version == "2.0.0"

    def test_default_encoding(self) -> None:
        with patch.dict(os.environ, {}):
            c = Config()
            assert c.default_encoding == "utf-8"

    def test_vault_max_row_bytes_default(self) -> None:
        with patch.dict(os.environ, {}):
            c = Config()
            assert c.vault_max_row_bytes == 26_214_400

    def test_frozen_dataclass(self) -> None:
        c = Config()
        with pytest.raises(FrozenInstanceError):
            c.port = 1234
