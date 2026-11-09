"""End-to-end integration test for the Playbook Studio agent surface.

Flow: Studio DB (publish) → agent profile with assignment → MCP
``playbook_catalog`` / ``playbook_run`` / ``playbook_result`` → durable
``workflow_executions`` records — plus the enforcement boundaries
(forbidden run for an unassigned profile; denied tool for an ungranted tool).
"""

from __future__ import annotations

import asyncio
import json

import pytest

from kali_mcp.agent_context import agent_context
from kali_mcp.db import manager as db_manager_mod
from kali_mcp.db.manager import DBManager
from kali_mcp.tools.playbook_blackbox import (
    JOB_REGISTRY,
    PlaybookCatalogTool,
    PlaybookResultTool,
    PlaybookRunTool,
)
from kali_mcp.workflow import modules_runtime as mr


def _run(coro):
    return asyncio.run(coro)


def _payload_text(result: dict) -> dict:
    text = result["content"][0]["text"]
    outer = json.loads(text)
    if isinstance(outer, dict) and "stdout" in outer:
        return json.loads(outer["stdout"])
    return outer


DEFINITION = {
    "name": "Flow Probe",
    "version": "1.0.0",
    "description": "integration flow playbook",
    "inputs": {
        "target": {"type": "string", "required": True},
        "depth": {"type": "integer", "required": False, "default": 1},
    },
    "execution": {"max_parallel": 1, "timeout": 60},
    "steps": [
        {
            "id": "discover",
            "type": "custom",
            "tool": "test.flow_probe",
            "depends_on": [],
            "args": {"target_seen": "{{target}}", "depth": "{{target}}"},
        },
        {
            "id": "report",
            "type": "custom",
            "tool": "test.flow_probe",
            "depends_on": ["discover"],
            "args": {"target_seen": "done"},
        },
    ],
}

_SEEN_CALLS: list[dict] = []


def _flow_probe(ctx, **kwargs):
    _SEEN_CALLS.append(dict(kwargs))
    return {"params_seen": kwargs, "ok": True}


@pytest.fixture(autouse=True)
def _restore_modules_runtime_state():
    saved_registry = dict(mr._REGISTRY)
    saved_flag = mr._BUILTIN_LOADED
    mr.register("test.flow_probe", _flow_probe)
    yield
    mr._REGISTRY.clear()
    mr._REGISTRY.update(saved_registry)
    mr._BUILTIN_LOADED = saved_flag


@pytest.fixture(autouse=True)
def _clear_profile_ctx():
    token = agent_context.set_current_profile(None)
    yield
    agent_context.reset_current_profile(token)


@pytest.fixture()
def db(tmp_path):
    m = DBManager(tmp_path / "studio_flow.sqlite")
    m.ensure_schema()
    return m


@pytest.fixture()
def patch_db(monkeypatch, db):
    monkeypatch.setattr(db_manager_mod, "get_db", lambda: db)
    return db


def _seed(db):
    db.create_playbook("pb.flow", "Flow Probe", status="draft")
    db.publish_playbook_version("pb.flow", "1.0.0", DEFINITION)
    db.create_agent_profile("agent-1", "Ops agent")
    db.grant_tool_permission("agent-1", "playbook_catalog")
    db.grant_tool_permission("agent-1", "playbook_run")
    db.grant_tool_permission("agent-1", "playbook_result")
    db.assign_playbook_to_profile("agent-1", "pb.flow")


def test_full_studio_flow_publish_catalog_run_result(patch_db):
    _seed(patch_db)
    _SEEN_CALLS.clear()

    set_token = agent_context.set_current_profile("agent-1")
    try:
        # 1. Catalog shows only the assigned published playbook
        catalog = _payload_text(_run(PlaybookCatalogTool().execute({})))
        assert catalog["profile_id"] == "agent-1"
        assert [p["id"] for p in catalog["playbooks"]] == ["pb.flow"]
        assert catalog["playbooks"][0]["inputs"] == ["depth", "target"]

        # 2. Run through the DAG engine (MCP contract, Studio backing)
        run_res = _run(
            PlaybookRunTool().execute({"playbook": "pb.flow", "target": "flow.example.org"})
        )
        run = _payload_text(run_res)
        assert run["status"] == "completed"
        assert run["playbook"] == "pb.flow"
        assert run["version"] == "1.0.0"
        assert run["target"] == "flow.example.org"

        # 3. Durable records exist with per-step rows
        row = patch_db.get_workflow_execution(run["execution_id"])
        assert row["status"] == "completed"
        assert row["job_id"] == run["job_id"]
        assert row["profile_id"] == "agent-1"
        steps = patch_db.list_step_executions(run["execution_id"])
        assert [s["step_id"] for s in steps] == ["discover", "report"]
        assert all(s["status"] == "completed" for s in steps)

        # 4. playbook_result serves the durable execution by job_id
        result = _payload_text(_run(PlaybookResultTool().execute({"job_id": run["job_id"]})))
        assert result["status"] == "completed"
        assert result["engine"] == "studio_dag"
        assert result["execution_id"] == run["execution_id"]
        assert result["result"]["summary"]["steps"] == ["discover", "report"]
        assert [s["step_id"] for s in result["steps"]] == ["discover", "report"]
    finally:
        agent_context.reset_current_profile(set_token)

    # 5. `{{target}}` substitution reached the custom module's step args
    assert _SEEN_CALLS[0].get("target_seen") == "flow.example.org"
    assert _SEEN_CALLS[1].get("target_seen") == "done"


def test_unassigned_profile_cannot_run_flow(patch_db):
    _seed(patch_db)
    patch_db.create_agent_profile("agent-2", "Restricted")
    patch_db.grant_tool_permission("agent-2", "playbook_run")

    set_token = agent_context.set_current_profile("agent-2")
    try:
        # Catalog is empty for this profile (no assignments)
        catalog = _payload_text(_run(PlaybookCatalogTool().execute({})))
        assert catalog["playbooks"] == []

        # Running the assigned-to-others playbook is forbidden
        run_res = _run(
            PlaybookRunTool().execute({"playbook": "pb.flow", "target": "flow.example.org"})
        )
        out = _payload_text(run_res)
        assert run_res.get("isError") is True
        assert out["forbidden"] is True
        assert out["code"] == 403
        assert "agent-2" in out["error"]

        # And nothing durable was recorded for the denied run
        assert patch_db.list_workflow_executions(playbook_id="pb.flow") == []
    finally:
        agent_context.reset_current_profile(set_token)


def test_no_agent_context_unchanged_legacy_surface(patch_db):
    """No X-Agent-Profile header / no token binding → legacy behavior."""
    _seed(patch_db)
    _SEEN_CALLS.clear()
    assert agent_context.get_current_profile() is None

    # Catalog serves the legacy black-box registry, not the Studio playbook
    catalog = _payload_text(_run(PlaybookCatalogTool().execute({})))
    assert "pb.flow" not in {p["id"] for p in catalog["playbooks"]}

    # Studio playbook ids are resolved via the Studio path — operator context
    run_res = _run(PlaybookRunTool().execute({"playbook": "pb.flow", "target": "flow.example.org"}))
    run = _payload_text(run_res)
    assert run["status"] == "completed"
    row = patch_db.get_workflow_execution(run["execution_id"])
    assert row["profile_id"] is None

    # Registry entry is queryable immediately
    reg = JOB_REGISTRY[run["job_id"]]
    assert reg["status"] == "completed"

    # Legacy black-box playbooks still validate on the old path
    tool = PlaybookRunTool()
    with pytest.raises(ValueError) as excinfo:
        tool.validate({"playbook": "definitely_not_real", "target": "x.example.org"})
    assert "unknown playbook" in str(excinfo.value)
