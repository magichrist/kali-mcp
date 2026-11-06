"""Tests for Studio approval gates and redaction (Phase 4)."""

from __future__ import annotations

import pytest

from kali_mcp.db.manager import DBManager
from kali_mcp.studio import approvals, redaction


@pytest.fixture
def db(tmp_path):
    db_path = tmp_path / "test_studio_approval.sqlite"
    m = DBManager(str(db_path))
    m.ensure_schema()
    yield m
    m.conn.close()


class TestApprovals:
    def test_request_and_get_pending(self, db):
        aid = approvals.request_approval(
            db, gate="publish", resource_id="pb1", requested_by="alice"
        )
        assert aid > 0
        pending = approvals.get_pending_approval(db, "publish", "pb1")
        assert pending is not None
        assert pending["gate"] == "publish"
        assert pending["resource_id"] == "pb1"
        assert pending["status"] == "pending"

    def test_is_approved(self, db):
        assert approvals.is_approved(db, "publish", "pb1") is False
        approvals.request_approval(db, gate="publish", resource_id="pb1")
        assert approvals.is_approved(db, "publish", "pb1") is True

    def test_approve(self, db):
        aid = approvals.request_approval(db, gate="publish", resource_id="pb1")
        ok = approvals.approve(db, approval_id=aid, approved_by="bob")
        assert ok is True
        # After approval, no pending row
        assert approvals.get_pending_approval(db, "publish", "pb1") is None

    def test_approve_nonexistent(self, db):
        assert approvals.approve(db, approval_id=99999, approved_by="bob") is False

    def test_require_approval_for_messages(self):
        assert "publish" in approvals.require_approval_for("publish").lower()
        assert "approval" in approvals.require_approval_for("publish").lower()
        assert "unknown gate" in approvals.require_approval_for("weird").lower() or "gate" in approvals.require_approval_for("weird").lower()

    def test_gate_constants(self):
        assert approvals.GATE_PUBLISH == "publish"
        assert approvals.GATE_IMPORT == "import"
        assert approvals.GATE_VISIBILITY_AGENT_CALLABLE == "visibility:agent_callable"
        assert approvals.GATE_PLAYBOOK_ASSIGN == "playbook:assign"


class TestRedaction:
    def test_redacts_secret_keys(self):
        result = redaction.redact({
            "api_key": "sk-1234567890abcdef",
            "name": "tool",
            "password": "hunter2",
        })
        assert result["api_key"] == "***REDACTED***"
        assert result["password"] == "***REDACTED***"
        assert result["name"] == "tool"

    def test_redacts_nested(self):
        result = redaction.redact({
            "data": {"credentials": {"password": "secret"}},
            "public": "visible",
        })
        # "credentials" is a secret key → its entire value is replaced
        assert result["data"]["credentials"] == "***REDACTED***"
        assert result["public"] == "visible"

    def test_redacts_secret_key_at_top_level(self):
        result = redaction.redact({"api_key": "sk-123", "name": "tool"})
        assert result["api_key"] == "***REDACTED***"
        assert result["name"] == "tool"

    def test_redact_result_alias(self):
        # redact_result is a wrapper around redact, same behavior
        result = redaction.redact_result({"api_key": "secret-xyz", "name": "tool"})
        assert result["api_key"] == "***REDACTED***"
        assert result["name"] == "tool"

    def test_redact_log(self):
        msg = redaction.redact_log("connecting with token sk_live_abc123def456")
        assert "***REDACTED***" in msg
        assert "sk_live" not in msg
