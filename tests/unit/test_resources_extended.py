"""Unit tests for resources.py edge cases (resource readers + registration)."""

from __future__ import annotations

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from kali_mcp import config as cfg_mod
from kali_mcp.resources import (
    _artifact_resource,
    _artifacts_index_resource,
    _config_resource,
    _db_stats_resource,
    _executions_resource,
    _make_health_resource,
    _server_log_resource,
    _tail_file,
    _tools_resource,
    _vault_index_resource,
    register_resources,
)


class TestConfigResource:
    def test_returns_json_with_expected_keys(self) -> None:
        text = _config_resource()
        data = json.loads(text)
        for key in (
            "server_name",
            "server_version",
            "host",
            "port",
            "transport",
            "default_timeout",
            "max_timeout",
            "max_concurrent",
            "log_dir",
            "artifact_dir",
            "debug",
            "rate_limit_per_minute",
            "auth_enabled",
        ):
            assert key in data


class TestToolsResource:
    def test_returns_registered_tools(self) -> None:
        from kali_mcp.registry import registry

        text = _tools_resource()
        data = json.loads(text)
        assert "count" in data
        assert "tools" in data
        assert data["count"] == len(registry.list_all())


class TestMakeHealthResource:
    def test_returns_health_json(self) -> None:
        fake_health = MagicMock()
        fake_health.get_status.return_value = {"status": "healthy", "uptime_seconds": 1.0}
        reader = _make_health_resource(fake_health)
        text = reader()
        data = json.loads(text)
        assert data["status"] == "healthy"


class TestTailFile:
    def test_nonexistent_file(self, tmp_path) -> None:
        text = _tail_file(tmp_path / "nope.log")
        data = json.loads(text)
        assert "error" in data

    def test_empty_file(self, tmp_path) -> None:
        p = tmp_path / "empty.jsonl"
        p.write_text("")
        text = _tail_file(p)
        data = json.loads(text)
        assert data["count"] == 0
        assert data["tail"] == []

    def test_json_lines_tail(self, tmp_path) -> None:
        p = tmp_path / "exec.jsonl"
        lines = [json.dumps({"i": i}) for i in range(5)]
        p.write_text("\n".join(lines) + "\n")
        text = _tail_file(p, max_lines=3)
        data = json.loads(text)
        assert data["count"] == 5
        assert len(data["tail"]) == 3

    def test_mixed_valid_and_invalid_lines(self, tmp_path) -> None:
        p = tmp_path / "mixed.jsonl"
        p.write_text('{"ok": true}\nnot json\n{"ok": false}\n')
        text = _tail_file(p)
        data = json.loads(text)
        assert data["count"] == 3
        assert data["tail"][2] == {"ok": False}
        assert data["tail"][1] == {"raw": "not json"}


class TestArtifactResource:
    def test_invalid_name_traversal(self) -> None:
        text = _artifact_resource("../etc/passwd")
        data = json.loads(text)
        assert data["error"] == "invalid artifact name"

    def test_missing_artifact(self) -> None:
        text = _artifact_resource("does_not_exist.json")
        data = json.loads(text)
        assert "artifact not found" in data["error"]

    def test_too_large_artifact(self, tmp_path) -> None:
        import kali_mcp.resources as res_mod

        orig = res_mod.config.artifact_dir
        object.__setattr__(res_mod.config, "artifact_dir", tmp_path)
        try:
            big = tmp_path / "big.json"
            big.write_text("x" * (2_000_000))
            text = _artifact_resource("big.json")
            data = json.loads(text)
            assert "too large" in data["error"]
        finally:
            object.__setattr__(res_mod.config, "artifact_dir", orig)

    def test_reads_json_artifact(self, tmp_path) -> None:
        import kali_mcp.resources as res_mod

        orig = res_mod.config.artifact_dir
        object.__setattr__(res_mod.config, "artifact_dir", tmp_path)
        try:
            art = tmp_path / "note.json"
            art.write_text(json.dumps({"foo": "bar"}))
            text = _artifact_resource("note.json")
            data = json.loads(text)
            assert data == {"foo": "bar"}
        finally:
            object.__setattr__(res_mod.config, "artifact_dir", orig)


class TestDbStatsResource:
    def test_db_disabled(self) -> None:
        with patch("kali_mcp.db.manager.get_db", return_value=None):
            text = _db_stats_resource()
            data = json.loads(text)
            assert "error" in data


class TestVaultIndexResource:
    def test_returns_index(self) -> None:
        text = _vault_index_resource()
        data = json.loads(text)
        assert "count" in data
        assert "entries" in data


class TestRegisterResources:
    def test_registers_all_resources(self) -> None:
        fake_mcp = MagicMock()
        fake_health = MagicMock()
        register_resources(fake_mcp, health=fake_health)
        assert fake_mcp.resource.call_count >= 9


class TestExecutionsAndServerLogResource:
    def test_executions_resource(self) -> None:
        text = _executions_resource()
        data = json.loads(text)
        assert "count" in data

    def test_server_log_resource(self) -> None:
        text = _server_log_resource()
        data = json.loads(text)
        assert "count" in data or "error" in data
