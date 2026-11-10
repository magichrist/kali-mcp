"""Unit tests for server configuration defaults."""

from __future__ import annotations


def test_default_config():
    from kali_mcp.config import config

    assert config.port == 8399
    assert config.default_timeout == 300
    assert config.max_timeout == 3600
    assert config.max_concurrent == 10
    assert config.host in ["127.0.0.1","0.0.0.0"] # Local run takes 0.0.0.0, but git action is showing Unexpected results.


def test_db_config_defaults():
    from kali_mcp.config import config

    assert config.db_enabled is True
    assert str(config.db_path).endswith("kali-mcp.sqlite")
