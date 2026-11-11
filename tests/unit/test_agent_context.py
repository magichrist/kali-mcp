"""Tests for per-request agent-profile context (Phase 6 enforcement).

Covers ``kmcp.agent_context``: header resolution, token-bound profile
resolution, deny-by-default permission checks, forbidden payloads, and the
ContextVar lifecycle used by server.py.
"""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from kmcp.agent_context import (
    HEADER_PROFILE,
    agent_context,
    forbidden_playbook_payload,
    forbidden_tool_payload,
)
from kmcp.db import manager as db_manager
from kmcp.db.manager import DBManager


@pytest.fixture()
def db(tmp_path):
    m = DBManager(tmp_path / "agent_ctx.sqlite")
    m.ensure_schema()
    return m


@pytest.fixture()
def patch_db(monkeypatch, db):
    """Route all ``db_manager.get_db()`` lookups to the tmp DBManager."""
    monkeypatch.setattr(db_manager, "get_db", lambda: db)
    return db


@pytest.fixture(autouse=True)
def _clear_profile_ctx():
    """Ensure every test starts (and ends) with no agent-profile binding."""
    token = agent_context.set_current_profile(None)
    yield
    agent_context.reset_current_profile(token)


def _seed_profile(db, profile_id="p1", tool="nmap", playbook=None):
    db.create_agent_profile(profile_id, "Test profile")
    db.grant_tool_permission(profile_id, tool)
    if playbook:
        db.create_playbook(playbook, "Assigned pb")
        db.assign_playbook_to_profile(profile_id, playbook)
    return profile_id


class TestResolveProfileFromHeaders:
    def test_valid_profile_resolves(self, patch_db):
        _seed_profile(patch_db, "p1")
        assert agent_context.resolve_profile_from_headers({HEADER_PROFILE: "p1"}) == "p1"

    def test_missing_header_is_no_context(self, patch_db):
        assert agent_context.resolve_profile_from_headers({}) is None

    def test_missing_mapping_is_no_context(self, patch_db):
        assert agent_context.resolve_profile_from_headers(None) is None

    def test_unknown_profile_is_ignored(self, patch_db):
        assert agent_context.resolve_profile_from_headers({HEADER_PROFILE: "ghost-profile"}) is None

    def test_empty_header_is_ignored(self, patch_db):
        assert agent_context.resolve_profile_from_headers({HEADER_PROFILE: "  "}) is None

    def test_db_unavailable_is_no_context(self, monkeypatch):
        monkeypatch.setattr(db_manager, "get_db", lambda: None)
        assert agent_context.resolve_profile_from_headers({HEADER_PROFILE: "p1"}) is None


def _bind_config_profile(profile_id: str):
    """Bind ``config.agent_profile_id`` despite the frozen dataclass; returns undo."""
    from kmcp.config import config

    previous = getattr(config, "agent_profile_id", "")
    object.__setattr__(config, "agent_profile_id", profile_id)
    return lambda: object.__setattr__(config, "agent_profile_id", previous)


class TestResolveFromContext:
    def _ctx_with_headers(self, headers):
        request = SimpleNamespace(headers=headers)
        request_context = SimpleNamespace(request=request)
        return SimpleNamespace(request_context=request_context)

    def test_header_resolution(self, patch_db):
        _seed_profile(patch_db, "p1")
        ctx = self._ctx_with_headers({HEADER_PROFILE: "p1"})
        assert agent_context.resolve_from_context(ctx) == "p1"

    def test_stdio_transport_is_no_context(self, patch_db):
        # No HTTP request object at all → None (unchanged default behavior).
        ctx = SimpleNamespace(request_context=SimpleNamespace(request=None))
        assert agent_context.resolve_from_context(ctx) is None

    def test_token_bound_profile_takes_precedence(self, patch_db, monkeypatch):
        _seed_profile(patch_db, "p1")
        undo = _bind_config_profile("p1")
        try:
            # Even a bogus/unresolvable header cannot override the binding.
            ctx = self._ctx_with_headers({HEADER_PROFILE: "p2"})
            assert agent_context.resolve_from_context(ctx) == "p1"
        finally:
            undo()

    def test_unknown_bound_profile_falls_back_to_header(self, patch_db, monkeypatch):
        _seed_profile(patch_db, "p1")
        undo = _bind_config_profile("ghost")
        try:
            ctx = self._ctx_with_headers({HEADER_PROFILE: "p1"})
            assert agent_context.resolve_from_context(ctx) == "p1"
        finally:
            undo()

    def test_bound_profile_missing_in_db_yields_none(self, patch_db, monkeypatch):
        undo = _bind_config_profile("ghost")
        try:
            ctx = self._ctx_with_headers({})
            assert agent_context.resolve_from_context(ctx) is None
        finally:
            undo()


class TestPermissionChecks:
    def test_deny_by_default_without_grant(self, patch_db):
        _seed_profile(patch_db, "p1", tool="nmap")
        assert agent_context.can_call_tool("p1", "nmap") is True
        assert agent_context.can_call_tool("p1", "sqlmap") is False

    def test_unassigned_playbook_denied(self, patch_db):
        _seed_profile(patch_db, "p1")
        patch_db.create_playbook("pb.other", "Other")
        assert agent_context.is_playbook_assigned("p1", "pb.other") is False

    def test_assigned_playbook_granted(self, patch_db):
        _seed_profile(patch_db, "p1", playbook="pb.ok")
        assert agent_context.is_playbook_assigned("p1", "pb.ok") is True

    def test_empty_ids_are_denied(self, patch_db):
        assert agent_context.can_call_tool("", "nmap") is False
        assert agent_context.can_call_tool("p1", "") is False
        assert agent_context.is_playbook_assigned("", "pb") is False

    def test_db_broken_fails_closed(self, patch_db, monkeypatch):
        _seed_profile(patch_db, "p1")

        def boom():
            raise RuntimeError("db offline")

        monkeypatch.setattr(db_manager, "get_db", boom)
        assert agent_context.can_call_tool("p1", "nmap") is False
        assert agent_context.is_playbook_assigned("p1", "x") is False

    def test_assigned_playbooks_lists_granted_only(self, patch_db):
        _seed_profile(patch_db, "p1", playbook="pb.ok")
        patch_db.create_playbook("pb.revoked", "Revoked")
        patch_db.assign_playbook_to_profile("p1", "pb.revoked", granted=False)
        rows = agent_context.assigned_playbooks("p1")
        ids = [r["playbook_id"] for r in rows]
        assert ids == ["pb.ok"]


class TestContextVarLifecycle:
    def test_set_and_reset(self):
        token = agent_context.set_current_profile("p1")
        try:
            assert agent_context.get_current_profile() == "p1"
        finally:
            agent_context.reset_current_profile(token)
        assert agent_context.get_current_profile() is None

    def test_nested_reset_restores_outer(self):
        outer = agent_context.set_current_profile("p1")
        agent_context.set_current_profile("p2")
        assert agent_context.get_current_profile() == "p2"
        agent_context.reset_current_profile(outer)
        assert agent_context.get_current_profile() is None


class TestForbiddenPayloads:
    def test_tool_payload_marks_forbidden_403(self):
        import json

        text = forbidden_tool_payload("sqlmap", "p1")
        payload = json.loads(text)
        assert payload["forbidden"] is True
        assert payload["code"] == 403
        assert payload["success"] is False
        assert "sqlmap" in payload["error"] and "p1" in payload["error"]

    def test_playbook_payload_marks_forbidden_403(self):
        import json

        text = forbidden_playbook_payload("pb.x", "p1")
        payload = json.loads(text)
        assert payload["forbidden"] is True
        assert payload["code"] == 403
        assert payload["playbook_id"] == "pb.x"

    def test_facade_matches_module_symbols(self):
        # Importable facade must expose the same callables.
        assert agent_context.can_call_tool is forbidden_tool_payload.__globals__[
            "can_call_tool"
        ] or callable(agent_context.can_call_tool)
        assert callable(agent_context.resolve_from_context)
        assert agent_context.HEADER_PROFILE == HEADER_PROFILE


class TestDbManagerHelpers:
    def test_list_tool_permission_rows(self, db):
        _seed_profile(db, "p1", tool="nmap")
        db.grant_tool_permission("p1", "sqlmap", granted=False)
        all_rows = db.list_tool_permission_rows("p1")
        assert len(all_rows) == 2
        granted_ids = {r["tool_id"] for r in db.list_tool_permission_rows("p1", granted_only=True)}
        assert granted_ids == {"nmap"}

    def test_list_playbook_assignments(self, db):
        _seed_profile(db, "p1", playbook="pb.ok")
        rows = db.list_playbook_assignments("p1")
        assert rows == [{"playbook_id": "pb.ok", "granted": 1, "granted_at": rows[0]["granted_at"]}]

    def test_list_helpers_for_unknown_profile(self, db):
        assert db.list_tool_permission_rows("nobody") == []
        assert db.list_playbook_assignments("nobody") == []
