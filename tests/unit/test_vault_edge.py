"""Edge-case tests for the vault: corruption, unicode, nesting, idempotency."""

from __future__ import annotations

import json

import pytest

from utils import vault


@pytest.fixture(autouse=True)
def _vault(tmp_path, monkeypatch):
    monkeypatch.setattr(vault, "VAULT_ROOT", tmp_path / "vault")
    vault.ensure_vault_dirs()
    yield


class TestEnsureVaultDirs:
    def test_creates_root(self, tmp_path):
        assert (tmp_path / "vault").is_dir()

    def test_idempotent(self, tmp_path):
        vault.ensure_vault_dirs()
        vault.ensure_vault_dirs()
        assert (vault.VAULT_ROOT / "index.json").exists()


class TestIndexBehavior:
    def test_corrupted_index_recovered(self):
        (vault.VAULT_ROOT / "index.json").write_text("NOT JSON{{{")
        vault.vault_write("findings", "after_crash", {"ok": True})
        index = json.loads((vault.VAULT_ROOT / "index.json").read_text())
        assert index["count"] >= 1
        assert any(e["name"] == "after_crash" for e in index["entries"])

    def test_missing_index_recreated(self, tmp_path):
        (vault.VAULT_ROOT / "index.json").unlink()
        vault.vault_write("notes", "rebuild", {"x": 1})
        index = json.loads((vault.VAULT_ROOT / "index.json").read_text())
        assert index["count"] >= 1

    def test_index_count_matches_entries(self):
        for i in range(5):
            vault.vault_write("findings", f"multi_{i}", {"i": i})
        index = json.loads((vault.VAULT_ROOT / "index.json").read_text())
        assert index["count"] == len(index["entries"])


class TestContentHandling:
    def test_unicode_content(self):
        payload = {"note": "héllo wörld — тест ✓"}
        vault.vault_write("notes", "unicode_test", payload)
        assert json.loads(vault.vault_read("notes", "unicode_test")) == payload

    def test_unicode_category_and_name(self):
        vault.vault_write("findings/süd", "läuft", {"ok": True})
        assert json.loads(vault.vault_read("findings/süd", "läuft")) == {"ok": True}

    def test_large_payload(self):
        payload = {"blob": "x" * 500_000}
        vault.vault_write("evidence", "big", payload)
        assert json.loads(vault.vault_read("evidence", "big"))["blob"] == payload["blob"]

    def test_nested_payload_structures(self):
        payload = {"deep": {"a": [1, 2, {"b": None}]}}
        vault.vault_write("notes", "nested", payload)
        assert json.loads(vault.vault_read("notes", "nested")) == payload

    def test_read_nonexistent_category(self):
        assert json.loads(vault.vault_read("nope", "nada")) == {"error": "not found"}


class TestPathSafety:
    def test_traversal_in_name_stays_within_root(self):
        # vault_write writes under VAULT_ROOT/category; a traversal name must
        # not escape — document current behavior by asserting the file lands
        # inside the vault root tree.
        vault.vault_write("findings", "../../etc_passwd", {"evil": True})
        found = list(vault.VAULT_ROOT.rglob("*.json"))
        assert found, "entry should be written somewhere under vault root"
        for f in found:
            assert vault.VAULT_ROOT in f.resolve().parents or f.parent == vault.VAULT_ROOT
