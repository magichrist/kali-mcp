"""Unit tests for utils/vault.py — CRUD, mirrors, index, query, size limits."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from kmcp.utils import vault


@pytest.fixture(autouse=True)
def _vault(tmp_path, monkeypatch):
    """Retarget the vault root to a per-test temp dir and init it."""
    monkeypatch.setattr(vault, "VAULT_ROOT", tmp_path / "vault")
    vault.ensure_vault_dirs()
    yield


class TestEnsureVaultDirs:
    def test_creates_root_and_index(self):
        assert vault.VAULT_ROOT.is_dir()
        assert (vault.VAULT_ROOT / "index.json").exists()

    def test_idempotent(self):
        vault.ensure_vault_dirs()
        vault.ensure_vault_dirs()
        index = json.loads((vault.VAULT_ROOT / "index.json").read_text())
        assert index["count"] == 0
        assert index["entries"] == []


class TestVaultWriteRead:
    def test_json_payload_roundtrip(self):
        payload = {"tool": "nmap", "port": 22, "open": True}
        mirror = vault.vault_write("findings", "ssh-22", payload)
        assert Path(mirror).exists()
        raw = vault.vault_read("findings", "ssh-22")
        assert json.loads(raw) == payload

    def test_string_content_stored_verbatim(self):
        content = "key1=value1\nkey2=value2\n"
        vault.vault_write("notes", "verbatim", content)
        assert vault.vault_read("notes", "verbatim") == content

    def test_write_overwrites_existing_and_updates_index(self):
        vault.vault_write("notes", "key", {"v": 1})
        vault.vault_write("notes", "key", {"v": 2})
        raw = vault.vault_read("notes", "key")
        assert json.loads(raw) == {"v": 2}
        index = json.loads((vault.VAULT_ROOT / "index.json").read_text())
        assert index["count"] == 1

    def test_read_missing_returns_error_json(self):
        raw = vault.vault_read("findings", "does_not_exist")
        assert json.loads(raw) == {"error": "not found"}

    def test_missing_category_read_returns_error(self):
        raw = vault.vault_read("no_such_category", "anything")
        assert json.loads(raw) == {"error": "not found"}


class TestVaultList:
    def test_list_filters_by_category(self):
        vault.vault_write("runs/a", "a1", {"x": 1})
        vault.vault_write("runs/b", "b1", {"x": 2})
        vault.vault_write("runs/a", "a2", {"x": 3})
        listed = vault.vault_list(category="runs/a")
        assert listed["count"] == 2
        assert {e["name"] for e in listed["entries"]} == {"a1", "a2"}

    def test_list_accepts_multiple_categories(self):
        vault.vault_write("runs/a", "a1", {"x": 1})
        vault.vault_write("runs/b", "b1", {"x": 2})
        listed = vault.vault_list(category=["runs/a", "runs/b"])
        assert listed["count"] == 2

    def test_list_comma_separated_category(self):
        vault.vault_write("runs/a", "a1", {"x": 1})
        vault.vault_write("runs/b", "b1", {"x": 2})
        listed = vault.vault_list(category="runs/a,runs/b")
        assert listed["count"] == 2

    def test_list_limit_and_offset(self):
        for i in range(5):
            vault.vault_write("findings", f"item_{i}", {"i": i})
        first = vault.vault_list(limit=2, offset=0)
        assert first["count"] == 5
        assert len(first["entries"]) == 2
        second = vault.vault_list(limit=2, offset=2)
        assert len(second["entries"]) == 2
        assert first["entries"][0]["name"] != second["entries"][0]["name"]

    def test_list_no_content_returned(self):
        vault.vault_write("findings", "item_1", {"secret": "shh"})
        listed = vault.vault_list(category="findings")
        for entry in listed["entries"]:
            assert "content" not in entry


class TestVaultQuery:
    def test_query_filters_by_tool(self):
        vault.vault_write("findings", "f1", {"tool": "nmap"}, target="127.0.0.1", tool="nmap")
        vault.vault_write("findings", "f2", {"tool": "httpx"}, target="example.org", tool="httpx")
        by_tool = vault.vault_query(tool="nmap")
        assert by_tool["count"] == 1
        assert by_tool["entries"][0]["name"] == "f1"

    def test_query_filters_by_target(self):
        vault.vault_write("findings", "f1", {"tool": "nmap"}, target="127.0.0.1", tool="nmap")
        vault.vault_write("findings", "f2", {"tool": "httpx"}, target="example.org", tool="httpx")
        by_target = vault.vault_query(target="example.org")
        assert by_target["count"] == 1
        assert by_target["entries"][0]["tool"] == "httpx"

    def test_query_filters_by_category_list(self):
        vault.vault_write("findings/a", "f1", {"x": 1}, target="t", tool="nmap")
        vault.vault_write("findings/b", "f2", {"x": 2}, target="t", tool="nmap")
        result = vault.vault_query(category=["findings/a"], tool="nmap")
        assert result["count"] == 1
        assert result["entries"][0]["name"] == "f1"

    def test_query_search_matches_name_tags_content(self):
        vault.vault_write(
            "findings",
            "ssh_brute",
            {"note": "open port 22"},
            target="127.0.0.1",
            tool="nmap",
            tags="brute,ssh",
        )
        vault.vault_write(
            "findings",
            "http_header",
            {"note": "server: apache"},
            target="example.org",
            tool="httpx",
            tags="web",
        )
        by_name = vault.vault_query(search="ssh_brute")
        assert by_name["count"] == 1
        by_tag = vault.vault_query(search="web")
        assert by_tag["count"] == 1
        by_content = vault.vault_query(search="apache")
        assert by_content["count"] == 1

    def test_query_search_is_case_insensitive(self):
        vault.vault_write("findings", "item", {"note": "Open Port 22"}, target="t", tool="nmap")
        assert vault.vault_query(search="open port")["count"] == 1
        assert vault.vault_query(search="OPEN PORT")["count"] == 1
        assert vault.vault_query(search="nomatch")["count"] == 0

    def test_query_with_no_filters_returns_all(self):
        vault.vault_write("findings", "f1", {"x": 1})
        vault.vault_write("findings", "f2", {"x": 2})
        result = vault.vault_query()
        assert result["count"] == 2


class TestVaultDelete:
    def test_delete_removes_row_and_mirror(self):
        vault.vault_write("runs/test", "del-me", {"x": 1})
        mirror = Path(vault.vault_path("runs/test", "del-me"))
        assert mirror.exists()
        result = vault.vault_delete("runs/test", "del-me")
        assert result["deleted"] is True
        assert result["category"] == "runs/test"
        assert result["name"] == "del-me"
        assert not mirror.exists()
        raw = vault.vault_read("runs/test", "del-me")
        assert json.loads(raw) == {"error": "not found"}

    def test_delete_missing_returns_deleted_false(self):
        result = vault.vault_delete("runs/test", "never_was")
        assert result["deleted"] is False

    def test_delete_regenerates_index(self):
        vault.vault_write("runs/test", "d1", {"x": 1})
        vault.vault_write("runs/test", "d2", {"x": 2})
        vault.vault_delete("runs/test", "d1")
        index = json.loads((vault.VAULT_ROOT / "index.json").read_text())
        assert index["count"] == 1
        assert index["entries"][0]["name"] == "d2"


class TestVaultStats:
    def test_stats_shape(self):
        vault.vault_write("runs/t", "s1", {"x": 1}, tool="nmap")
        vault.vault_write("runs/t", "s2", {"x": 2}, tool="httpx")
        vault.vault_write("findings", "f1", {"x": 3}, tool="nmap")
        stats = vault.vault_stats()
        assert stats["total"] == 3
        assert stats["by_category"]["runs/t"] == 2
        assert stats["by_category"]["findings"] == 1
        assert stats["by_tool"]["nmap"] == 2
        assert stats["by_tool"]["httpx"] == 1
        assert "total_bytes" in stats
        assert "db_path" in stats


class TestVaultPathAndIndex:
    def test_vault_path_returns_mirror_path(self):
        vault.vault_write("findings", "p1", {"x": 1})
        p = vault.vault_path("findings", "p1")
        assert p.endswith("findings/p1.json")
        assert vault.VAULT_ROOT in Path(p).resolve().parents

    def test_get_index_returns_count_and_entries(self):
        vault.vault_write("findings", "i1", {"x": 1})
        index = vault.get_index()
        assert index["count"] == 1
        assert index["entries"][0]["name"] == "i1"
        assert index["entries"][0]["category"] == "findings"


class TestVaultRowSizeLimit:
    def test_row_too_large_raises(self, tmp_path, monkeypatch):
        from dataclasses import replace

        from kmcp import config as cfg

        small_cfg = replace(cfg.config, vault_max_row_bytes=100)
        with patch("kmcp.utils.vault.config", small_cfg), pytest.raises(ValueError):
            vault.vault_write("runs/big", "big", {"data": "x" * 1000})

    def test_zero_max_row_means_unlimited(self, tmp_path, monkeypatch):
        from dataclasses import replace

        from kmcp import config as cfg

        unlimited_cfg = replace(cfg.config, vault_max_row_bytes=0)
        with patch("kmcp.utils.vault.config", unlimited_cfg):
            vault.vault_write("runs/huge", "huge", {"data": "y" * 5000})
            assert json.loads(vault.vault_read("runs/huge", "huge"))["data"] == "y" * 5000


class TestVaultConcurrency:
    def test_concurrent_writes_are_safe(self):
        errors = []

        def writer(i: int) -> None:
            try:
                vault.vault_write("runs/conc", f"w{i}", {"i": i})
            except Exception as exc:  # noqa: BLE001
                errors.append(exc)

        threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        assert not errors
        listed = vault.vault_list(category="runs/conc")
        assert listed["count"] == 20
