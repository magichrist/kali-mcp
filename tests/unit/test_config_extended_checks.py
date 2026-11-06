"""Extended unit tests for config.py env var parsing and defaults."""

from __future__ import annotations

import os
from dataclasses import FrozenInstanceError
from unittest.mock import patch

import pytest

from kali_mcp.config import Config


class TestConfigIntParsingExtended:
    def test_invalid_int_env_falls_back_to_default(self) -> None:
        with patch.dict(
            os.environ,
            {"MCP_PORT": "not-a-number", "MCP_MAX_TIMEOUT": "also-bad"},
            clear=True,
        ):
            c = Config()
            assert c.port == 8399
            assert c.max_timeout == 3600

    def test_negative_int_values_are_accepted(self) -> None:
        with patch.dict(os.environ, {"MCP_PORT": "-1"}, clear=True):
            assert Config().port == -1

    def test_rate_limit_defaults_to_zero_unlimited(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert Config().rate_limit_per_minute == 0

    def test_vault_max_row_bytes_default(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert Config().vault_max_row_bytes == 26_214_400

    def test_max_concurrent_default_and_override(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert Config().max_concurrent == 10
        with patch.dict(os.environ, {"MCP_MAX_CONCURRENT": "25"}, clear=True):
            assert Config().max_concurrent == 25


class TestConfigBoolParsingExtended:
    def test_bool_env_accepts_common_true_false(self) -> None:
        for val, expected in (
            ("1", True),
            ("true", True),
            ("yes", True),
            ("TRUE", True),
            ("0", False),
            ("false", False),
            ("no", False),
            ("", False),
        ):
            with patch.dict(os.environ, {"MCP_DEBUG": val}, clear=True):
                assert Config().debug is expected, f"failed for {val!r}"


class TestConfigStringAndPathDefaults:
    def test_host_default_and_override(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert Config().host == "127.0.0.1"
        with patch.dict(os.environ, {"MCP_HOST": "127.0.0.1"}, clear=True):
            assert Config().host == "127.0.0.1"

    def test_transport_default_sse_and_override(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert Config().transport == "sse"
        with patch.dict(
            os.environ, {"MCP_TRANSPORT": "streamable-http"}, clear=True
        ):
            assert Config().transport == "streamable-http"

    def test_api_token_default_empty_and_override(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert Config().api_token == ""
        with patch.dict(os.environ, {"MCP_API_TOKEN": "tok123"}, clear=True):
            assert Config().api_token == "tok123"

    def test_allowed_origins_default_star_and_override(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert Config().allowed_origins == "*"
        with patch.dict(
            os.environ,
            {"MCP_ALLOWED_ORIGINS": "https://a.com,https://b.com"},
            clear=True,
        ):
            assert Config().allowed_origins == "https://a.com,https://b.com"

    def test_default_encoding_default_and_override(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            assert Config().default_encoding == "utf-8"
        with patch.dict(os.environ, {"MCP_ENCODING": "utf-16"}, clear=True):
            assert Config().default_encoding == "utf-16"

    def test_db_enabled_false_skips_db_dir(self, tmp_path) -> None:
        with patch.dict(
            os.environ,
            {
                "MCP_LOG_DIR": str(tmp_path / "logs"),
                "MCP_ARTIFACT_DIR": str(tmp_path / "artifacts"),
                "MCP_DB_PATH": str(tmp_path / "data" / "kali-mcp.sqlite"),
                "MCP_DB_ENABLED": "false",
            },
            clear=True,
        ):
            c = Config()
            assert c.db_enabled is False
            assert not (tmp_path / "data").exists()

    def test_server_name_version_defaults_and_overrides(self) -> None:
        with patch.dict(os.environ, {}, clear=True):
            c = Config()
            assert c.server_name == "kali-mcp"
            assert c.server_version == "1.0.0"
        with patch.dict(
            os.environ,
            {"MCP_SERVER_NAME": "kali-mcp-v2", "MCP_SERVER_VERSION": "2.0.0"},
            clear=True,
        ):
            c = Config()
            assert c.server_name == "kali-mcp-v2"
            assert c.server_version == "2.0.0"


class TestConfigFrozen:
    def test_frozen_dataclass_rejects_mutation(self) -> None:
        c = Config()
        with pytest.raises(FrozenInstanceError):
            c.port = 9999
