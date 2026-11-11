"""Unit tests for the monitor session registry (kmcp/monitor/sessions.py)."""

from __future__ import annotations

from kmcp.monitor.sessions import SessionRegistry, session_registry


class TestSessionRegistry:
    def test_connect_and_list(self) -> None:
        reg = SessionRegistry()
        reg.on_connect("sess-1", {"name": "test-client", "version": "1.0"})
        sessions = reg.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "sess-1"
        assert sessions[0]["client_info"]["name"] == "test-client"
        assert "connected_at" in sessions[0]
        assert "last_activity" in sessions[0]

    def test_connect_multiple_sessions(self) -> None:
        reg = SessionRegistry()
        reg.on_connect("sess-a", {})
        reg.on_connect("sess-b", {})
        reg.on_connect("sess-c", {})
        sessions = reg.list_sessions()
        assert len(sessions) == 3
        ids = {s["session_id"] for s in sessions}
        assert ids == {"sess-a", "sess-b", "sess-c"}

    def test_activity_updates_last_activity(self) -> None:
        reg = SessionRegistry()
        reg.on_connect("sess-1", {})
        first = reg.get_session("sess-1")
        assert first is not None
        first_activity = first["last_activity"]

        reg.on_activity("sess-1")
        second = reg.get_session("sess-1")
        assert second is not None
        assert second["last_activity"] >= first_activity

    def test_activity_unknown_session_is_noop(self) -> None:
        reg = SessionRegistry()
        # Should not raise
        reg.on_activity("nonexistent")
        assert reg.count() == 0

    def test_disconnect_removes_session(self) -> None:
        reg = SessionRegistry()
        reg.on_connect("sess-1", {})
        assert reg.count() == 1
        reg.on_disconnect("sess-1")
        assert reg.count() == 0
        assert reg.get_session("sess-1") is None

    def test_disconnect_unknown_session_is_noop(self) -> None:
        reg = SessionRegistry()
        reg.on_disconnect("nonexistent")  # should not raise
        assert reg.count() == 0

    def test_get_session_unknown_returns_none(self) -> None:
        reg = SessionRegistry()
        assert reg.get_session("nope") is None

    def test_count(self) -> None:
        reg = SessionRegistry()
        assert reg.count() == 0
        reg.on_connect("s1", {})
        reg.on_connect("s2", {})
        assert reg.count() == 2
        reg.on_disconnect("s1")
        assert reg.count() == 1

    def test_clear(self) -> None:
        reg = SessionRegistry()
        reg.on_connect("s1", {})
        reg.on_connect("s2", {})
        reg.clear()
        assert reg.count() == 0
        assert reg.list_sessions() == []

    def test_sessions_sorted_newest_first(self) -> None:
        import time

        reg = SessionRegistry()
        reg.on_connect("old", {})
        time.sleep(0.01)
        reg.on_connect("new", {})
        sessions = reg.list_sessions()
        assert sessions[0]["session_id"] == "new"
        assert sessions[1]["session_id"] == "old"

    def test_global_registry_is_singleton(self) -> None:
        # The module-level session_registry should be a usable instance
        assert session_registry is not None
        assert isinstance(session_registry.count(), int)
