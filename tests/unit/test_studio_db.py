"""Unit tests for Playbook Studio schema extensions in src/kali_mcp/db/manager.py.

Covers: idempotent creation of the Studio tables defined in
docs/visual/02_DATA_MODEL.md §3, preservation of existing v1+v2 tables and
data across re-migration, and CRUD round-trips for the §4 helper methods
(tool definitions, agent profiles + permissions, playbook lifecycle with
versions, workflow executions + step executions, validations, audit,
approval gates).
"""

from __future__ import annotations

import json

import pytest

from kali_mcp.db.manager import DBManager

STUDIO_TABLES = [
    "tool_definitions",
    "mcp_connections",
    "agent_profiles",
    "agent_tool_permissions",
    "agent_playbook_assignments",
    "playbooks",
    "playbook_versions",
    "workflow_nodes",
    "workflow_edges",
    "workflow_executions",
    "workflow_step_executions",
    "playbook_validations",
    "studio_audit",
    "pending_approvals",
]

STUDIO_INDEXES = [
    "idx_tool_defs_provider",
    "idx_tool_defs_visibility",
    "idx_tool_defs_enabled",
    "idx_mcp_conn_health",
    "idx_agent_profiles_id",
    "idx_agent_tool_perm_profile",
    "idx_agent_playbook_assign_profile",
    "idx_playbooks_status",
    "idx_playbooks_builtin",
    "idx_playbook_versions_playbook",
    "idx_playbook_versions_version",
    "idx_workflow_nodes_version",
    "idx_workflow_edges_version",
    "idx_workflow_exec_status",
    "idx_workflow_exec_playbook",
    "idx_workflow_exec_job",
    "idx_step_exec_execution",
    "idx_playbook_validations_version",
]

EXPECTED_TOOL_ROW = {
    "tool_id": "nmap",
    "name": "Nmap",
    "provider": "native",
    "visibility": "agent_callable",
    "requires_binary": "nmap",
}


@pytest.fixture()
def db(tmp_path):
    manager = DBManager(tmp_path / "studio.sqlite")
    manager.ensure_schema()
    yield manager
    manager.close()


def _table_count(db, table):
    return db.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


# ── schema creation & idempotency ────────────────────────────────────────


class TestStudioSchemaCreation:
    def test_ensure_schema_creates_all_studio_tables(self, db):
        names = {
            r[0]
            for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='table'").fetchall()
        }
        for table in STUDIO_TABLES:
            assert table in names

    def test_ensure_schema_creates_all_studio_indexes(self, db):
        names = {
            r[0]
            for r in db.conn.execute("SELECT name FROM sqlite_master WHERE type='index'").fetchall()
        }
        for index in STUDIO_INDEXES:
            assert index in names

    def test_ensure_schema_is_idempotent(self, db):
        seed_tid = db.upsert_target("127.0.0.1", target_type="host")
        tool_id = db.upsert_tool_definition("idem-tool", "Idem Tool")

        for _ in range(3):
            db.ensure_schema()  # must not raise

        for table in STUDIO_TABLES + ["targets", "scans", "findings", "credentials"]:
            assert _table_count(db, table) >= 0

        assert db.get_tool_definition("idem-tool")["id"] == tool_id
        assert (
            db.conn.execute("SELECT id FROM targets WHERE id = ?", (seed_tid,)).fetchone()
            is not None
        )


# ── existing v1+v2 data preserved across migration ───────────────────────


class TestExistingDataPreserved:
    @staticmethod
    def _seed_existing(db):
        """Populate v1 and v2 tables using the pre-Studio helper APIs."""
        tid = db.upsert_target("127.0.0.1", target_type="host", tags="seeded")
        sid = db.add_scan(
            tid,
            "nmap",
            "nmap -sT 127.0.0.1",
            "2026-01-01T00:00:00Z",
            "2026-01-01T00:00:05Z",
            5.0,
            1,
            1,
            None,
            assessment_id="assess_seed",
            job_id="job_seed",
            workflow_name="recon",
        )
        fid = db.add_finding(
            tid,
            sid,
            "nmap",
            "open_port",
            "high",
            "SSH exposed",
            "tcp/22 open",
            "nmap output",
            port=22,
            service="ssh",
            source_tools='["nmap"]',
        )
        cid = db.add_credential(tid, "ssh", "root", password="s3cret", source_tool="nmap")
        aid = db.upsert_asset(
            asset_id="asset_127.0.0.1",
            asset_type="host",
            name="127.0.0.1",
            target_id=tid,
        )
        evid = db.add_evidence_artifact(
            "evidence_seed", "nmap", "127.0.0.1", "stdout", "/tmp/out.txt"
        )
        return {
            "targets": tid,
            "scans": sid,
            "findings": fid,
            "credentials": cid,
            "assets": aid,
            "evidence_artifacts": evid,
        }

    def test_re_migration_keeps_every_prewritten_row(self, db):
        ids = self._seed_existing(db)
        tables = ["targets", "scans", "findings", "credentials", "assets", "evidence_artifacts"]

        before = {t: [dict(r) for r in db.conn.execute(f"SELECT * FROM {t}")] for t in tables}
        db.ensure_schema()  # migrate again on a populated database

        for table in tables:
            after = [dict(r) for r in db.conn.execute(f"SELECT * FROM {table}")]
            assert after == before[table]

        row = db.conn.execute("SELECT * FROM targets WHERE id = ?", (ids["targets"],)).fetchone()
        assert row["target"] == "127.0.0.1"
        assert row["tags"] == "seeded"

        scan = db.conn.execute(
            "SELECT assessment_id, job_id, workflow_name FROM scans WHERE id = ?",
            (ids["scans"],),
        ).fetchone()
        assert scan["assessment_id"] == "assess_seed"
        assert scan["job_id"] == "job_seed"
        assert scan["workflow_name"] == "recon"


# ── tool definition helpers ──────────────────────────────────────────────


class TestToolDefinitions:
    def test_upsert_insert_then_update_round_trip(self, db):
        tdid = db.upsert_tool_definition(
            "nmap",
            "Nmap",
            description="Port scanner",
            visibility="agent_callable",
            requires_binary="nmap",
            input_schema={"type": "object"},
            output_schema={"type": "object"},
            scope_required=True,
        )
        assert tdid > 0
        row = db.get_tool_definition("nmap")
        assert row["id"] == tdid
        for key, value in EXPECTED_TOOL_ROW.items():
            assert row[key] == value
        assert row["enabled"] == 1
        assert row["scope_required"] == 1
        assert json.loads(row["input_schema"]) == {"type": "object"}
        assert row["created_at"] is not None

        # Same tool_id updates in place (same row id).
        updated = db.upsert_tool_definition("nmap", "Nmap v2", visibility="internal")
        assert updated == tdid
        row = db.get_tool_definition("nmap")
        assert row["name"] == "Nmap v2"
        assert row["visibility"] == "internal"

    def test_list_filters(self, db):
        db.upsert_tool_definition("nmap", "Nmap", provider="native", visibility="agent_callable")
        db.upsert_tool_definition(
            "mcp:github:search_repos", "Search Repos", provider="external_mcp"
        )
        db.upsert_tool_definition("disabled-check", "Disabled", provider="native", enabled=False)

        by_provider = db.list_tool_definitions(provider="external_mcp")
        assert [r["tool_id"] for r in by_provider] == ["mcp:github:search_repos"]
        assert len(db.list_tool_definitions(visibility="agent_callable")) == 1
        assert [r["tool_id"] for r in db.list_tool_definitions(enabled=False)] == ["disabled-check"]
        assert len(db.list_tool_definitions()) == 3

    def test_delete_returns_membership(self, db):
        db.upsert_tool_definition("nmap", "Nmap")
        assert db.delete_tool_definition("nmap") is True
        assert db.get_tool_definition("nmap") is None
        assert db.delete_tool_definition("nmap") is False


# ── agent profiles, permissions, assignments ─────────────────────────────


class TestAgentProfiles:
    def test_create_and_update_round_trip(self, db):
        pid = db.create_agent_profile(
            "profile_recon",
            "Recon Agent",
            description="Scoped recon",
            allowed_scopes=["scope_1"],
        )
        row = db.get_agent_profile("profile_recon")
        assert row["id"] == pid
        assert row["max_parallel_operations"] == 4
        assert json.loads(row["allowed_scopes"]) == ["scope_1"]

        # Re-create with same profile_id updates rather than raising.
        db.create_agent_profile("profile_recon", "Recon Agent v2", max_parallel_operations=8)
        row = db.get_agent_profile("profile_recon")
        assert row["name"] == "Recon Agent v2"
        assert row["max_parallel_operations"] == 8

        # Partial update keeps omitted fields.
        assert db.update_agent_profile("profile_recon", description="Updated") is True
        row = db.get_agent_profile("profile_recon")
        assert row["description"] == "Updated"
        assert row["name"] == "Recon Agent v2"
        assert db.update_agent_profile("profile_missing", name="nope") is False

        assert [p["profile_id"] for p in db.list_agent_profiles()] == ["profile_recon"]

    def test_permission_grant_deny_revoke(self, db):
        db.create_agent_profile("profile_recon", "Recon Agent")

        # Deny-by-default: no permission row means no call allowed.
        assert db.can_agent_call_tool("profile_recon", "nmap") is False

        db.grant_tool_permission("profile_recon", "nmap")
        assert db.can_agent_call_tool("profile_recon", "nmap") is True

        # Explicit deny.
        db.grant_tool_permission("profile_recon", "nmap", granted=False)
        assert db.can_agent_call_tool("profile_recon", "nmap") is False

        # Revoke removes the row; back to deny-by-default.
        db.grant_tool_permission("profile_recon", "nmap")
        db.revoke_tool_permission("profile_recon", "nmap")
        assert db.can_agent_call_tool("profile_recon", "nmap") is False

    def test_playbook_assignment(self, db):
        db.create_playbook("pb_recon", "Recon Playbook")
        assert db.is_playbook_assigned("profile_recon", "pb_recon") is False
        db.assign_playbook_to_profile("profile_recon", "pb_recon")
        assert db.is_playbook_assigned("profile_recon", "pb_recon") is True
        db.unassign_playbook_from_profile("profile_recon", "pb_recon")
        assert db.is_playbook_assigned("profile_recon", "pb_recon") is False

    def test_delete_profile_cascades(self, db):
        db.create_agent_profile("profile_recon", "Recon Agent")
        db.grant_tool_permission("profile_recon", "nmap")
        db.assign_playbook_to_profile("profile_recon", "pb_recon")

        assert db.delete_agent_profile("profile_recon") is True
        assert db.get_agent_profile("profile_recon") is None
        assert _table_count(db, "agent_tool_permissions") == 0
        assert _table_count(db, "agent_playbook_assignments") == 0
        assert db.delete_agent_profile("profile_recon") is False


# ── playbooks & versions ─────────────────────────────────────────────────


class TestPlaybooks:
    def test_playbook_crud_round_trip(self, db):
        pbid = db.create_playbook("pb_recon", "Recon", category="recon", author="ops")
        row = db.get_playbook("pb_recon")
        assert row["id"] == pbid
        assert row["status"] == "draft"
        assert row["is_builtin"] == 0

        assert db.update_playbook("pb_recon", status="validated") is True
        assert db.get_playbook("pb_recon")["status"] == "validated"
        assert db.update_playbook("pb_missing", status="draft") is False

        db.create_playbook("pb_published", "Published Playbook")
        db.publish_playbook_version("pb_published", "1.0.0", {"steps": []})
        assert [p["playbook_id"] for p in db.list_playbooks(status="published")] == ["pb_published"]
        assert db.get_playbook("pb_recon")["status"] == "validated"

        assert db.delete_playbook("pb_recon") is True
        assert db.get_playbook("pb_recon") is None
        assert db.delete_playbook("pb_recon") is False

    def test_publish_versions_append_only_and_rollback_read(self, db):
        db.create_playbook("pb_scan", "Scan Playbook")

        v1_id = db.publish_playbook_version(
            "pb_scan",
            "1.0.0",
            definition={"playbook": "pb_scan", "steps": ["step1"]},
            notes="initial",
            published_by="ops",
        )
        v2_id = db.publish_playbook_version(
            "pb_scan",
            "1.1.0",
            definition={"playbook": "pb_scan", "steps": ["seq1-1", "seq1-2"]},
            published_by="ops",
        )
        assert v1_id != v2_id

        pb = db.get_playbook("pb_scan")
        assert pb["status"] == "published"
        assert pb["current_version_id"] == v2_id

        versions = db.list_playbook_versions("pb_scan")
        assert [v["version"] for v in versions] == ["1.0.0", "1.1.0"]
        assert [v["id"] for v in versions] == [v1_id, v2_id]

        # Rollback-read: the older version remains readable and immutable.
        v1 = db.get_playbook_version(v1_id)
        assert v1["definition"] == json.dumps({"playbook": "pb_scan", "steps": ["step1"]})
        assert v1["published_by"] == "ops"
        assert db.get_playbook_version("pb_scan-1.0.0")["id"] == v1_id

        # Republishing the same semver never mutates existing rows.
        republished = db.publish_playbook_version(
            "pb_scan", "1.1.0", definition={"playbook": "pb_scan"}
        )
        assert republished not in (v1_id, v2_id)
        assert db.get_playbook_version(v2_id)["definition"] == json.dumps(
            {"playbook": "pb_scan", "steps": ["seq1-1", "seq1-2"]}
        )


# ── workflow executions & steps ──────────────────────────────────────────


class TestWorkflowExecutions:
    def test_execution_and_step_round_trip(self, db):
        db.create_playbook("pb_scan", "Scan Playbook")
        vid = db.publish_playbook_version("pb_scan", "1.0.0", {"steps": []})

        exec_id = "exec_abc123"
        wid = db.create_workflow_execution(
            exec_id,
            playbook_id="pb_scan",
            version_id=vid,
            job_id="job_seed",
            assessment_id="assess_seed",
            profile_id="profile_recon",
            inputs={"target": "127.0.0.1"},
        )
        assert wid > 0

        row = db.get_workflow_execution(exec_id)
        assert row["id"] == wid
        assert row["status"] == "running"
        assert json.loads(row["inputs"]) == {"target": "127.0.0.1"}
        assert row["completed_at"] is None

        # Re-calling create with the same execution_id is a no-op.
        assert db.create_workflow_execution(exec_id, playbook_id="pb_scan", version_id=vid) == wid
        assert db.get_workflow_execution(exec_id)["started_at"] == row["started_at"]

        # Record two steps, complete the first.
        sid1 = db.record_step_execution(
            exec_id,
            "step-1",
            step_type="tool",
            tool_id="nmap",
            status="running",
            inputs={"args": "-sT"},
            started_at="2026-01-01T00:00:01Z",
        )
        db.record_step_execution(exec_id, "step-2", step_type="output")
        db.update_step_execution(
            sid1,
            status="completed",
            outputs={"ports": [22, 80]},
            completed_at="2026-01-01T00:00:04Z",
            duration_ms=3000,
        )
        steps = db.list_step_executions(exec_id)
        assert [s["step_id"] for s in steps] == ["step-1", "step-2"]
        assert steps[0]["status"] == "completed"
        assert json.loads(steps[0]["outputs"]) == {"ports": [22, 80]}
        assert steps[0]["duration_ms"] == 3000
        assert db.update_step_execution(99999, status="completed") is False

        # Complete the execution with outputs, filter listings.
        assert (
            db.update_workflow_execution(
                exec_id,
                status="completed",
                outputs={"result": "done"},
                completed_at="2026-01-01T00:00:05Z",
            )
            is True
        )
        row = db.get_workflow_execution(exec_id)
        assert row["status"] == "completed"
        assert json.loads(row["outputs"]) == {"result": "done"}

        db.create_workflow_execution("exec_failed", playbook_id="pb_scan", version_id=vid)
        db.update_workflow_execution("exec_failed", status="failed", error="boom")
        assert [e["execution_id"] for e in db.list_workflow_executions(status="failed")] == [
            "exec_failed"
        ]
        assert len(db.list_workflow_executions(playbook_id="pb_scan")) == 2
        assert len(db.list_workflow_executions(job_id="job_seed")) == 1
        assert db.update_workflow_execution("exec_missing", status="failed") is False


# ── validations, audit, approvals ────────────────────────────────────────


class TestValidationsAuditApprovals:
    def test_record_validation(self, db):
        db.create_playbook("pb_scan", "Scan Playbook")
        rid = db.record_validation(
            playbook_id="pb_scan",
            status="invalid",
            errors=[{"step_id": "step-1", "field": "tool_id", "message": "unknown tool"}],
            validated_by="validator",
        )
        row = db.conn.execute("SELECT * FROM playbook_validations WHERE id = ?", (rid,)).fetchone()
        assert row["playbook_id"] == "pb_scan"
        assert row["status"] == "invalid"
        assert json.loads(row["errors"])[0]["field"] == "tool_id"
        assert row["validated_at"] is not None

    def test_record_audit(self, db):
        rid = db.record_audit(
            "playbook.published",
            entity_type="playbook",
            entity_id="pb_scan",
            actor="ops",
            data={"version": "1.0.0"},
        )
        row = db.conn.execute("SELECT * FROM studio_audit WHERE id = ?", (rid,)).fetchone()
        assert row["event"] == "playbook.published"
        assert row["entity_id"] == "pb_scan"
        assert json.loads(row["data"]) == {"version": "1.0.0"}
        assert row["created_at"] is not None

    def test_approval_gate_round_trip(self, db):
        aid = (
            db.upsert_approval("aggressive_execution", tool="mcp:x", requested_by="agent_1")
            if False
            else db.upsert_approval("aggressive_execution", "tool:mcp:x", requested_by="agent_1")
        )
        pending = db.get_pending_approval("aggressive_execution", "tool:mcp:x")
        assert pending["id"] == aid
        assert pending["status"] == "pending"
        assert pending["requested_by"] == "agent_1"
        assert pending["approved_by"] is None

        assert db.approve(aid, "admin") is True
        pending = db.get_pending_approval("aggressive_execution", "tool:mcp:x")
        assert pending is None

        row = db.conn.execute("SELECT * FROM pending_approvals WHERE id = ?", (aid,)).fetchone()
        assert row["status"] == "approved"
        assert row["approved_by"] == "admin"
        assert row["approved_at"] is not None

    def test_upsert_approval_refreshes_pending_row(self, db):
        aid1 = db.upsert_approval("import_activation", "import:pkg1")
        aid2 = db.upsert_approval("import_activation", "import:pkg1", requested_by="agent_2")
        assert aid1 == aid2
        assert _table_count(db, "pending_approvals") == 1

        db.approve(aid1, "admin")
        aid3 = db.upsert_approval("import_activation", "import:pkg1")
        assert aid3 != aid1
        assert db.get_pending_approval("import_activation", "import:pkg1")["id"] == aid3
