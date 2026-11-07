"""Tests for POST /api/executions (start a published Studio playbook run).

Uses a real SQLite DBManager on tmp_path so execution handlers behave like
production. Only 127.0.0.1 / example-style hostnames appear as literals.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import pytest

from kali_mcp.db import manager as dbm
from kali_mcp.db.manager import DBManager
from kali_mcp.studio import api
from kali_mcp.workflow import modules_runtime as mr


def _run(coro):
    return asyncio.run(coro)


class FakeRequest:
    def __init__(self, method="GET", path_params=None, query_params=None, body=b"{}"):
        self.method = method
        self.path_params = path_params or {}
        self.query_params = query_params or {}
        self._body = body

    async def body(self):
        return self._body


def _body(payload):
    return json.dumps(payload).encode()


@pytest.fixture(autouse=True)
def _restore_modules_runtime_state():
    saved_registry = dict(mr._REGISTRY)
    saved_flag = mr._BUILTIN_LOADED
    mr.register("test.api_probe", _api_probe)
    yield
    mr._REGISTRY.clear()
    mr._REGISTRY.update(saved_registry)
    mr._BUILTIN_LOADED = saved_flag


@pytest.fixture()
def db(tmp_path):
    manager = DBManager(tmp_path / "studio_exec.sqlite")
    manager.ensure_schema()
    return manager


DEFINITION = {
    "name": "API Probe",
    "version": "1.0.0",
    "description": "minimal playbook reachable via POST /api/executions",
    "inputs": {
        "target": {"type": "string", "required": True},
    },
    "execution": {"max_parallel": 1, "timeout": 60},
    "steps": [
        {
            "id": "s1",
            "type": "custom",
            "tool": "test.api_probe",
            "depends_on": [],
            "args": {"echoed": "{{target}}"},
        },
    ],
}


_SEEN_ARGS = {}


def _api_probe(ctx, **kwargs):
    return {"echoed": kwargs.get("echoed"), "ok": True}


def _seed(db, playbook_id="pb.api", publish=True):
    db.create_playbook(playbook_id, "API Probe", status="draft")
    if publish:
        db.publish_playbook_version(playbook_id, "1.0.0", DEFINITION)
    return playbook_id


class TestStartExecutionEndpoint:
    def test_happy_path_runs_and_persists(self, db):
        _seed(db, "pb.api")
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.start_execution_endpoint(FakeRequest(
                method="POST",
                body=_body({"playbook_id": "pb.api", "inputs": {"target": "host.local"}}),
            )))
        assert resp.status_code == 200
        data = api.json.loads(resp.body)["data"]
        assert data["status"] == "completed"
        assert data["job_id"].startswith("job_")
        assert data["assessment_id"].startswith("assessment_")
        assert data["payload"]["results"] == [{"echoed": "host.local", "ok": True}]

        row = db.get_workflow_execution(
            data["execution"]["execution_id"]
        )
        assert row is not None
        assert row["status"] == "completed"
        assert row["playbook_id"] == "pb.api"
        assert row["profile_id"] is None  # no agent context in this request
        steps = db.list_step_executions(data["execution"]["execution_id"])
        assert [s["step_id"] for s in steps] == ["s1"]

    def test_missing_playbook_id_is_400(self, db):
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.start_execution_endpoint(FakeRequest(
                method="POST", body=_body({"inputs": {}}),
            )))
        assert resp.status_code == 400
        assert "playbook_id is required" in api.json.loads(resp.body)["error"]["message"]

    def test_invalid_body_is_400(self, db):
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.start_execution_endpoint(FakeRequest(
                method="POST", body=b"not-json{",
            )))
        assert resp.status_code == 400

    def test_unknown_playbook_is_404(self, db):
        _seed(db, "pb.api")
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.start_execution_endpoint(FakeRequest(
                method="POST",
                body=_body({"playbook_id": "pb.missing", "inputs": {"target": "host.local"}}),
            )))
        assert resp.status_code == 404
        assert "not found" in api.json.loads(resp.body)["error"]["message"]

    def test_unpublished_playbook_is_400(self, db):
        _seed(db, "pb.api", publish=False)
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.start_execution_endpoint(FakeRequest(
                method="POST",
                body=_body({"playbook_id": "pb.api", "inputs": {"target": "host.local"}}),
            )))
        assert resp.status_code == 400
        assert "not published" in api.json.loads(resp.body)["error"]["message"]

    def test_missing_required_input_is_400(self, db):
        _seed(db, "pb.api")
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.start_execution_endpoint(FakeRequest(
                method="POST",
                body=_body({"playbook_id": "pb.api", "inputs": {}}),
            )))
        assert resp.status_code == 400
        message = api.json.loads(resp.body)["error"]["message"]
        assert "missing required playbook inputs" in message
        assert "target" in message

    def test_specific_version_runs_that_version(self, db):
        _seed(db, "pb.api")
        definition2 = json.loads(json.dumps(DEFINITION))
        definition2["name"] = "API Probe 2"
        vid2 = db.publish_playbook_version("pb.api", "1.1.0", definition2)
        assert vid2 is not None
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.start_execution_endpoint(FakeRequest(
                method="POST",
                body=_body({"playbook_id": "pb.api", "version_id": vid2,
                            "inputs": {"target": "host.local"}}),
            )))
        assert resp.status_code == 200
        data = api.json.loads(resp.body)["data"]
        assert data["execution"]["version_id"] == vid2
        assert data["status"] in ("completed", "partial")

    def test_unknown_explicit_version_is_404(self, db):
        _seed(db, "pb.api")
        with patch.object(api, "_db", return_value=db):
            resp = _run(api.start_execution_endpoint(FakeRequest(
                method="POST",
                body=_body({"playbook_id": "pb.api", "version_id": 999999,
                            "inputs": {"target": "host.local"}}),
            )))
        assert resp.status_code == 404

    def test_profile_context_is_recorded(self, db):
        _seed(db, "pb.api")
        with patch.object(api, "_db", return_value=db):
            with patch("kali_mcp.agent_context.get_current_profile", return_value="p9"):
                resp = _run(api.start_execution_endpoint(FakeRequest(
                    method="POST",
                    body=_body({"playbook_id": "pb.api",
                                "inputs": {"target": "host.local"}}),
                )))
        assert resp.status_code == 200
        data = api.json.loads(resp.body)["data"]
        row = db.get_workflow_execution(data["execution"]["execution_id"])
        assert row["profile_id"] == "p9"


class TestExecutionsRouteTable:
    def test_post_route_registered(self):
        paths = {getattr(r, "path", "") for r in api.routes}
        assert "/api/executions" in paths
