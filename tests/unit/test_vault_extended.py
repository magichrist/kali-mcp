"""Unit tests for utils/vault.py edge cases."""

from __future__ import annotations

import json
import threading
from pathlib import Path
from unittest.mock import patch

import pytest

from kali_mcp.utils.vault import (
    _mirror_path,
    _safe_component,
    ensure_vault_dirs,
    vault_delete,
    vault_list,
    vault_query,
    vault_read,
    vault_stats,
    vault_write,
)


class TestVaultPathSafety:
    def test_safe_component_strips_traversal(self) -> None:
        assert _safe_component("../../../etc/passwd") != "../../etc/passwd"
        assert ".." not in _safe_component("../..")
        assert _safe_component("normal-name") == "normal-name"
        assert _safe_component("weird/name") == "weird_name"

    def test_mirror_path_stays_inside_vault_root(self, tmp_path) -> None:
        fake_root = tmp_path / "vault"
        with patch("kali_mcp.utils.vault.VAULT_ROOT", fake_root):
            path = _mirror_path("runs/generic_command", "2026_tool.json")
            assert str(path).startswith(str(fake_root))
            assert "runs/generic_command" in str(path)


class TestVaultWriteReadDelete:
    def _patch_vault_root(self, tmp_path) -> None:
        return patch("kali_mcp.utils.vault.VAULT_ROOT", tmp_path / "vault")

    def test_write_and_read_roundtrip(self, tmp_path) -> None:
        with self._patch_vault_root(tmp_path):
            ensure_vault_dirs()
            mirror = vault_write("runs/test", "run-1", {"tool": "nmap", "ok": True})
            assert Path(mirror).exists()
            content = vault_read("runs/test", "run-1")
            data = json.loads(content)
            assert data["tool"] == "nmap"
            assert data["ok"] is True

    def test_write_overwrites_existing(self, tmp_path) -> None:
        with self._patch_vault_root(tmp_path):
            ensure_vault_dirs()
            vault_write("runs/test", "run-1", {"v": 1})
            vault_write("runs/test", "run-1", {"v": 2})
            content = vault_read("runs/test", "run-1")
            assert json.loads(content)["v"] == 2

    def test_read_missing_returns_error_json(self, tmp_path) -> None:
        with self._patch_vault_root(tmp_path):
            ensure_vault_dirs()
            content = vault_read("runs/test", "missing")
            data = json.loads(content)
            assert data["error"] == "not found"

    def test_list_filters_by_category(self, tmp_path) -> None:
        with self._patch_vault_root(tmp_path):
            ensure_vault_dirs()
            vault_write("runs/a", "a1", {"x": 1})
            vault_write("runs/b", "b1", {"x": 2})
            vault_write("runs/a", "a2", {"x": 3})
            listed = vault_list(category="runs/a")
            assert listed["count"] == 2
            names = {e["name"] for e in listed["entries"]}
            assert names == {"a1", "a2"}

    def test_query_filters_by_tool_and_target(self, tmp_path) -> None:
        with self._patch_vault_root(tmp_path):
            ensure_vault_dirs()
            vault_write(
                "findings/127.0.0.1",
                "f1",
                {"tool": "nmap"},
                target="127.0.0.1",
                tool="nmap",
            )
            vault_write(
                "findings/example.org",
                "f2",
                {"tool": "httpx"},
                target="example.org",
                tool="httpx",
            )
            by_tool = vault_query(tool="nmap")
            assert by_tool["count"] == 1
            by_target = vault_query(target="127.0.0.1")
            assert by_target["count"] == 1

    def test_delete_removes_row_and_mirror(self, tmp_path) -> None:
        with self._patch_vault_root(tmp_path):
            ensure_vault_dirs()
            vault_write("runs/test", "del-me", {"x": 1})
            result = vault_delete("runs/test", "del-me")
            assert result["deleted"] is True
            content = vault_read("runs/test", "del-me")
            assert json.loads(content)["error"] == "not found"

    def test_stats_shape(self, tmp_path) -> None:
        with self._patch_vault_root(tmp_path):
            ensure_vault_dirs()
            vault_write("runs/t", "s1", {"tool": "nmap"})
            stats = vault_stats()
            assert "total" in stats
            assert "by_category" in stats
            assert "by_tool" in stats
            assert "total_bytes" in stats
            assert stats["total"] >= 1

    def test_concurrent_writes_are_safe(self, tmp_path) -> None:
        with self._patch_vault_root(tmp_path):
            ensure_vault_dirs()
            errors = []

            def writer(i: int) -> None:
                try:
                    vault_write("runs/conc", f"w{i}", {"i": i})
                except Exception as exc:  # noqa: BLE001
                    errors.append(exc)

            threads = [threading.Thread(target=writer, args=(i,)) for i in range(20)]
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            assert not errors
            listed = vault_list(category="runs/conc")
            assert listed["count"] == 20


class TestVaultRowSizeLimit:
    def _patch_vault_root(self, tmp_path) -> None:
        return patch("kali_mcp.utils.vault.VAULT_ROOT", tmp_path / "vault")

    def test_row_too_large_raises(self, tmp_path) -> None:
        with self._patch_vault_root(tmp_path):
            ensure_vault_dirs()
            # Temporarily lower the max row size on a replaced config instance
            from dataclasses import replace

            from kali_mcp import config as cfg

            small_cfg = replace(cfg.config, vault_max_row_bytes=100)
            with patch("kali_mcp.utils.vault.config", small_cfg), pytest.raises(ValueError):
                vault_write("runs/big", "big", {"data": "x" * 1000})
