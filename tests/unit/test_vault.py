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


def test_redact_secrets_scrubs_key_value():
    text = vault.redact_secrets('api_key=sk-12345678 password=longpassword99 token=abcdefghij')
    assert "[REDACTED]" in text
    assert "sk-12345678" not in text
    assert "longpassword99" not in text


def test_redact_dict_nested():
    obj = {"data": {"credentials": {"password": "secret12345", "token": "abcdefghij"}}, "name": "tool"}
    red = vault.redact_dict(obj)
    assert red["data"]["credentials"]["password"] == "[REDACTED]"
    assert red["data"]["credentials"]["token"] == "[REDACTED]"
    assert red["name"] == "tool"


def test_redact_dict_list():
    obj = {"items": [{"password": "secret1"}, {"password": "secret2"}]}
    red = vault.redact_dict(obj)
    assert red["items"][0]["password"] == "[REDACTED]"
    assert red["items"][1]["password"] == "[REDACTED]"


def test_can_access_default_allows():
    # No owner recorded -> access allowed (backwards compatible).
    assert vault.can_access("assessment_no_owner") is True


def test_can_access_respects_owner(monkeypatch, tmp_path):
    # Point the vault at a temp db so we can record an owner tag.
    import importlib
    import kali_mcp.utils.vault as v

    orig_db_path = v._db_path
    try:
        v._db_path = lambda: tmp_path / "vault.sqlite"
        v.ensure_vault_dirs()
        v.vault_write(
            "assessments", "owned-assessment",
            {"assessment_id": "owned-assessment"}, tags="owner:analyst-1",
        )
        assert v.can_access("owned-assessment", caller_id="analyst-1") is True
        assert v.can_access("owned-assessment", caller_id="analyst-2") is False
        assert v.can_access("owned-assessment") is True  # None caller allowed
    finally:
        v._db_path = orig_db_path
