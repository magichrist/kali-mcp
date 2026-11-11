"""Tests for the Studio tool service layer (Phase 3, Task C)."""

from __future__ import annotations

import pytest

from kmcp.db.manager import DBManager
from kmcp.studio.service_tools import (
    PROVIDER_EXTERNAL_MCP,
    PROVIDER_NATIVE,
    enable_tool,
    get_tool_definition,
    import_external_mcp_tools_sync,
    list_tool_definitions,
    set_tool_visibility,
    sync_registry_to_db,
    upsert_tool_definition,
)


class DummyRegistryTool:
    """Minimal stand-in for a BaseTool."""

    def __init__(self, name: str, description: str = "", timeout: int = 300):
        self.name = name
        self.description = description
        self.default_timeout = timeout

    def input_schema(self):
        return {"type": "object", "properties": {}}


@pytest.fixture
def db(tmp_path):
    """Fresh DBManager using a temp sqlite file."""
    db_path = tmp_path / "test_studio.sqlite"
    m = DBManager(str(db_path))
    m.ensure_schema()
    yield m
    m.conn.close()


class TestUpsertGet:
    def test_upsert_and_get(self, db):
        row_id = upsert_tool_definition(
            db,
            tool_id="nmap",
            name="nmap",
            description="Network mapper",
            provider=PROVIDER_NATIVE,
            input_schema={"type": "object", "properties": {"target": {"type": "string"}}},
            visibility="agent_callable",
            enabled=True,
            default_timeout=300,
        )
        assert row_id > 0

        row = get_tool_definition(db, "nmap")
        assert row is not None
        assert row["tool_id"] == "nmap"
        assert row["name"] == "nmap"
        assert row["visibility"] == "agent_callable"
        assert row["enabled"] == 1

    def test_upsert_updates_existing(self, db):
        upsert_tool_definition(
            db,
            tool_id="nmap",
            name="nmap",
            description="v1",
            provider=PROVIDER_NATIVE,
            visibility="agent_callable",
        )
        row_id = upsert_tool_definition(
            db,
            tool_id="nmap",
            name="nmap",
            description="v2",
            provider=PROVIDER_NATIVE,
            visibility="internal",
        )
        row = get_tool_definition(db, "nmap")
        assert row["description"] == "v2"
        assert row["visibility"] == "internal"
        # Same row id (update, not insert)
        assert row["id"] == row_id


class TestList:
    def test_list_all(self, db):
        upsert_tool_definition(
            db, tool_id="a", name="a", provider=PROVIDER_NATIVE, visibility="agent_callable"
        )
        upsert_tool_definition(
            db, tool_id="b", name="b", provider=PROVIDER_NATIVE, visibility="internal"
        )
        rows = list_tool_definitions(db)
        assert len(rows) == 2

    def test_list_by_visibility(self, db):
        upsert_tool_definition(
            db, tool_id="a", name="a", provider=PROVIDER_NATIVE, visibility="agent_callable"
        )
        upsert_tool_definition(
            db, tool_id="b", name="b", provider=PROVIDER_NATIVE, visibility="internal"
        )
        rows = list_tool_definitions(db, visibility="internal")
        assert len(rows) == 1
        assert rows[0]["tool_id"] == "b"

    def test_list_by_enabled(self, db):
        upsert_tool_definition(
            db,
            tool_id="a",
            name="a",
            provider=PROVIDER_NATIVE,
            visibility="agent_callable",
            enabled=True,
        )
        upsert_tool_definition(
            db,
            tool_id="b",
            name="b",
            provider=PROVIDER_NATIVE,
            visibility="agent_callable",
            enabled=False,
        )
        rows = list_tool_definitions(db, enabled=True)
        assert len(rows) == 1
        assert rows[0]["tool_id"] == "a"


class TestVisibility:
    def test_set_tool_visibility(self, db):
        upsert_tool_definition(
            db, tool_id="nmap", name="nmap", provider=PROVIDER_NATIVE, visibility="agent_callable"
        )
        assert set_tool_visibility(db, "nmap", "internal") is True
        row = get_tool_definition(db, "nmap")
        assert row["visibility"] == "internal"

    def test_set_tool_visibility_unknown(self, db):
        assert set_tool_visibility(db, "nope", "internal") is False

    def test_invalid_visibility_rejected(self, db):
        with pytest.raises(ValueError, match="invalid visibility"):
            upsert_tool_definition(
                db, tool_id="x", name="x", provider=PROVIDER_NATIVE, visibility="bogus"
            )

    def test_enable_tool(self, db):
        upsert_tool_definition(
            db,
            tool_id="nmap",
            name="nmap",
            provider=PROVIDER_NATIVE,
            visibility="agent_callable",
            enabled=True,
        )
        assert enable_tool(db, "nmap", False) is True
        row = get_tool_definition(db, "nmap")
        assert row["enabled"] == 0
        assert enable_tool(db, "nope", True) is False


class TestSyncRegistryToDb:
    def test_sync_registry_to_db(self, db, monkeypatch):
        import kmcp.studio.service_tools as st

        # Monkeypatch the global registry to return our dummy tools
        dummy_tools = [DummyRegistryTool("dummy_scan", "A dummy scan tool", 120)]
        monkeypatch.setattr(st.global_registry, "list_all", lambda: dummy_tools)
        monkeypatch.setattr(st.global_registry, "get", lambda name: None)

        synced = sync_registry_to_db(db)
        assert "dummy_scan" in synced
        assert synced["dummy_scan"] > 0

        row = get_tool_definition(db, "dummy_scan")
        assert row is not None
        assert row["provider"] == PROVIDER_NATIVE
        assert row["visibility"] == "agent_callable"


class TestImportExternalMcp:
    def test_import_external_mcp_tools_sync(self, db, monkeypatch):

        # Fake client that returns tools without connecting
        class FakeClient:
            async def list_tools(self):
                return [
                    {
                        "name": "read_file",
                        "description": "Read a file",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"path": {"type": "string"}},
                        },
                    },
                    {
                        "name": "list_dir",
                        "description": "List a directory",
                        "inputSchema": {
                            "type": "object",
                            "properties": {"dir": {"type": "string"}},
                        },
                    },
                ]

        client = FakeClient()
        imported = import_external_mcp_tools_sync(db, "conn_1", client, visibility="internal")
        assert len(imported) == 2
        assert imported[0]["name"] == "read_file"
        assert imported[0]["provider"] == PROVIDER_EXTERNAL_MCP
        assert imported[0]["visibility"] == "internal"
        assert imported[0]["tool_id"] == "external_mcp:conn_1:read_file"

        # Verify in DB
        row = get_tool_definition(db, "external_mcp:conn_1:read_file")
        assert row is not None
        assert row["provider"] == PROVIDER_EXTERNAL_MCP
