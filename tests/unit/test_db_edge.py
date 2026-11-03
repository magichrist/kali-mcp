"""Additional DB manager tests: credentials, semantics, robustness."""

from __future__ import annotations

import sqlite3
import threading

import pytest

from kali_mcp.db.manager import DBManager


@pytest.fixture()
def db(tmp_path):
    m = DBManager(tmp_path / "t.sqlite")
    m.ensure_schema()
    yield m
    m.close()


class TestCredentials:
    def test_add_and_query_credential(self, db):
        tid = db.upsert_target("10.0.0.1")
        cid = db.add_credential(
            tid,
            service="ssh",
            username="root",
            password="toor",
            hash_value=None,
            source_tool="hydra",
        )
        assert cid > 0
        row = db.conn.execute("SELECT * FROM credentials WHERE id=?", (cid,)).fetchone()
        assert row["service"] == "ssh"
        assert row["username"] == "root"
        assert row["password"] == "toor"
        assert row["source_tool"] == "hydra"
        assert row["captured_at"]

    def test_credential_hash_only(self, db):
        tid = db.upsert_target("10.0.0.2")
        db.add_credential(
            tid,
            service="ntlm",
            username="",
            hash_value="aad3b...",
            source_tool="responder",
        )
        row = db.conn.execute("SELECT hash FROM credentials").fetchone()
        assert row["hash"] == "aad3b..."

    def test_duplicate_credentials_allowed(self, db):
        """Same cred captured twice → two rows (audit trail)."""
        tid = db.upsert_target("h")
        db.add_credential(tid, "ssh", "root", password="x", source_tool="hydra")
        db.add_credential(tid, "ssh", "root", password="x", source_tool="hydra")
        count = db.conn.execute("SELECT COUNT(*) FROM credentials").fetchone()[0]
        assert count == 2


class TestUpsertSemantics:
    def test_target_upsert_updates_all_fields(self, db):
        tid = db.upsert_target("t1", target_type="host", scope="in-scope", tags="a", notes="n1")
        db.upsert_target("t1", target_type="domain", scope="out-of-scope", tags="b", notes="n2")
        row = db.conn.execute("SELECT * FROM targets WHERE id=?", (tid,)).fetchone()
        assert row["target_type"] == "domain"
        assert row["scope"] == "out-of-scope"
        assert row["tags"] == "b"
        assert row["notes"] == "n2"

    def test_targets_unique_by_string(self, db):
        db.upsert_target("same")
        db.upsert_target("same")
        count = db.conn.execute("SELECT COUNT(*) FROM targets").fetchone()[0]
        assert count == 1


class TestScansAndFindings:
    def test_scan_findings_count_stored(self, db):
        tid = db.upsert_target("t")
        sid = db.add_scan(tid, "nmap", "nmap -q", "s", "e", 1.0, 1, 7, None)
        row = db.conn.execute("SELECT findings_count FROM scans WHERE id=?", (sid,)).fetchone()
        assert row["findings_count"] == 7

    def test_many_findings(self, db):
        tid = db.upsert_target("t")
        sid = db.add_scan(tid, "gobuster", "gobuster", "s", "e", 1.0, 1, 0, None)
        for i in range(100):
            db.add_finding(tid, sid, "gobuster", "web_path", "info", f"p{i}", "", "")
        count = db.conn.execute("SELECT COUNT(*) FROM findings WHERE scan_id=?", (sid,)).fetchone()[
            0
        ]
        assert count == 100

    def test_severity_grouping_query(self, db):
        tid = db.upsert_target("t")
        for sev in ("high", "high", "low"):
            db.add_finding(tid, None, "t", "type", sev, "title", "", "")
        rows = db.conn.execute(
            "SELECT severity, COUNT(*) FROM findings GROUP BY severity"
        ).fetchall()
        d = {r[0]: r[1] for r in rows}
        assert d == {"high": 2, "low": 1}


class TestRobustness:
    def test_close_is_idempotent(self, tmp_path):
        m = DBManager(tmp_path / "c.sqlite")
        m.ensure_schema()
        m.close()
        m.close()  # second close must not raise

    def test_wal_persists_across_connections(self, tmp_path):
        m1 = DBManager(tmp_path / "w.sqlite")
        m1.ensure_schema()
        tid = m1.upsert_target("persist-test")
        m1.close()

        m2 = DBManager(tmp_path / "w.sqlite")
        m2.ensure_schema()
        row = m2.conn.execute("SELECT target FROM targets WHERE id=?", (tid,)).fetchone()
        assert row["target"] == "persist-test"
        m2.close()

    def test_thread_safety_flag_set(self, db):
        """check_same_thread=False → cross-thread use is permitted."""
        errors = []

        def _write():
            try:
                tid = db.upsert_target("from-thread")
                db.add_scan(tid, "t", "t", "s", "e", 0, 1, 0, None)
            except Exception as e:  # noqa: BLE001
                errors.append(e)

        t = threading.Thread(target=_write)
        t.start()
        t.join()
        assert not errors

    def test_foreign_key_on_scans(self, db):
        with pytest.raises(sqlite3.IntegrityError):
            db.add_scan(99999, "tool", "cmd", "s", "e", 0, 1, 0, None)
