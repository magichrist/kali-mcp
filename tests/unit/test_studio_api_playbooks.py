"""Tests for Studio REST API routes (Phase 4)."""

from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from kali_mcp.studio import api


def _run(coro):
    return asyncio.run(coro)


class FakeRequest:
    """Minimal Starlette-like request for testing handlers."""

    def __init__(self, method="GET", path_params=None, query_params=None, body=b"{}"):
        self.method = method
        self.path_params = path_params or {}
        self.query_params = query_params or {}
        self._body = body

    async def body(self):
        return self._body


class FakeDB:
    """In-memory fake DBManager for API route tests."""

    def __init__(self):
        self.playbooks = {}
        self.versions = []
        self.audit = []
        self.approvals = {}
        self.tools = {}

    def get_db(self):
        return self

    def get_playbook(self, playbook_id):
        return self.playbooks.get(playbook_id)

    def list_playbooks(self, status=None):
        rows = list(self.playbooks.values())
        if status:
            rows = [r for r in rows if r.get("status") == status]
        return rows

    def list_tool_definitions(self, provider=None, visibility=None, enabled=None):
        rows = list(self.tools.values())
        if provider:
            rows = [r for r in rows if r.get("provider") == provider]
        if visibility:
            rows = [r for r in rows if r.get("visibility") == visibility]
        if enabled is not None:
            rows = [r for r in rows if bool(r.get("enabled", True)) == bool(enabled)]
        return rows

    def get_tool_definition(self, tool_id):
        return self.tools.get(tool_id)

    def upsert_tool_definition(self, tool_id, name, **kwargs):
        self.tools[tool_id] = {"tool_id": tool_id, "name": name, **kwargs}
        return 1

    def set_tool_visibility(self, tool_id, visibility):
        if tool_id in self.tools:
            self.tools[tool_id]["visibility"] = visibility
            return True
        return False

    def create_playbook(self, playbook_id, name, **kwargs):
        self.playbooks[playbook_id] = {
            "playbook_id": playbook_id, "name": name, "status": kwargs.get("status", "draft"),
            "category": kwargs.get("category"), "description": kwargs.get("description"),
            "author": kwargs.get("author"), "is_builtin": kwargs.get("is_builtin", 0),
        }
        return 1

    def update_playbook(self, playbook_id, **fields):
        if playbook_id not in self.playbooks:
            return False
        self.playbooks[playbook_id].update(fields)
        return True

    def delete_playbook(self, playbook_id):
        if playbook_id in self.playbooks:
            del self.playbooks[playbook_id]
            return True
        return False

    def publish_playbook_version(self, playbook_id, version, definition, **kwargs):
        vid = len(self.versions) + 1
        self.versions.append({
            "id": vid, "version_id": f"{playbook_id}-{version}",
            "version": version, "playbook_id": playbook_id,
            "definition": definition, "notes": kwargs.get("notes"),
        })
        return vid

    def get_playbook_version(self, version_id):
        if isinstance(version_id, int):
            for v in self.versions:
                if v["id"] == version_id:
                    return v
            return None
        for v in self.versions:
            if v["version_id"] == version_id:
                return v
        return None

    def list_playbook_versions(self, playbook_id):
        return [v for v in self.versions if v["playbook_id"] == playbook_id]

    def record_audit(self, **kwargs):
        self.audit.append(kwargs)
        return len(self.audit)

    def upsert_approval(self, gate, resource_id, status="pending", requested_by=None):
        key = (gate, resource_id)
        self.approvals[key] = {
            "id": len(self.approvals) + 1,
            "gate": gate, "resource_id": resource_id,
            "status": status, "requested_by": requested_by,
        }
        return self.approvals[key]["id"]

    def get_pending_approval(self, gate, resource_id):
        return self.approvals.get((gate, resource_id))

    def approve(self, approval_id, approved_by, status="approved"):
        for v in self.approvals.values():
            if v["id"] == approval_id:
                v["status"] = status
                v["approved_by"] = approved_by
                return True
        return False

    def get_tool_definition(self, tool_id):
        return {"tool_id": tool_id, "name": tool_id, "visibility": "internal", "enabled": 1}

    conn = None


def _make_db_with_conn():
    """Create a fake DB with a conn attribute for SQL-based service calls."""
    db = FakeDB()

    class FakeCursor:
        def __init__(self):
            self.rows = []
            self.rowcount = 0
            self.lastrowid = 1

        def execute(self, sql, params=()):
            self.rows = []
            if "INSERT INTO playbook_validations" in sql:
                self.rowcount = 1
            elif "INSERT INTO studio_audit" in sql:
                self.rowcount = 1
                self.lastrowid = len(db.audit) + 1
            return self

        def fetchone(self):
            return None

        def fetchall(self):
            return []

    class FakeConn:
        def __init__(self):
            self.cursor = lambda: FakeCursor()
            self.committed = False

        def commit(self):
            self.committed = True

    db.conn = FakeConn()
    return db


class TestPlaybookRoutes:
    def test_list_playbooks(self):
        db = _make_db_with_conn()
        db.playbooks = {
            "pb1": {"playbook_id": "pb1", "name": "PB1", "status": "draft"},
            "pb2": {"playbook_id": "pb2", "name": "PB2", "status": "published"},
        }
        with patch("kali_mcp.studio.api._db", return_value=db):
            req = FakeRequest(query_params={"status": "draft"})
            resp = _run(api.list_playbooks(req))
            assert resp.status_code == 200
            data = resp.body.decode()
            assert "pb1" in data

    def test_create_playbook(self):
        db = _make_db_with_conn()
        with patch("kali_mcp.studio.api._db", return_value=db):
            body = b'{"playbook_id": "pb_new", "name": "New PB", "category": "recon"}'
            req = FakeRequest(method="POST", body=body)
            resp = _run(api.create_playbook(req))
            assert resp.status_code == 201
            data = resp.body.decode()
            assert "pb_new" in data

    def test_create_playbook_missing_fields(self):
        db = _make_db_with_conn()
        with patch("kali_mcp.studio.api._db", return_value=db):
            req = FakeRequest(method="POST", body=b'{"name": "No ID"}')
            resp = _run(api.create_playbook(req))
            assert resp.status_code == 422

    def test_get_playbook_not_found(self):
        db = _make_db_with_conn()
        with patch("kali_mcp.studio.api._db", return_value=db):
            req = FakeRequest(path_params={"id": "nope"})
            resp = _run(api.get_playbook(req))
            assert resp.status_code == 404

    def test_validate_playbook(self):
        db = _make_db_with_conn()
        db.playbooks = {"pb1": {"playbook_id": "pb1", "name": "PB1", "status": "draft"}}
        definition = {
            "id": "pb1", "name": "PB1", "version": "1.0.0",
            "inputs": {}, "execution": {},
            "steps": [
                {"id": "s1", "tool": "target.validate", "type": "custom",
                 "depends_on": [], "inputs": {"target": "example.com"}},
            ],
            "outputs": {},
        }
        with patch("kali_mcp.studio.api._db", return_value=db):
            body = json.dumps({"definition": definition, "for_publish": False}).encode()
            req = FakeRequest(method="POST", path_params={"id": "pb1"}, body=body)
            resp = _run(api.validate_playbook_endpoint(req))
            assert resp.status_code == 200
            assert b'"valid":true' in resp.body

    def test_publish_requires_approval(self):
        db = _make_db_with_conn()
        db.playbooks = {"pb1": {"playbook_id": "pb1", "name": "PB1", "status": "draft"}}
        definition = {
            "id": "pb1", "name": "PB1", "version": "1.0.0",
            "inputs": {}, "execution": {},
            "steps": [
                {"id": "s1", "tool": "target.validate", "type": "custom",
                 "depends_on": [], "inputs": {"target": "example.com"}},
            ],
            "outputs": {},
        }
        with patch("kali_mcp.studio.api._db", return_value=db):
            body = json.dumps({
                "version": "1.0.0",
                "definition": definition,
            }).encode()
            req = FakeRequest(method="POST", path_params={"id": "pb1"}, body=body)
            resp = _run(api.publish_playbook(req))
            assert resp.status_code == 403
            assert b"approval_required" in resp.body

    def test_export_playbook(self):
        db = _make_db_with_conn()
        db.playbooks = {
            "pb1": {"playbook_id": "pb1", "name": "PB1", "category": "recon", "status": "published"}
        }
        db.versions = [{
            "id": 1, "version_id": "pb1-1.0.0", "version": "1.0.0",
            "playbook_id": "pb1", "definition": {"id": "pb1"},
            "notes": "v1",
        }]
        with patch("kali_mcp.studio.api._db", return_value=db):
            req = FakeRequest(path_params={"id": "pb1"})
            resp = _run(api.export_playbook_endpoint(req))
            assert resp.status_code == 200
            assert b"kali-mcp-playbook-package" in resp.body

    def test_export_nonexistent(self):
        db = _make_db_with_conn()
        with patch("kali_mcp.studio.api._db", return_value=db):
            req = FakeRequest(path_params={"id": "nope"})
            resp = _run(api.export_playbook_endpoint(req))
            assert resp.status_code == 404

    def test_compile_dsl(self):
        db = _make_db_with_conn()
        dsl = '''id: pb.dsl name: "t" steps {
  s: tool nmap depends_on [] inputs { target: "10.0.0.1" }
}'''
        with patch("kali_mcp.studio.api._db", return_value=db):
            body = json.dumps({"dsl": dsl}).encode()
            req = FakeRequest(method="POST", body=body)
            resp = _run(api.compile_dsl_endpoint(req))
            assert resp.status_code == 200
            assert b'"name": "t"' in resp.body or b'"name":"t"' in resp.body

    def test_compile_dsl_invalid(self):
        db = _make_db_with_conn()
        with patch("kali_mcp.studio.api._db", return_value=db):
            body = json.dumps({"dsl": "not valid dsl at all"}).encode()
            req = FakeRequest(method="POST", body=body)
            resp = _run(api.compile_dsl_endpoint(req))
            assert resp.status_code == 422


class TestToolRoutes:
    def test_list_tools(self):
        db = _make_db_with_conn()
        with patch("kali_mcp.studio.api._db", return_value=db):
            req = FakeRequest()
            resp = _run(api.list_tools(req))
            assert resp.status_code == 200

    def test_set_tool_visibility_requires_approval(self):
        db = _make_db_with_conn()
        # No pending approval for agent_callable visibility
        with patch("kali_mcp.studio.api._db", return_value=db):
            body = json.dumps({"visibility": "agent_callable"}).encode()
            req = FakeRequest(method="PUT", path_params={"id": "nmap"}, body=body)
            resp = _run(api.set_tool_visibility_endpoint(req))
            assert resp.status_code == 403

    def test_set_tool_visibility_with_approval(self):
        db = _make_db_with_conn()
        # Pre-create an approval
        from kali_mcp.studio.approvals import request_approval
        request_approval(db, gate="visibility:agent_callable", resource_id="nmap")
        with patch("kali_mcp.studio.api._db", return_value=db):
            body = json.dumps({"visibility": "agent_callable"}).encode()
            req = FakeRequest(method="PUT", path_params={"id": "nmap"}, body=body)
            resp = _run(api.set_tool_visibility_endpoint(req))
            assert resp.status_code == 200


import json  # noqa: E402  (used above)
