"""Integration tests for the MCP resources layer (resources.py)."""

from __future__ import annotations

import json

import pytest


@pytest.fixture()
def isolated_db_vault(tmp_path, monkeypatch):
    """Point DB + vault at a temp dir for resource read tests."""
    from kali_mcp.utils import vault as v

    monkeypatch.setattr("kali_mcp.db.manager._db_singleton", None)
    monkeypatch.setattr(v, "VAULT_ROOT", tmp_path / "vault")
    v.ensure_vault_dirs()
    yield tmp_path
    monkeypatch.setattr("kali_mcp.db.manager._db_singleton", None)


def test_db_stats_resource(isolated_db_vault, monkeypatch):
    import dataclasses

    from kali_mcp import resources
    from kali_mcp.config import config as real_config
    from kali_mcp.db import manager as dbm

    new_cfg = dataclasses.replace(real_config, db_path=isolated_db_vault / "db.sqlite")
    monkeypatch.setattr("kali_mcp.db.manager.config", new_cfg)
    monkeypatch.setattr("kali_mcp.db.manager._db_singleton", None)

    db = dbm.get_db()
    db.ensure_schema()
    tid = db.upsert_target("127.0.0.1")
    db.add_scan(tid, "nmap", "nmap", "t1", "t2", 1.0, 1, 0, None)

    stats = json.loads(resources._db_stats_resource())
    assert stats["targets"] == 1
    assert stats["scans"] == 1
    assert "findings" in stats


def test_db_stats_resource_disabled(monkeypatch):
    from kali_mcp import resources
    from kali_mcp.db import manager as dbm

    monkeypatch.setattr(dbm, "get_db", lambda: None)
    stats = json.loads(resources._db_stats_resource())
    assert "error" in stats


def test_vault_index_resource(isolated_db_vault):
    from kali_mcp import resources
    from kali_mcp.utils import vault as v

    v.vault_write("findings", "r1", {"x": 1})
    index = json.loads(resources._vault_index_resource())
    assert index["count"] >= 1
    assert any(e["name"] == "r1" for e in index["entries"])
