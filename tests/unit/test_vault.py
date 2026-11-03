"""Unit tests for the plaintext inter-agent vault (utils/vault.py)."""

from __future__ import annotations

import json

from kali_mcp.utils import vault


def test_write_and_read_roundtrip():
    vault.ensure_vault_dirs()
    payload = {"host": "10.0.0.1", "port": 22, "service": "ssh"}
    vault.vault_write("findings", "test_ssh", payload)

    raw = vault.vault_read("findings", "test_ssh")
    assert json.loads(raw) == payload


def test_index_updated_on_write():
    vault.ensure_vault_dirs()
    vault.vault_write("notes", "test_index_entry", {"k": "v"})

    index = json.loads((vault.VAULT_ROOT / "index.json").read_text())
    assert index["count"] == len(index["entries"])
    assert any(
        e["category"] == "notes" and e["name"] == "test_index_entry" for e in index["entries"]
    )


def test_read_missing_returns_error_json():
    result = json.loads(vault.vault_read("findings", "definitely_missing"))
    assert result == {"error": "not found"}


def test_write_overwrites_existing_entry():
    vault.ensure_vault_dirs()
    vault.vault_write("notes", "test_overwrite", {"v": 1})
    vault.vault_write("notes", "test_overwrite", {"v": 2})

    assert json.loads(vault.vault_read("notes", "test_overwrite")) == {"v": 2}
