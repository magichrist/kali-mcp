"""Unit tests for the SQLite persistence layer (db/manager.py)."""

from __future__ import annotations

import sqlite3

import pytest

from kali_mcp.db.manager import DBManager


@pytest.fixture()
def db(tmp_path):
    manager = DBManager(tmp_path / "test.sqlite")
    manager.ensure_schema()
    yield manager
    manager.close()


def test_schema_is_idempotent(tmp_path):
    manager = DBManager(tmp_path / "idem.sqlite")
    manager.ensure_schema()
    manager.ensure_schema()  # second call must not raise
    manager.close()


def test_all_tables_created(db):
    tables = {
        row[0] for row in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert {"targets", "scans", "findings", "credentials"} <= tables


def test_wal_mode_enabled(db):
    mode = db.conn.execute("PRAGMA journal_mode").fetchone()[0]
    assert mode.lower() == "wal"


def test_upsert_target_creates_then_updates(db):
    tid = db.upsert_target("10.0.0.5", target_type="host")
    assert tid > 0
    # Same target string → same row, updated fields
    tid2 = db.upsert_target("10.0.0.5", target_type="host", tags="web,dmz")
    assert tid2 == tid
    row = db.conn.execute("SELECT tags FROM targets WHERE id=?", (tid,)).fetchone()
    assert row["tags"] == "web,dmz"


def test_add_scan_and_finding(db):
    tid = db.upsert_target("example.com", target_type="domain")
    sid = db.add_scan(
        tid,
        "nmap",
        "nmap -q 10.0.0.5",
        "2026-10-31T00:00:00Z",
        "2026-10-31T00:00:10Z",
        10.0,
        1,
        1,
        None,
    )
    fid = db.add_finding(
        tid,
        sid,
        "nmap",
        "open_port",
        "medium",
        "SSH exposed",
        "tcp/22 open",
        "nmap output",
        port=22,
        service="ssh",
    )
    assert sid > 0 and fid > 0
    count = db.conn.execute("SELECT COUNT(*) FROM findings").fetchone()[0]
    assert count == 1


def test_finding_foreign_key_enforced(db):
    with pytest.raises(sqlite3.IntegrityError):
        db.add_finding(9999, None, "x", "t", "low", "title", "d", "e")


def test_optional_finding_fields_default_null(db):
    tid = db.upsert_target("h2")
    fid = db.add_finding(tid, None, "tool", "type", "info", "t", "d", "e")
    row = db.conn.execute("SELECT port, service, url FROM findings WHERE id=?", (fid,)).fetchone()
    assert row["port"] is None and row["service"] is None and row["url"] is None


def test_query_findings_filters_by_asset_id(db):
    tid = db.upsert_target("example.com", target_type="domain")
    other_tid = db.upsert_target("other.example.com", target_type="domain")
    db.upsert_asset("asset_example_com", "host", "example.com", target_id=tid)
    db.upsert_asset("asset_other", "host", "other.example.com", target_id=other_tid)
    sid = db.add_scan(
        tid,
        "nmap",
        "nmap -q example.com",
        "2026-10-31T00:00:00Z",
        "2026-10-31T00:00:10Z",
        10.0,
        1,
        1,
        None,
    )
    db.add_finding(
        tid,
        sid,
        "nmap",
        "open_port",
        "medium",
        "SSH exposed",
        "tcp/22 open",
        "nmap raw output",  # evidence
        port=22,
        service="ssh",
    )
    # A second target with no matching asset row must not leak in.
    other_sid = db.add_scan(
        other_tid,
        "nmap",
        "nmap -q other.example.com",
        "2026-10-31T00:00:00Z",
        "2026-10-31T00:00:10Z",
        10.0,
        1,
        1,
        None,
    )
    db.add_finding(
        other_tid,
        other_sid,
        "nmap",
        "open_port",
        "low",
        "HTTP exposed",
        "tcp/80 open",
        "nmap raw output",  # evidence
        port=80,
        service="http",
    )

    res = db.query_findings(asset_id="asset_example_com")
    assert res["count"] == 1
    assert res["findings"][0]["title"] == "SSH exposed"

    res = db.query_findings(asset_id="asset_other")
    assert res["count"] == 1
    assert res["findings"][0]["title"] == "HTTP exposed"

    res = db.query_findings(asset_id="asset_does_not_exist")
    assert res["count"] == 0
    assert res["findings"] == []
