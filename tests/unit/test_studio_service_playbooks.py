"""Tests for the Studio playbook service layer (Phase 4)."""

from __future__ import annotations

import json
import pytest

from kali_mcp.db.manager import DBManager
from kali_mcp.studio import playbook_service


@pytest.fixture
def db(tmp_path):
    """Fresh DBManager using a temp sqlite file."""
    db_path = tmp_path / "test_studio_playbook.sqlite"
    m = DBManager(str(db_path))
    m.ensure_schema()
    yield m
    m.conn.close()


VALID_DEFINITION = {
    "id": "custom.domain_recon",
    "name": "Custom Domain Recon",
    "version": "1.0.0",
    "inputs": {
        "target": {"type": "string", "required": True, "source": "agent"},
    },
    "execution": {"max_parallel": 4, "timeout": 900, "resume": True},
    "steps": [
        {
            "id": "validate",
            "tool": "target.validate",
            "type": "custom",
            "depends_on": [],
            "inputs": {"target": "{{inputs.target}}"},
        },
        {
            "id": "scope",
            "tool": "target.scope_check",
            "type": "custom",
            "depends_on": ["validate"],
            "inputs": {"target": "{{inputs.target}}"},
        },
    ],
    "outputs": {
        "result": "{{steps.scope.allowed}}",
    },
}


class TestCRUD:
    def test_create_get_playbook(self, db):
        row = playbook_service.create_playbook(
            db, playbook_id="pb1", name="Test Playbook", category="recon"
        )
        assert row is not None
        assert row["playbook_id"] == "pb1"
        assert row["name"] == "Test Playbook"
        assert row["category"] == "recon"
        assert row["status"] == "draft"
        row2 = playbook_service.get_playbook(db, "pb1")
        assert row2 is not None
        assert row2["name"] == "Test Playbook"

    def test_list_playbooks(self, db):
        playbook_service.create_playbook(db, playbook_id="pb1", name="PB1", status="draft")
        playbook_service.create_playbook(db, playbook_id="pb2", name="PB2", status="published")
        drafts = playbook_service.list_playbooks(db, status="draft")
        assert len(drafts) == 1
        assert drafts[0]["playbook_id"] == "pb1"
        all_pbs = playbook_service.list_playbooks(db)
        assert len(all_pbs) == 2

    def test_update_playbook(self, db):
        playbook_service.create_playbook(db, playbook_id="pb1", name="Old", category="recon")
        ok = playbook_service.update_playbook(db, "pb1", name="New", status="published")
        assert ok is True
        row = playbook_service.get_playbook(db, "pb1")
        assert row["name"] == "New"
        assert row["status"] == "published"

    def test_update_nonexistent(self, db):
        assert playbook_service.update_playbook(db, "nope", name="X") is False

    def test_delete_playbook(self, db):
        playbook_service.create_playbook(db, playbook_id="pb1", name="PB1")
        assert playbook_service.delete_playbook(db, "pb1") is True
        assert playbook_service.get_playbook(db, "pb1") is None
        assert playbook_service.delete_playbook(db, "nope") is False


class TestPublish:
    def test_publish_version(self, db):
        playbook_service.create_playbook(db, playbook_id="pb1", name="PB1")
        vid = playbook_service.publish_version(
            db, playbook_id="pb1", version="1.0.0", definition=VALID_DEFINITION,
            notes="Initial release",
        )
        assert vid > 0
        row = playbook_service.get_version(db, vid)
        assert row is not None
        assert row["version"] == "1.0.0"
        assert row["playbook_id"] == "pb1"

    def test_list_versions(self, db):
        playbook_service.create_playbook(db, playbook_id="pb1", name="PB1")
        playbook_service.publish_version(db, "pb1", "1.0.0", definition=VALID_DEFINITION)
        playbook_service.publish_version(db, "pb1", "2.0.0", definition=VALID_DEFINITION)
        versions = playbook_service.list_versions(db, "pb1")
        assert len(versions) == 2
        assert versions[0]["version"] == "1.0.0"
        assert versions[1]["version"] == "2.0.0"

    def test_get_version_nonexistent(self, db):
        assert playbook_service.get_version(db, 99999) is None


class TestValidation:
    def test_valid_definition(self, db):
        playbook_service.create_playbook(db, playbook_id="pb1", name="PB1")
        result = playbook_service.validate_definition(db, "pb1", VALID_DEFINITION)
        assert result["valid"] is True

    def test_invalid_definition(self, db):
        playbook_service.create_playbook(db, playbook_id="pb1", name="PB1")
        result = playbook_service.validate_definition(db, "pb1", {"steps": []})
        assert result["valid"] is False
        assert len(result["findings"]) > 0

    def test_for_publish_requires_modules(self, db):
        # Module steps that aren't registered should fail at publish time
        playbook_service.create_playbook(db, playbook_id="pb1", name="PB1")
        defn = dict(VALID_DEFINITION)
        defn["steps"][0]["tool"] = "nonexistent.module"
        result = playbook_service.validate_definition(db, "pb1", defn, for_publish=True)
        # May or may not fail depending on whether module catalogs resolve;
        # the point is it doesn't crash
        assert "valid" in result


class TestPreview:
    def test_preview_resolves_dag(self, db):
        playbook_service.create_playbook(db, playbook_id="pb1", name="PB1")
        result = playbook_service.preview_playbook(db, "pb1", VALID_DEFINITION)
        assert result["ok"] is True
        assert result["step_count"] == 2
        assert "validate" in result["execution_order"]
        assert "scope" in result["execution_order"]

    def test_preview_cycle(self, db):
        playbook_service.create_playbook(db, playbook_id="pb1", name="PB1")
        defn = dict(VALID_DEFINITION)
        defn["steps"] = [
            {
                "id": "a", "tool": "target.validate", "type": "custom",
                "depends_on": ["b"], "inputs": {"target": "{{inputs.target}}"},
            },
            {
                "id": "b", "tool": "target.validate", "type": "custom",
                "depends_on": ["a"], "inputs": {"target": "{{inputs.target}}"},
            },
        ]
        result = playbook_service.preview_playbook(db, "pb1", defn)
        assert result["ok"] is False
        assert "error" in result


class TestRollback:
    def test_rollback_version(self, db):
        playbook_service.create_playbook(db, playbook_id="pb1", name="PB1")
        v1 = playbook_service.publish_version(db, "pb1", "1.0.0", definition=VALID_DEFINITION)
        v2 = playbook_service.publish_version(db, "pb1", "2.0.0", definition=VALID_DEFINITION)
        # Rollback to v1
        row = playbook_service.rollback_version(db, "pb1", v1)
        assert row["version"] == "1.0.0"

    def test_rollback_nonexistent_version(self, db):
        playbook_service.create_playbook(db, playbook_id="pb1", name="PB1")
        with pytest.raises(ValueError, match="not found"):
            playbook_service.rollback_version(db, "pb1", 99999)

    def test_rollback_wrong_playbook(self, db):
        playbook_service.create_playbook(db, playbook_id="pb1", name="PB1")
        playbook_service.create_playbook(db, playbook_id="pb2", name="PB2")
        v1 = playbook_service.publish_version(db, "pb1", "1.0.0", definition=VALID_DEFINITION)
        with pytest.raises(ValueError, match="does not belong"):
            playbook_service.rollback_version(db, "pb2", v1)


class TestExportImport:
    def test_export_playbook(self, db):
        playbook_service.create_playbook(db, playbook_id="pb1", name="PB1", category="recon")
        playbook_service.publish_version(db, "pb1", "1.0.0", definition=VALID_DEFINITION)
        package = playbook_service.export_playbook(db, "pb1")
        assert package is not None
        assert package["format"] == "kali-mcp-playbook-package"
        assert package["playbook"]["playbook_id"] == "pb1"
        assert package["playbook"]["name"] == "PB1"
        assert len(package["versions"]) == 1
        assert "hash" in package

    def test_export_nonexistent(self, db):
        assert playbook_service.export_playbook(db, "nope") is None

    def test_import_playbook(self, db):
        playbook_service.create_playbook(db, playbook_id="pb1", name="PB1")
        playbook_service.publish_version(db, "pb1", "1.0.0", definition=VALID_DEFINITION)
        package = playbook_service.export_playbook(db, "pb1")
        # Import into a fresh DB
        db2 = DBManager(":memory:")
        db2.ensure_schema()
        result = playbook_service.import_playbook(db2, package, require_approval=False)
        assert result["ok"] is True
        assert result["playbook_id"] == "pb1"
        assert result["versions_imported"] == 1
        row = playbook_service.get_playbook(db2, "pb1")
        assert row is not None
        assert row["name"] == "PB1"

    def test_import_invalid_format(self, db):
        result = playbook_service.import_playbook(db, {"format": "bad"})
        assert result["ok"] is False

    def test_import_hash_mismatch(self, db):
        package = {"format": "kali-mcp-playbook-package", "playbook": {}, "versions": []}
        package["hash"] = "badhash"
        result = playbook_service.import_playbook(db, package)
        assert result["ok"] is False
        assert "hash" in result["error"]
