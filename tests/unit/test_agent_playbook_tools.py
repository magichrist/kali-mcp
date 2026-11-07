"""Tests for agent-visible playbook tools with Studio backing (Phase 6).

Covers:
- ``PlaybookRunTool`` Studio path: assignment gating (deny-by-default),
  published-version loading, required-input validation, durable executions.
- ``PlaybookCatalogTool``: profile-scoped catalog (assigned playbooks only).
- ``PlaybookResultTool``: Studio durable execution lookup by job_id.
- ``ToolCatalogTool``: granted-only filtering under an agent profile.
- Legacy behavior preserved when no agent profile context is present.

Note: ``{{inputs.X}}`` placeholders are NOT runtime-substituted by the DAG
engine; only ``{{target}}`` (from the ``targets`` input) is. Studio runs wire
agent inputs via ``defn.inputs`` merge, and the runner sets both ``target``
and ``targets``.
"""

from __future__ import annotations

import asyncio
import json

import pytest

from kali_mcp.agent_context import agent_context
from kali_mcp.db import manager as db_manager_mod
from kali_mcp.db.manager import DBManager
from kali_mcp.tools.playbook_blackbox import JOB_REGISTRY, PlaybookRunTool
from kali_mcp.workflow import modules_runtime as mr


def _run(coro):
    return asyncio.run(coro)


def _payload_text(result: dict) -> dict:
    """Extract the JSON payload from an MCP tool result.

    Success results wrap the payload in a ``{tool, command, stdout, ...}``
    envelope; error payloads are the text content directly.
    """
    text = result["content"][0]["text"]
    outer = json.loads(text)
    if isinstance(outer, dict) and "stdout" in outer:
        return json.loads(outer["stdout"])
    return outer


@pytest.fixture(autouse=True)
def _restore_modules_runtime_state():
    """Snapshot/restore the shared module registry (see test_modules_runtime)."""
    saved_registry = dict(mr._REGISTRY)
    saved_flag = mr._BUILTIN_LOADED
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
    m = DBManager(tmp_path / "playbook_tools.sqlite")
    m.ensure_schema()
    return m


@pytest.fixture()
def patch_db(monkeypatch, db):
    monkeypatch.setattr(db_manager_mod, "get_db", lambda: db)
    return db


DEFINITION = {
    "name": "Studio Probe",
    "version": "1.0.0",
    "description": "minimal studio playbook for tool tests",
    "inputs": {
        "target": {"type": "string", "required": True, "description": "target host"},
    },
    "execution": {"max_parallel": 1, "timeout": 60},
    "steps": [
        {
            "id": "s1",
            "type": "custom",
            "tool": "test.echo_probe",
            "depends_on": [],
            "args": {"echoed": "{{target}}"},
        },
    ],
}

_SEEN_ARGS = {}  # module kwargs captured by the probe callback


def _echo_probe(ctx, **kwargs):
    _SEEN_ARGS.update(kwargs)
    return {"echoed": kwargs.get("echoed"), "ok": True}


def _seed_published(db, playbook_id="pb.studio", status="published", publish=True):
    db.create_playbook(playbook_id, "Studio Probe", status=status)
    vid = None
    if publish:
        vid = db.publish_playbook_version(playbook_id, "1.0.0", DEFINITION)
    return vid


class TestPlaybookRunStudio:
    def test_happy_path_assigned_profile_runs_and_persists(self, patch_db):
        mr.register("test.echo_probe", _echo_probe)
        _seed_published(patch_db)
        patch_db.create_agent_profile("p1", "Agent")
        patch_db.grant_tool_permission("p1", "playbook_run")
        patch_db.assign_playbook_to_profile("p1", "pb.studio")
        set_token = agent_context.set_current_profile("p1")
        try:
            tool = PlaybookRunTool()
            result = _run(tool.execute(
                {"playbook": "pb.studio", "target": "target.local"}
            ))
        finally:
            agent_context.reset_current_profile(set_token)
        out = _payload_text(result)
        assert out["status"] == "completed"
        assert out["playbook"] == "pb.studio"
        assert out["target"] == "target.local"
        assert out["version"] == "1.0.0"
        assert out["execution_id"].startswith("wexec_")
        assert out["job_id"].startswith("job_")
        assert out["summary"]["steps"] == ["s1"]
        assert len(out["summary"]["completed_steps"]) == 1
        assert "isError" not in result or result.get("isError") is not True

        # Durable records
        row = patch_db.get_workflow_execution(out["execution_id"])
        assert row is not None
        assert row["status"] == "completed"
        assert row["playbook_id"] == "pb.studio"
        assert row["profile_id"] == "p1"
        steps = patch_db.list_step_executions(out["execution_id"])
        assert [s["step_id"] for s in steps] == ["s1"]
        assert steps[0]["status"] == "completed"

        # In-memory registry stays coherent for playbook_result polling
        reg = JOB_REGISTRY[out["job_id"]]
        assert reg["status"] == "completed"
        assert reg["engine"] == "studio_dag"

        # The engine substituted {{target}} from targets
        assert _SEEN_ARGS.get("echoed") == "target.local"

    def test_detail_full_includes_step_results(self, patch_db):
        mr.register("test.echo_probe", _echo_probe)  # idempotent (same fn)
        _seed_published(patch_db)
        patch_db.create_agent_profile("p1", "Agent")
        patch_db.assign_playbook_to_profile("p1", "pb.studio")
        set_token = agent_context.set_current_profile("p1")
        try:
            result = _run(PlaybookRunTool().execute(
                {"playbook": "pb.studio", "target": "target.local", "detail": "full"}
            ))
        finally:
            agent_context.reset_current_profile(set_token)
        out = _payload_text(result)
        step_res = out["step_results"]["s1"]
        # Compute a per-step expected echo: engine substitutes {{target}}
        assert step_res["echoed"] == "target.local"

    def test_unassigned_profile_is_forbidden(self, patch_db):
        _seed_published(patch_db)
        patch_db.create_agent_profile("p1", "Agent")
        agent_context.set_current_profile("p1")
        result = _run(PlaybookRunTool().execute(
            {"playbook": "pb.studio", "target": "target.local"}
        ))
        out = _payload_text(result)
        assert result.get("isError") is True
        assert out["forbidden"] is True
        assert out["code"] == 403
        assert "not assigned" in out["error"]

    def test_missing_required_input_rejected(self, patch_db):
        _seed_published(patch_db)
        patch_db.create_agent_profile("p1", "Agent")
        patch_db.assign_playbook_to_profile("p1", "pb.studio")
        agent_context.set_current_profile("p1")
        tool = PlaybookRunTool()
        with pytest.raises(ValueError) as excinfo:
            tool.validate({"playbook": "pb.studio", "target": ""})
        assert "target is required" in str(excinfo.value)

    def test_unpublished_playbook_rejected(self, patch_db):
        _seed_published(patch_db, status="draft", publish=False)
        tool = PlaybookRunTool()
        result = _run(tool.execute(
            {"playbook": "pb.studio", "target": "target.local"}
        ))
        out = _payload_text(result)
        assert out["success"] is False
        assert "no published version" in out["error"]
        # No durable execution row is created for an invalid run
        assert patch_db.list_workflow_executions(playbook_id="pb.studio") == []

    def test_required_inputs_missing_400_style_error(self, patch_db):
        _seed_published(patch_db)
        patch_db.create_agent_profile("p1", "Agent")
        patch_db.assign_playbook_to_profile("p1", "pb.studio")
        agent_context.set_current_profile("p1")
        definition = json.loads(json.dumps(DEFINITION))
        definition["inputs"]["extra_input"] = {"type": "string", "required": True}
        patch_db.publish_playbook_version("pb.studio", "1.1.0", definition)
        result = _run(PlaybookRunTool().execute(
            {"playbook": "pb.studio", "target": "target.local"}
        ))
        out = _payload_text(result)
        assert out["success"] is False
        assert "missing required playbook inputs" in out["error"]
        assert "extra_input" in out["error"]


class TestPlaybookCatalogProfile:
    def test_profile_catalog_lists_assigned_published_only(self, patch_db):
        from kali_mcp.tools.playbook_blackbox import PlaybookCatalogTool

        _seed_published(patch_db)
        _seed_published(patch_db, "pb.revoked", )
        patch_db.create_playbook("pb.draft", "Draft pb", status="draft")
        patch_db.create_agent_profile("p1", "Agent")
        patch_db.assign_playbook_to_profile("p1", "pb.studio")
        patch_db.assign_playbook_to_profile("p1", "pb.revoked", granted=False)

        agent_context.set_current_profile("p1")
        resp = _payload_text(_run(PlaybookCatalogTool().execute({})))
        ids = [p["id"] for p in resp["playbooks"]]
        assert ids == ["pb.studio"]
        entry = resp["playbooks"][0]
        assert entry["source"] == "studio"
        assert entry["inputs"] == ["target"]
        assert resp["profile_id"] == "p1"

    def test_no_profile_context_serves_legacy_registry(self, patch_db):
        from kali_mcp.playbooks import registry as pb_registry
        from kali_mcp.tools.playbook_blackbox import PlaybookCatalogTool

        _seed_published(patch_db)  # studio playbook exists but no profile context
        resp = _payload_text(_run(PlaybookCatalogTool().execute({})))
        ids = [p["id"] for p in resp["playbooks"]]
        assert "pb.studio" not in ids
        legacy_ids = {p["id"] for p in pb_registry.list_playbooks()}
        assert set(ids) == legacy_ids


class TestPlaybookResultStudio:
    def test_serves_durable_execution_by_job_id(self, patch_db):
        from kali_mcp.tools.playbook_blackbox import PlaybookResultTool

        _seed_published(patch_db)
        execution_id = "wexec_test_0001"
        activity_job_id = "job_test_0001"
        patch_db.create_workflow_execution(
            execution_id, "pb.studio", version_id=1,
            job_id=activity_job_id, status="running",
        )
        patch_db.record_step_execution(
            execution_id, "s1", tool_id="test.echo_probe",
            step_type="custom", status="completed",
        )
        patch_db.update_workflow_execution(
            execution_id, status="completed",
            outputs={"summary": {"echoed": "target.local"}},
            completed_at="2026-01-01T00:00:00+00:00",
        )
        resp = _payload_text(_run(PlaybookResultTool().execute(
            {"job_id": activity_job_id}
        )))
        assert resp["status"] == "completed"
        assert resp["playbook"] == "pb.studio"
        assert resp["execution_id"] == execution_id
        assert resp["version_id"] == 1
        assert resp["result"]["summary"]["echoed"] == "target.local"
        assert resp["steps"][0]["step_id"] == "s1"

    def test_running_execution_signals_poll(self, patch_db):
        from kali_mcp.tools.playbook_blackbox import PlaybookResultTool

        _seed_published(patch_db)
        patch_db.create_workflow_execution(
            "wexec_running", "pb.studio", version_id=1,
            job_id="job_running", status="running",
        )
        resp = _payload_text(_run(PlaybookResultTool().execute(
            {"job_id": "job_running"}
        )))
        assert resp["status"] == "running"
        assert resp["result"] is None
        assert any("again" in a for a in resp["next_actions"])

    def test_falls_through_to_legacy_when_no_db_row(self, patch_db):
        from kali_mcp.tools.playbook_blackbox import PlaybookResultTool

        JOB_REGISTRY.clear()
        JOB_REGISTRY["job_legacy"] = {
            "job_id": "job_legacy",
            "assessment_id": "assessment_legacy",
            "status": "completed",
            "playbook": "recon",
            "result": {"summary": {"findings": 0}},
        }
        try:
            resp = _payload_text(_run(PlaybookResultTool().execute(
                {"job_id": "job_legacy"}
            )))
            assert resp["status"] == "completed"
        finally:
            JOB_REGISTRY.clear()


class TestToolCatalogProfileFiltering:
    def _catalog(self):
        from kali_mcp.tools.agent_interface import ToolCatalogTool

        return ToolCatalogTool()

    def test_granted_tools_only(self, patch_db):
        patch_db.create_agent_profile("p1", "Agent")
        patch_db.grant_tool_permission("p1", "nmap")
        patch_db.grant_tool_permission("p1", "tool_catalog")
        set_token = agent_context.set_current_profile("p1")
        try:
            resp = _payload_text(_run(self._catalog().execute({"mode": "agent"})))
        finally:
            agent_context.reset_current_profile(set_token)
        tools = resp["tools"] if "tools" in resp else resp.get("catalog", [])
        assert isinstance(tools, list)
        assert set(t["name"] for t in tools) <= {"nmap", "tool_catalog"}

    def test_no_grants_no_tools(self, patch_db):
        patch_db.create_agent_profile("p0", "Agent")
        agent_context.set_current_profile("p0")
        resp = _payload_text(_run(self._catalog().execute({"mode": "agent"})))
        tools = resp["tools"] if "tools" in resp else resp.get("catalog", [])
        assert tools == []

    def test_no_profile_context_full_default_catalog(self, patch_db):
        from kali_mcp.tools.agent_interface import AGENT_MODE_TOOLS

        resp = _payload_text(_run(self._catalog().execute({"mode": "agent"})))
        tools = resp["tools"] if "tools" in resp else resp.get("catalog", [])
        names = {t["name"] for t in tools}
        assert names == set(AGENT_MODE_TOOLS)
