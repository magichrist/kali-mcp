"""Unit tests for db/manager.py edge cases (close, add_credential, _now, upsert)."""

from __future__ import annotations

import sqlite3
from unittest.mock import patch

import pytest

from kali_mcp.db.manager import DBManager, get_db


class TestDBManagerEdgeCases:
    def test_close(self, tmp_path) -> None:
        db = DBManager(tmp_path / "test.sqlite")
        db.ensure_schema()
        db.close()
        # Connection should be closed; executing should raise
        with pytest.raises(sqlite3.ProgrammingError):
            db.conn.execute("SELECT 1")

    def test_add_credential(self, tmp_path) -> None:
        db = DBManager(tmp_path / "test.sqlite")
        db.ensure_schema()
        tid = db.upsert_target("127.0.0.1", target_type="host")
        cid = db.add_credential(
            target_id=tid,
            service="ssh",
            username="admin",
            password="secret",
            hash_value="abc123",
            source_tool="hydra",
            notes="test cred",
        )
        assert isinstance(cid, int)
        row = db.conn.execute("SELECT * FROM credentials WHERE id = ?", (cid,)).fetchone()
        assert row is not None
        assert row["service"] == "ssh"
        assert row["username"] == "admin"
        db.close()

    def test_upsert_target_updates_existing(self, tmp_path) -> None:
        db = DBManager(tmp_path / "test.sqlite")
        db.ensure_schema()
        tid1 = db.upsert_target("127.0.0.1", target_type="host", tags="web")
        tid2 = db.upsert_target("127.0.0.1", target_type="host", tags="updated")
        assert tid1 == tid2  # same target → same id
        row = db.conn.execute("SELECT tags FROM targets WHERE id = ?", (tid1,)).fetchone()
        assert row["tags"] == "updated"
        db.close()

    def test_add_scan_and_finding(self, tmp_path) -> None:
        db = DBManager(tmp_path / "test.sqlite")
        db.ensure_schema()
        tid = db.upsert_target("example.com", target_type="domain")
        sid = db.add_scan(
            target_id=tid,
            tool="nmap",
            command="nmap -sT example.com",
            started_at="2026-01-01T00:00:00Z",
            completed_at="2026-01-01T00:00:05Z",
            duration=5.0,
            success=1,
            findings_count=2,
            artifact_uri=None,
        )
        fid = db.add_finding(
            target_id=tid,
            scan_id=sid,
            tool="nmap",
            finding_type="open_port",
            severity="informational",
            title="Port 80/tcp open",
            description="HTTP service",
            evidence="80/tcp open",
            port=80,
            service="http",
            url="http://example.com",
        )
        assert isinstance(sid, int)
        assert isinstance(fid, int)
        db.close()

    def test_get_db_returns_singleton(self) -> None:
        # get_db caches the singleton; calling twice returns same object
        from kali_mcp.db import manager as dbm

        original = dbm._db_singleton
        dbm._db_singleton = None
        try:
            with patch.object(dbm, "config") as mock_config:
                mock_config.db_enabled = True
                import tempfile

                mock_config.db_path = str(tempfile.mkdtemp()) + "/singleton.sqlite"
                db1 = get_db()
                db2 = get_db()
                assert db1 is db2
        finally:
            dbm._db_singleton = original
