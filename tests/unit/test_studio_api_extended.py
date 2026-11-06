"""Tests for the extended Studio REST API routes (Phase 8).

Covers: executions (list/get/cancel/resume), findings query, MCP connections
(list/create/get/delete/test/discover), agents (CRUD/tool grants/playbook
assignments/catalog), overview, scope, and server-info endpoints.

Uses a real SQLite DBManager on tmp_path so raw-SQL handlers behave like
production. Only 127.0.0.1 is used for any address literal.
"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import pytest

from kali_mcp.db.manager import DBManager
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


def _body(payload):
    import json

    return json.dumps(payload).encode()


@pytest.fixture()
def db(tmp_path):
    manager = DBManager(tmp_path / "studio_api.sqlite")
    manager.ensure_schema()
    return manager


class TestExecutionRoutes:
    def _seed_execution(self, db, execution_id="exec_1", status="running"):
        db.create_playbook("pb.deploy", "Deploy")
        vid = db.publish_playbook_version("pb.deploy", "1.0.0", {"steps": []})
        db.create_workflow_execution(execution_id, "pb.deploy", version_id=vid, status=status)
        db.record_step_execution(
            execution_id, "s1", tool_id="nmap", step_type="tool", status="completed",
        )

    def test_list_executions(self, db):
        self._seed_execution(db, "exec_1", "completed")
        self._seed_execution(db, "exec_2", "running")
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.list_executions(FakeRequest(query_params={})))
        assert resp.status_code == 200
        data = api.json.loads(resp.body)["data"]
        assert len(data["executions"]) == 2

    def test_list_executions_status_filter(self, db):
        self._seed_execution(db, "exec_1", "completed")
        self._seed_execution(db, "exec_2", "running")
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.list_executions(FakeRequest(query_params={"status": "running"})))
        data = api.json.loads(resp.body)["data"]
        assert [e["execution_id"] for e in data["executions"]] == ["exec_2"]

    def test_get_execution_detail(self, db):
        self._seed_execution(db, "exec_1")
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.get_execution(FakeRequest(path_params={"id": "exec_1"})))
        data = api.json.loads(resp.body)["data"]
        assert data["execution"]["execution_id"] == "exec_1"
        assert len(data["steps"]) == 1
        assert data["steps"][0]["step_id"] == "s1"

    def test_get_execution_not_found(self, db):
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.get_execution(FakeRequest(path_params={"id": "missing"})))
        assert resp.status_code == 404

    def test_cancel_execution(self, db):
        self._seed_execution(db, "exec_1", "running")
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.cancel_execution(FakeRequest(path_params={"id": "exec_1"})))
        assert resp.status_code == 200
        row = db.get_workflow_execution("exec_1")
        assert row["status"] == "cancelled"

    def test_cancel_execution_not_found(self, db):
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.cancel_execution(FakeRequest(path_params={"id": "nope"})))
        assert resp.status_code == 404


class TestFindingsRoute:
    def test_query_findings_filters(self, db):
        tid = db.upsert_target("127.0.0.1", target_type="host")
        sid = db.add_scan(
            tid, "nmap", "nmap 127.0.0.1",
            "2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z", 5.0, 1, 0, None,
        )
        db.add_finding(tid, sid, "nmap", "open_port", "high", "T", "d", "e")
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.query_findings(FakeRequest(query_params={"severity": "high"})))
        data = api.json.loads(resp.body)["data"]
        assert data["count"] == 1
        assert data["findings"][0]["severity"] == "high"

    def test_query_findings_empty(self, db):
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.query_findings(FakeRequest(query_params={})))
        assert resp.status_code == 200
        data = api.json.loads(resp.body)["data"]
        assert data["count"] == 0

    def test_query_findings_bad_limit(self, db):
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.query_findings(FakeRequest(query_params={"limit": "abc"})))
        assert resp.status_code == 422


class TestConnectionRoutes:
    def _conn_body(self, **overrides):
        payload = {
            "connection_id": "conn_ext",
            "name": "External FS",
            "transport": "stdio",
            "command": "npx mcp-server-fs",
        }
        payload.update(overrides)
        return _body(payload)

    def test_create_and_list(self, db):
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.create_connection(
                FakeRequest(body=self._conn_body())))
            assert resp.status_code == 201
            resp = _run(api.list_connections(FakeRequest()))
        data = api.json.loads(resp.body)["data"]
        assert len(data["connections"]) == 1
        assert data["connections"][0]["connection_id"] == "conn_ext"

    def test_create_requires_id_and_name(self, db):
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.create_connection(FakeRequest(body=_body({"name": "x"}))))
        assert resp.status_code == 422

    def test_create_sse_requires_url(self, db):
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.create_connection(
                FakeRequest(body=self._conn_body(transport="sse", command=None))))
        assert resp.status_code == 422

    def test_create_invalid_transport(self, db):
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.create_connection(
                FakeRequest(body=self._conn_body(transport="carrier-pigeon"))))
        assert resp.status_code == 422

    def test_get_connection_with_tools(self, db):
        with patch.object(api, "_db", return_value=db):
            _run(api.create_connection(FakeRequest(body=self._conn_body())))
            resp = _run(api.get_connection(FakeRequest(path_params={"id": "conn_ext"})))
        data = api.json.loads(resp.body)["data"]
        assert data["connection"]["transport"] == "stdio"
        assert "imported_tools" in data

    def test_delete_connection(self, db):
        with patch.object(api, "_db", return_value=db):
            _run(api.create_connection(FakeRequest(body=self._conn_body())))
            resp = _run(api.delete_connection(FakeRequest(path_params={"id": "conn_ext"})))
        assert resp.status_code == 200
        assert api.json.loads(resp.body)["data"]["deleted"] is True

    def test_delete_connection_not_found(self, db):
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.delete_connection(FakeRequest(path_params={"id": "nope"})))
        assert resp.status_code == 404

    def test_test_connection_unreachable(self, db):
        with patch.object(api, "_db", return_value=db):
            _run(api.create_connection(FakeRequest(body=self._conn_body(
                transport="sse", endpoint_url="http://127.0.0.1:59999/mcp"))))
            resp = _run(api.test_connection_endpoint(
                FakeRequest(path_params={"id": "conn_ext"})))
        data = api.json.loads(resp.body)["data"]
        assert data["ok"] is False
        assert data["health_status"] == "unreachable"

    def test_test_connection_not_found(self, db):
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.test_connection_endpoint(
                FakeRequest(path_params={"id": "nope"})))
        assert resp.status_code == 404


class TestAgentRoutes:
    def test_create_and_list(self, db):
        body = _body({"profile_id": "proc", "name": "Process Agent"})
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.create_agent(FakeRequest(body=body)))
            assert resp.status_code == 201
            resp = _run(api.list_agents(FakeRequest()))
        data = api.json.loads(resp.body)["data"]
        assert len(data["agents"]) == 1
        assert data["agents"][0]["profile_id"] == "proc"

    def test_create_requires_id_and_name(self, db):
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.create_agent(FakeRequest(body=_body({"name": "x"}))))
        assert resp.status_code == 422

    def test_get_agent_includes_permissions(self, db):
        with patch.object(api, "_db", return_value=db):
            _run(api.create_agent(FakeRequest(body=_body(
                {"profile_id": "proc", "name": "A"}))))
            db.upsert_tool_definition("nmap", "nmap")
            db.grant_tool_permission("proc", "nmap", True)
            db.create_playbook("recon.basic", "Basic Recon")
            db.assign_playbook_to_profile("proc", "recon.basic", True)
            resp = _run(api.get_agent(FakeRequest(path_params={"id": "proc"})))
        data = api.json.loads(resp.body)["data"]
        assert len(data["permissions"]) == 1
        assert data["permissions"][0]["granted"] == 1
        assert len(data["assignments"]) == 1
        assert "nmap" in data["effective_catalog"]["tools"]
        assert "recon.basic" in data["effective_catalog"]["playbooks"]

    def test_get_agent_not_found(self, db):
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.get_agent(FakeRequest(path_params={"id": "ghost"})))
        assert resp.status_code == 404

    def test_update_agent(self, db):
        with patch.object(api, "_db", return_value=db):
            _run(api.create_agent(FakeRequest(body=_body(
                {"profile_id": "proc", "name": "A"}))))
            resp = _run(api.update_agent(FakeRequest(
                path_params={"id": "proc"},
                body=_body({"name": "Renamed", "max_parallel_operations": 8}),
            )))
        assert resp.status_code == 200
        assert db.get_agent_profile("proc")["name"] == "Renamed"

    def test_delete_agent(self, db):
        with patch.object(api, "_db", return_value=db):
            _run(api.create_agent(FakeRequest(body=_body(
                {"profile_id": "proc", "name": "A"}))))
            resp = _run(api.delete_agent(FakeRequest(path_params={"id": "proc"})))
        assert resp.status_code == 200
        assert db.get_agent_profile("proc") is None

    def test_tool_grant_and_revoke(self, db):
        with patch.object(api, "_db", return_value=db):
            _run(api.create_agent(FakeRequest(body=_body(
                {"profile_id": "proc", "name": "A"}))))
            _run(api.assign_agent_tool(FakeRequest(
                path_params={"id": "proc", "tool_id": "nmap"}, body=b"{}")))
            assert db.can_agent_call_tool("proc", "nmap") is True
            _run(api.unassign_agent_tool(FakeRequest(
                path_params={"id": "proc", "tool_id": "nmap"}, body=b"{}")))
            assert db.can_agent_call_tool("proc", "nmap") is False

    def test_playbook_assign_and_unassign(self, db):
        with patch.object(api, "_db", return_value=db):
            _run(api.create_agent(FakeRequest(body=_body(
                {"profile_id": "proc", "name": "A"}))))
            _run(api.assign_agent_playbook(FakeRequest(
                path_params={"id": "proc", "playbook_id": "recon.basic"}, body=b"{}")))
            assert db.is_playbook_assigned("proc", "recon.basic") is True
            _run(api.unassign_agent_playbook(FakeRequest(
                path_params={"id": "proc", "playbook_id": "recon.basic"}, body=b"{}")))
            assert db.is_playbook_assigned("proc", "recon.basic") is False

    def test_agent_catalog(self, db):
        with patch.object(api, "_db", return_value=db):
            _run(api.create_agent(FakeRequest(body=_body(
                {"profile_id": "proc", "name": "A"}))))
            resp = _run(api.agent_catalog(FakeRequest(path_params={"id": "proc"})))
        data = api.json.loads(resp.body)["data"]
        assert data["tools"] == []
        assert data["playbooks"] == []


class TestOverviewScopeServer:
    def test_overview_counts(self, db):
        tid = db.upsert_target("127.0.0.1", target_type="host")
        sid = db.add_scan(
            tid, "nmap", "nmap 127.0.0.1",
            "2026-01-01T00:00:00Z", "2026-01-01T00:01:00Z", 5.0, 1, 0, None,
        )
        db.add_finding(tid, sid, "nmap", "open_port", "high", "T", "d", "e")
        db.create_playbook("pb1", "PB1")
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.overview(FakeRequest()))
        data = api.json.loads(resp.body)["data"]
        assert data["playbooks"]["total"] == 1
        assert data["findings"]["total"] == 1
        assert data["connections"]["total"] == 0
        assert data["agents"]["total"] == 0

    def test_scope_shape(self):
        with patch.object(api, "_db", return_value=None):
            resp = _run(api.get_scope(FakeRequest()))
        data = api.json.loads(resp.body)["data"]
        for key in ("allowed_targets", "excluded_targets", "allowed_operations",
                    "policy", "is_empty", "is_expired"):
            assert key in data

    def test_server_info(self):
        with patch.object(api, "_db", return_value=None):
            resp = _run(api.get_server_info(FakeRequest()))
        data = api.json.loads(resp.body)["data"]
        for key in ("server_name", "server_version", "host", "port",
                    "auth_enabled"):
            assert key in data
