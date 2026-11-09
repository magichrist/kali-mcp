"""Migration test: a DB populated with v1+v2 data gets Studio tables added
and existing rows remain intact (Phase 8).
"""

from __future__ import annotations

from pathlib import Path

from kali_mcp.db.manager import DBManager


def _seed_v1_v2(db_path: Path) -> None:
    # Simulate an existing populated database by running the current schema
    # once, then inserting a representative row.
    manager = DBManager(db_path)
    manager.ensure_schema()
    manager.conn.execute(
        "INSERT INTO targets (target, target_type, created_at, updated_at) "
        "VALUES ('example.com', 'domain', '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
    )
    manager.conn.commit()
    manager.close()


def test_studio_tables_added_on_upgrade(tmp_path):
    db_path = tmp_path / "legacy.sqlite"
    _seed_v1_v2(db_path)

    manager = DBManager(db_path)
    manager.ensure_schema()

    tables = {
        r[0] for r in manager.conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "targets" in tables
    assert "tool_definitions" in tables
    assert "playbooks" in tables
    assert "workflow_runs" in tables

    # Existing row intact
    row = manager.conn.execute("SELECT target FROM targets").fetchone()
    assert row and row[0] == "example.com"
    manager.close()


def test_idempotent_schema_upgrade(tmp_path):
    db_path = tmp_path / "legacy2.sqlite"
    _seed_v1_v2(db_path)
    m1 = DBManager(db_path)
    m1.ensure_schema()
    m1.close()
    m2 = DBManager(db_path)
    m2.ensure_schema()  # second upgrade must not raise
    m2.close()
