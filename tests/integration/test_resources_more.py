"""Tests for resources.py readers: config, tools, artifacts, logs, traversal safety."""

from __future__ import annotations

import json

import pytest


@pytest.fixture()
def artifact_env(tmp_path, monkeypatch):
    """Point artifact/log dirs at tmp; create sample files."""
    import dataclasses

    from kali_mcp.config import config as real_config

    new_cfg = dataclasses.replace(
        real_config,
        artifact_dir=tmp_path / "artifacts",
        log_dir=tmp_path / "logs",
    )
    monkeypatch.setattr("kali_mcp.resources.config", new_cfg)
    (tmp_path / "artifacts").mkdir(exist_ok=True)
    (tmp_path / "logs").mkdir(exist_ok=True)
    (tmp_path / "artifacts" / "sample.txt").write_text("hello artifact")
    (tmp_path / "logs" / "server.log").write_text(
        json.dumps({"timestamp": "t", "level": "INFO", "logger": "x", "message": "m"})
        + "\n"
    )
    return tmp_path


class TestConfigResource:
    def test_shape(self, artifact_env):
        import kali_mcp.resources as resources

        cfg = json.loads(resources._config_resource())
        assert cfg["port"] == 8399
        assert "server_name" in cfg
        assert "auth_enabled" in cfg

    def test_auth_flag_reflects_token(self, artifact_env, monkeypatch):
        import dataclasses

        import kali_mcp.resources as resources
        from kali_mcp.config import config as real_config

        cfg_with_token = dataclasses.replace(real_config, api_token="secret")
        monkeypatch.setattr("kali_mcp.resources.config", cfg_with_token)
        assert json.loads(resources._config_resource())["auth_enabled"] is True


class TestToolsResource:
    def test_lists_all_tools(self):
        import kali_mcp.resources as resources

        data = json.loads(resources._tools_resource())
        assert data["count"] >= 50
        names = {t["name"] for t in data["tools"]}
        assert "nmap" in names and "hydra" in names
        for t in data["tools"]:
            assert t["description"]
            assert "type" in t["schema"]


class TestArtifacts:
    def test_index_lists_files(self, artifact_env):
        import kali_mcp.resources as resources

        data = json.loads(resources._artifacts_index_resource())
        assert data["count"] == 1
        assert data["artifacts"][0]["name"] == "sample.txt"
        assert data["artifacts"][0]["size_bytes"] > 0

    def test_read_artifact(self, artifact_env):
        import kali_mcp.resources as resources

        payload = json.loads(resources._artifact_resource("sample.txt"))
        assert payload == "hello artifact"

    def test_read_missing_artifact(self, artifact_env):
        import kali_mcp.resources as resources

        assert "error" in json.loads(resources._artifact_resource("nope.txt"))

    def test_read_rejects_traversal(self, artifact_env):
        import kali_mcp.resources as resources

        assert "error" in json.loads(
            resources._artifact_resource("../../../etc/passwd")
        )

    def test_non_json_artifact_returned_as_string(self, artifact_env):
        import kali_mcp.resources as resources

        (artifact_env / "artifacts" / "plain.txt").write_text("not json")
        payload = json.loads(resources._artifact_resource("plain.txt"))
        assert payload == "not json"


class TestLogTails:
    def test_server_log_tail(self, artifact_env):
        import kali_mcp.resources as resources

        data = json.loads(resources._server_log_resource())
        assert data["count"] == 1
        assert data["tail"][0]["message"] == "m"

    def test_missing_log_file(self, artifact_env):
        import kali_mcp.resources as resources

        (artifact_env / "logs" / "server.log").unlink()
        assert "error" in json.loads(resources._server_log_resource())

    def test_malformed_log_lines_survive(self, artifact_env):
        import kali_mcp.resources as resources

        (artifact_env / "logs" / "executions.jsonl").write_text(
            json.dumps({"ok": 1}) + "\nGARBAGE LINE\n"
        )
        data = json.loads(resources._executions_resource())
        assert data["count"] == 2
        assert data["tail"][-1] == {"raw": "GARBAGE LINE"}


class TestDbStatsAndVaultIndex:
    def test_db_stats_when_db_fails(self, monkeypatch):
        from kali_mcp.db import manager as dbm
        import kali_mcp.resources as resources

        def boom():
            raise RuntimeError("db down")

        monkeypatch.setattr(dbm, "get_db", boom)
        assert "error" in json.loads(resources._db_stats_resource())

    def test_vault_index_when_vault_fails(self, monkeypatch):
        import kali_mcp.resources as resources

        def boom():
            raise RuntimeError("vault down")

        monkeypatch.setattr("kali_mcp.utils.vault.ensure_vault_dirs", boom)
        assert "error" in json.loads(resources._vault_index_resource())

    def test_vault_index_enriches_uris(self, tmp_path, monkeypatch):
        import dataclasses

        import kali_mcp.resources as resources
        from kali_mcp.config import config as real_config
        from kali_mcp.utils import vault as v

        art_dir = tmp_path / "artifacts"
        art_dir.mkdir(exist_ok=True)
        new_cfg = dataclasses.replace(real_config, artifact_dir=art_dir)
        monkeypatch.setattr("kali_mcp.resources.config", new_cfg)
        monkeypatch.setattr(v, "VAULT_ROOT", art_dir / "vault")
        v.ensure_vault_dirs()
        v.vault_write("findings", "uri_test", {"a": 1})

        index = json.loads(resources._vault_index_resource())
        entry = next(e for e in index["entries"] if e["name"] == "uri_test")
        assert entry.get("uri") == "kali://artifacts/vault/findings/uri_test.json"
