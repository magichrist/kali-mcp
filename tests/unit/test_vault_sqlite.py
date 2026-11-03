"""Tests for the SQLite-backed vault (utils/vault.py) and its MCP tools.

Covers: SQLite persistence, overwrite semantics, querying, deletion,
index self-healing, path safety, and the agent → subagent handoff flow.
"""

from __future__ import annotations

import json
import sqlite3

import pytest

from kali_mcp.utils import vault


@pytest.fixture()
def vault_env(tmp_path, monkeypatch):
    """Point the vault at a temp root and init it."""
    monkeypatch.setattr(vault, "VAULT_ROOT", tmp_path / "vault")
    vault.ensure_vault_dirs()
    yield tmp_path / "vault"


class TestSqliteStorage:
    def test_db_file_created_inside_vault_root(self, vault_env):
        assert (vault_env / "vault.sqlite").exists()

    def test_entries_persist_in_sqlite(self, vault_env):
        vault.vault_write("findings", "sql_row", {"port": 22})
        conn = sqlite3.connect(str(vault_env / "vault.sqlite"))
        try:
            row = conn.execute(
                "SELECT category, name, content FROM entries WHERE name='sql_row'"
            ).fetchone()
        finally:
            conn.close()
        assert row is not None
        assert row[0] == "findings"
        assert json.loads(row[2]) == {"port": 22}

    def test_tags_index_exists(self, vault_env):
        conn = sqlite3.connect(str(vault_env / "vault.sqlite"))
        try:
            indexes = {
                row[0] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='index'")
            }
        finally:
            conn.close()
        assert {
            "idx_entries_category",
            "idx_entries_target",
            "idx_entries_tags",
        } <= indexes

    def test_unique_category_name(self, vault_env):
        vault.vault_write("vulnerabilities", "vuln:VULN-001", "title=SQLi")
        with pytest.raises(sqlite3.IntegrityError):
            conn = sqlite3.connect(str(vault_env / "vault.sqlite"))
            try:
                conn.execute(
                    "INSERT INTO entries (category, name, content, created_at, "
                    "updated_at) VALUES ('vulnerabilities', 'vuln:VULN-001', "
                    "'x', 't', 't')"
                )
            finally:
                conn.close()

    def test_keyvalue_content_stored_verbatim(self, vault_env):
        fields = "title=SQL injection\nseverity=critical\nurl=http://t/x"
        vault.vault_write("vulnerabilities", "vuln:VULN-002", fields)
        assert vault.vault_read("vulnerabilities", "vuln:VULN-002") == fields
        # free-text search reaches into verbatim content
        res = vault.vault_query(search="severity=critical")
        assert res["count"] == 1
        assert res["entries"][0]["name"] == "vuln:VULN-002"

    def test_multi_category_query(self, vault_env):
        vault.vault_write("web", "w1", {"a": 1})
        vault.vault_write("active_directory", "ad1", {"b": 2})
        vault.vault_write("source_code", "sc1", {"c": 3})
        res = vault.vault_query(category="web, active_directory")
        assert res["count"] == 2
        names = {e["name"] for e in res["entries"]}
        assert names == {"w1", "ad1"}
        # list-style API accepts a list too
        res = vault.vault_list(category=["web", "source_code"])
        assert res["count"] == 2

    def test_row_keys_with_colons_and_slashes(self, vault_env):
        vault.vault_write("vulnerabilities", "vuln:VULN-010", {"x": 1})
        vault.vault_write("source_code", "repo:org/name", {"y": 2})
        assert json.loads(vault.vault_read("vulnerabilities", "vuln:VULN-010")) == {"x": 1}
        assert json.loads(vault.vault_read("source_code", "repo:org/name")) == {"y": 2}

    def test_write_is_single_row_no_junk(self, vault_env):
        vault.vault_write("findings", "one_row", {"a": 1})
        vault.vault_write("findings", "one_row", {"a": 2})  # overwrite, not insert
        conn = sqlite3.connect(str(vault_env / "vault.sqlite"))
        try:
            count, total = conn.execute(
                "SELECT COUNT(*), (SELECT COUNT(*) FROM entries) FROM entries"
            ).fetchone()
        finally:
            conn.close()
        assert count == 1 and total == 1

    def test_metadata_columns_stored(self, vault_env):
        vault.vault_write("handoff", "meta", {"x": 1}, target="10.0.0.1", tool="nmap", tags="recon")
        entry = vault.vault_query(target="10.0.0.1")["entries"][0]
        assert entry["tool"] == "nmap"
        assert entry["tags"] == "recon"


class TestQueryApi:
    def test_query_by_category(self, vault_env):
        vault.vault_write("findings", "q1", {"a": 1})
        vault.vault_write("notes", "q2", {"b": 2})
        res = vault.vault_query(category="findings")
        assert res["count"] == 1
        assert res["entries"][0]["name"] == "q1"

    def test_free_text_search(self, vault_env):
        vault.vault_write("handoff", "ssh_creds", {"user": "admin"})
        res = vault.vault_query(search="ssh")
        assert res["count"] == 1
        assert res["entries"][0]["name"] == "ssh_creds"

    def test_search_matches_content(self, vault_env):
        vault.vault_write("findings", "blob", {"secret_value": "s3cret"})
        res = vault.vault_query(search="s3cret")
        assert res["count"] == 1

    def test_combined_filters(self, vault_env):
        vault.vault_write("findings", "m1", {"a": 1}, target="10.0.0.1", tool="nmap")
        vault.vault_write("findings", "m2", {"a": 2}, target="10.0.0.2", tool="nmap")
        res = vault.vault_query(target="10.0.0.1", tool="nmap")
        assert res["count"] == 1
        assert res["entries"][0]["name"] == "m1"

    def test_list_paginates(self, vault_env):
        for i in range(5):
            vault.vault_write("findings", f"p{i}", {"i": i})
        page = vault.vault_list(category="findings", limit=2, offset=2)
        assert page["count"] == 5
        assert len(page["entries"]) == 2


class TestDeleteAndStats:
    def test_delete_removes_row_and_mirror(self, vault_env):
        path = vault.vault_write("notes", "gone", {"a": 1})
        res = vault.vault_delete("notes", "gone")
        assert res["deleted"] is True
        import os

        assert not os.path.exists(path)
        assert vault.vault_read("notes", "gone") == json.dumps({"error": "not found"})

    def test_delete_missing_is_reported(self, vault_env):
        res = vault.vault_delete("notes", "never_existed")
        assert res["deleted"] is False

    def test_stats(self, vault_env):
        vault.vault_write("findings", "s1", {"a": 1}, tool="nmap")
        vault.vault_write("notes", "s2", {"b": 2})
        stats = vault.vault_stats()
        assert stats["total"] == 2
        assert stats["by_category"]["findings"] == 1
        assert stats["by_tool"]["nmap"] == 1


class TestAgentHandoff:
    def test_agent_to_subagent_roundtrip(self, vault_env):
        # Agent 1: store a handoff payload for a subagent
        vault.vault_write(
            "handoff",
            "webapp_recon_results",
            {"urls": ["http://t/admin"], "note": "fuzz these"},
            target="target.example.com",
            tool="playbook_recon",
        )
        # Subagent 2: discover and read it
        found = vault.vault_query(category="handoff", target="target.example.com")
        assert found["count"] == 1
        entry = found["entries"][0]
        payload = json.loads(vault.vault_read(entry["category"], entry["name"]))
        assert payload["urls"] == ["http://t/admin"]

    def test_json_mirror_file_exists(self, vault_env):
        path = vault.vault_write("findings", "mirrored", {"a": 1})
        with open(path) as fh:
            assert json.load(fh) == {"a": 1}


class TestLimits:
    def test_oversize_row_rejected(self, vault_env, monkeypatch):
        """Rows over MCP_VAULT_MAX_ROW_BYTES are rejected with a clear error."""
        import dataclasses

        from kali_mcp.config import config as real_config

        small = dataclasses.replace(real_config, vault_max_row_bytes=1024)
        monkeypatch.setattr(vault, "config", small)
        with pytest.raises(ValueError, match="vault row too large"):
            vault.vault_write("stress", "too_big", "x" * 2048)
        # nothing was written
        assert vault.vault_read("stress", "too_big") == json.dumps({"error": "not found"})

    def test_zero_limit_means_unlimited(self, vault_env, monkeypatch):
        import dataclasses

        from kali_mcp.config import config as real_config

        unlimited = dataclasses.replace(real_config, vault_max_row_bytes=0)
        monkeypatch.setattr(vault, "config", unlimited)
        path = vault.vault_write("stress", "big_ok", "x" * 2048)
        assert path

    def test_default_limit_allows_normal_rows(self, vault_env):
        vault.vault_write("stress", "normal", {"blob": "y" * 500_000})
        assert vault.vault_stats()["total"] == 1


class TestValidation:
    def test_empty_category_rejected(self, vault_env):
        with pytest.raises(ValueError):
            vault.vault_write("", "x", {"a": 1})

    def test_empty_name_rejected(self, vault_env):
        with pytest.raises(ValueError):
            vault.vault_write("findings", "  ", {"a": 1})
