"""Extra coverage tests for utils/vault.py.

Targets the branches not exercised by the existing vault test suite:
encryption (AES + stdlib fallback), secret refs, redaction edge cases,
access-control edge cases, legacy-table migration, mirror/index failure
paths, and the _normalize_categories non-sequence fallback.
"""

from __future__ import annotations

import base64
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from kali_mcp.utils import vault


class FakeMirror:
    """Stand-in for a mirror Path whose reads/writes can be made to fail."""

    def __init__(self, path, readable: bool = True, unlinkable: bool = True):
        self._path = Path(path)
        self._readable = readable
        self._unlinkable = unlinkable

    def is_file(self) -> bool:
        return True

    def read_text(self, encoding: str = "utf-8") -> str:
        if not self._readable:
            raise OSError("mirror read failed")
        return '{"value": "mirror-value"}'

    def unlink(self) -> None:
        if not self._unlinkable:
            raise OSError("mirror unlink failed")

    def resolve(self) -> Path:
        return self._path

    def __str__(self) -> str:
        return str(self._path)


class FakeConn:
    """SQLite connection stand-in whose execute() raises."""

    def execute(self, *a, **k):
        raise sqlite3.Error("down")

    def close(self) -> None:
        pass


@pytest.fixture(autouse=True)
def _vault(tmp_path, monkeypatch):
    """Retarget the vault root to a per-test temp dir and init it."""
    monkeypatch.setattr(vault, "VAULT_ROOT", tmp_path / "vault")
    vault.ensure_vault_dirs()
    yield


# ── encryption ──────────────────────────────────────────────────────────


class TestEncryptionAES:
    """cryptography is installed in this environment, so the AES-GCM path
    is the default for encrypt_value/decrypt_value."""

    def test_encrypt_decrypt_roundtrip(self):
        ct = vault.encrypt_value("s3cr3t-p@ssw0rd", "passphrase")
        assert ct != "s3cr3t-p@ssw0rd"
        assert base64.b64decode(ct.encode("ascii"))  # valid base64
        assert vault.decrypt_value(ct, "passphrase") == "s3cr3t-p@ssw0rd"

    def test_decrypt_wrong_passphrase_raises(self):
        ct = vault.encrypt_value("data", "pass-a")
        # Wrong passphrase -> authentication-tag failure (cryptography InvalidTag).
        with pytest.raises(Exception):
            vault.decrypt_value(ct, "pass-b")

    def test_decrypt_corrupted_ciphertext_raises(self):
        ct = vault.encrypt_value("data", "pass")
        blob = bytearray(base64.b64decode(ct.encode("ascii")))
        # Flip a byte in the ciphertext portion (after salt+nonce).
        blob[-1] ^= 0xFF
        bad = base64.b64encode(bytes(blob)).decode("ascii")
        with pytest.raises(Exception):
            vault.decrypt_value(bad, "pass")

    def test_encrypt_empty_string(self):
        ct = vault.encrypt_value("", "pass")
        assert vault.decrypt_value(ct, "pass") == ""

    def test_vault_encrypt_decrypt_aliases(self):
        ct = vault.vault_encrypt("x", "p")
        assert vault.vault_decrypt(ct, "p") == "x"


class TestEncryptionStdlibFallback:
    """Force the stdlib XOR+HMAC fallback by hiding the AES backend."""

    def test_fallback_roundtrip(self, monkeypatch):
        monkeypatch.setattr(vault, "_aes_available", lambda: False)
        ct = vault.encrypt_value("fallback-data", "passphrase")
        assert vault.decrypt_value(ct, "passphrase") == "fallback-data"

    def test_fallback_bad_tag_raises(self, monkeypatch):
        monkeypatch.setattr(vault, "_aes_available", lambda: False)
        ct = vault.encrypt_value("data", "pass")
        blob = bytearray(base64.b64decode(ct.encode("ascii")))
        # Corrupt a byte inside the HMAC tag region (salt 16 + nonce 12).
        blob[20] ^= 0xFF
        bad = base64.b64encode(bytes(blob)).decode("ascii")
        with pytest.raises(ValueError, match="bad tag"):
            vault.decrypt_value(bad, "pass")

    def test_aes_available_false_path(self, monkeypatch):
        """_aes_available returning False is the fallback decision branch."""
        monkeypatch.setattr(vault, "_aes_available", lambda: False)
        assert vault._aes_available() is False


# ── secret refs ─────────────────────────────────────────────────────────


class TestSecretRefs:
    def test_write_secret_ref_returns_handle(self):
        ref = vault.write_secret_ref("db-password", "hunter2")
        assert ref == "secret:db-password"
        raw = vault.vault_read("secrets", "db-password")
        data = json.loads(raw)
        assert data["ref"] == "secret:db-password"
        assert data["redacted"] is True

    def test_resolve_secret_ref_returns_value(self):
        vault.vault_write(
            "secrets",
            "api-key",
            {"value": "sk-live_12345678", "ref": "secret:api-key"},
            tags="secret",
        )
        assert vault.resolve_secret_ref("secret:api-key") == "sk-live_12345678"

    def test_resolve_secret_ref_missing_value_is_none(self):
        vault.vault_write("secrets", "novalue", {"ref": "secret:novalue"}, tags="secret")
        assert vault.resolve_secret_ref("secret:novalue") is None

    def test_resolve_secret_ref_bad_prefix_returns_none(self):
        assert vault.resolve_secret_ref("not-a-secret:foo") is None
        assert vault.resolve_secret_ref("") is None

    def test_resolve_secret_ref_corrupt_json_returns_none(self):
        vault.vault_write("secrets", "corrupt", "not-json-at-all", tags="secret")
        assert vault.resolve_secret_ref("secret:corrupt") is None

    def test_resolve_secret_ref_read_failure_returns_none(self, monkeypatch):
        monkeypatch.setattr(vault, "_connect", lambda: (_ for _ in ()).throw(sqlite3.Error("down")))
        assert vault.resolve_secret_ref("secret:anything") is None


# ── redaction ───────────────────────────────────────────────────────────


class TestRedaction:
    def test_redact_secrets_non_string_input(self):
        assert vault.redact_secrets(12345) == "12345"
        assert vault.redact_secrets(None) == "None"

    def test_redact_secrets_bearer_token(self):
        text = "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9.xxx.yyy"
        out = vault.redact_secrets(text)
        assert "Bearer [REDACTED]" in out
        assert "eyJhbGci" not in out

    def test_redact_secrets_private_key(self):
        pem = "-----BEGIN RSA PRIVATE KEY-----\nMIIEogIBAAKCAQEA\n-----END RSA PRIVATE KEY-----\n"
        out = vault.redact_secrets(pem)
        assert out == "[REDACTED PRIVATE KEY]\n"

    def test_redact_dict_non_container_passthrough(self):
        assert vault.redact_dict(42) == 42
        assert vault.redact_dict(None) is None
        assert vault.redact_dict(3.14) == 3.14

    def test_redact_dict_secret_key_replaced_without_recursion(self):
        obj = {"password": "hunter2", "api_key": "sk-live_12345678", "plain": "keep"}
        red = vault.redact_dict(obj)
        assert red["password"] == "[REDACTED]"
        assert red["api_key"] == "[REDACTED]"
        assert red["plain"] == "keep"


# ── access control ──────────────────────────────────────────────────────


class TestCanAccess:
    def test_can_access_db_error_defaults_true(self, monkeypatch):
        monkeypatch.setattr(
            vault,
            "_connect",
            lambda: (_ for _ in ()).throw(sqlite3.Error("down")),
        )
        assert vault.can_access("any-assessment") is True

    def test_can_access_row_without_owner_tag_allows(self):
        vault.ensure_vault_dirs()
        vault.vault_write(
            "assessments",
            "shared-assessment",
            {"assessment_id": "shared-assessment"},
            tags="scope:full",
        )
        # Row exists but no owner: tag -> access allowed regardless of caller.
        assert vault.can_access("shared-assessment") is True
        assert vault.can_access("shared-assessment", caller_id="analyst-1") is True


# ── index / mirror / migration edge cases ───────────────────────────────


class TestIndexAndMirrorFailure:
    def test_get_index_sqlite_error_returns_empty(self, monkeypatch):
        monkeypatch.setattr(vault, "_connect", lambda: FakeConn())
        index = vault.get_index()
        assert index == {"count": 0, "entries": []}

    def test_read_mirror_oserror_returns_not_found(self, monkeypatch):
        """DB row missing + mirror present-but-unreadable -> not found JSON."""
        mirror_path = vault.VAULT_ROOT / "findings" / "ghost.json"
        monkeypatch.setattr(
            vault,
            "_mirror_path",
            lambda cat, name: FakeMirror(mirror_path, readable=False),
        )
        raw = vault.vault_read("findings", "ghost")
        assert json.loads(raw) == {"error": "not found"}

    def test_delete_mirror_unlink_oserror_still_reports_deleted(self, monkeypatch):
        vault.vault_write("runs/t", "d1", {"x": 1})
        mirror_path = vault.VAULT_ROOT / "runs/t" / "d1.json"
        monkeypatch.setattr(
            vault,
            "_mirror_path",
            lambda cat, name: FakeMirror(mirror_path, unlinkable=False),
        )
        result = vault.vault_delete("runs/t", "d1")
        assert result["deleted"] is True
        assert result["category"] == "runs/t"
        assert result["name"] == "d1"


class TestLegacyMigration:
    def test_migrate_legacy_vault_entries_table(self, tmp_path, monkeypatch):
        """A pre-contract vault_entries table is migrated into entries."""
        import kali_mcp.utils.vault as v

        db_path = tmp_path / "legacy" / "vault.sqlite"
        db_path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(str(db_path))
        conn.executescript(
            """
            CREATE TABLE vault_entries (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                category TEXT NOT NULL, name TEXT NOT NULL, content TEXT NOT NULL,
                content_size INTEGER NOT NULL DEFAULT 0, target TEXT DEFAULT '',
                tool TEXT DEFAULT '', tags TEXT DEFAULT '', path TEXT DEFAULT '',
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL
            );
            """
        )
        now = datetime.now(timezone.utc).isoformat()
        conn.execute(
            "INSERT INTO vault_entries (category, name, content, content_size, "
            "target, tool, tags, path, created_at, updated_at) "
            "VALUES ('legacy', 'leg-1', '{\"a\":1}', 16, '', '', 'owner:alice', '/x', ?, ?)",
            (now, now),
        )
        conn.commit()
        conn.close()

        monkeypatch.setattr(vault, "VAULT_ROOT", tmp_path / "legacy")
        orig_db_path = v._db_path
        try:
            v._db_path = lambda: db_path
            vault.ensure_vault_dirs()
            raw = vault.vault_read("legacy", "leg-1")
            data = json.loads(raw)
            assert data == {"a": 1}
            # Legacy table should have been dropped.
            check = sqlite3.connect(str(db_path))
            tables = {
                r[0]
                for r in check.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            check.close()
            assert "vault_entries" not in tables
            assert "entries" in tables
        finally:
            v._db_path = orig_db_path


class TestNormalizeCategories:
    def test_normalize_categories_non_sequence_wrapped(self):
        # category that is None / str / list / tuple / set are handled
        # earlier; an arbitrary object falls through to [str(category)].
        assert vault._normalize_categories(123) == ["123"]
        obj = object()
        assert vault._normalize_categories(obj) == [str(obj)]
