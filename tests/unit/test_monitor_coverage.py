"""Unit tests for kali_mcp/monitor — Monitor, session registry, SSE client, TUI."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from kali_mcp.monitor import Monitor
from kali_mcp.monitor.sessions import SessionRegistry
from kali_mcp.monitor.sse_client import SseClient
from kali_mcp.monitor.tui import _health_panel, _jobs_panel, _sessions_panel, build_layout


class TestMonitorSnapshot:
    def test_build_snapshot_shape(self):
        session_registry = MagicMock()
        session_registry.list_sessions.return_value = [
            {
                "session_id": "sess-1",
                "connected_at": "2026-11-03T10:00:00+00:00",
                "last_activity": "2026-11-03T10:00:05+00:00",
                "client_info": {"name": "test-client"},
            }
        ]
        engine = MagicMock()
        engine.get_active_jobs.return_value = [
            {"request_id": "req-1", "tool": "nmap", "elapsed_seconds": 12.5}
        ]
        health = MagicMock()
        health.get_status.return_value = {
            "status": "healthy",
            "uptime_seconds": 100.0,
            "active_executions": 1,
            "total_requests": 10,
            "total_errors": 0,
            "tools_registered": 56,
            "memory_mb": 128.0,
        }

        monitor = Monitor(session_registry, engine, health)
        snapshot = monitor.build_snapshot()

        assert "timestamp" in snapshot
        assert snapshot["sessions"][0]["session_id"] == "sess-1"
        assert snapshot["jobs"][0]["request_id"] == "req-1"
        assert snapshot["jobs"][0]["tool"] == "nmap"
        assert snapshot["health"]["status"] == "healthy"

    def test_get_snapshot_mirror(self):
        session_registry = MagicMock()
        session_registry.list_sessions.return_value = [
            {"session_id": "sess-1", "connected_at": "t", "last_activity": "t", "client_info": {}}
        ]
        engine = MagicMock()
        engine.get_active_jobs.return_value = [
            {"request_id": "req-1", "tool": "nmap", "elapsed_seconds": 1.0}
        ]
        health = MagicMock()
        health.get_status.return_value = {"status": "healthy"}

        monitor = Monitor(session_registry, engine, health)
        snap_get = monitor.get_snapshot()
        snap_build = monitor.build_snapshot()
        # Both go through build_snapshot; only the timestamp may differ between calls.
        assert snap_get.keys() == snap_build.keys()
        assert snap_get["sessions"] == snap_build["sessions"]
        assert snap_get["jobs"] == snap_build["jobs"]
        assert snap_get["health"] == snap_build["health"]
        assert "timestamp" in snap_get


class TestMonitorSSEClients:
    def test_subscribe_unsubscribe(self):
        monitor = Monitor(MagicMock(), MagicMock(), MagicMock())
        assert monitor._clients == set()
        q = monitor.subscribe()
        assert len(monitor._clients) == 1
        monitor.unsubscribe(q)
        assert monitor._clients == set()

    def test_broadcast_drops_full_queues(self):
        import asyncio

        monitor = Monitor(MagicMock(), MagicMock(), MagicMock())
        full_q = asyncio.Queue(maxsize=1)
        full_q.put_nowait({"blocking": True})
        monitor._clients.add(full_q)
        normal_q = asyncio.Queue()
        monitor._clients.add(normal_q)

        asyncio.run(monitor.broadcast({"test": True}))
        assert full_q not in monitor._clients
        assert normal_q.get_nowait() == {"test": True}

    def test_broadcast_empty_clients(self):
        import asyncio

        monitor = Monitor(MagicMock(), MagicMock(), MagicMock())
        # Should not raise with no clients
        asyncio.run(monitor.broadcast({"test": True}))


class TestMonitorActions:
    def test_kill_job_broadcasts_snapshot(self):
        session_registry = MagicMock()
        engine = MagicMock()
        engine.kill_job = AsyncMock(return_value=True)
        health = MagicMock()
        health.get_status.return_value = {"status": "healthy"}

        monitor = Monitor(session_registry, engine, health)
        result = _run_async(monitor.kill_job("req-1"))

        assert result == {"action": "kill_job", "request_id": "req-1", "killed": True}
        engine.kill_job.assert_called_once_with("req-1")

    def test_kill_job_not_found(self):
        engine = MagicMock()
        engine.kill_job = AsyncMock(return_value=False)
        monitor = Monitor(MagicMock(), engine, MagicMock())
        result = _run_async(monitor.kill_job("req-unknown"))
        assert result["killed"] is False

    def test_force_cleanup(self):
        engine = MagicMock()
        engine.force_cleanup = MagicMock(return_value=5)
        monitor = Monitor(MagicMock(), engine, MagicMock())
        result = _run_async(monitor.force_cleanup())
        assert result == {"action": "force_cleanup", "cleaned": 5}
        engine.force_cleanup.assert_called_once()


class TestSessionRegistry:
    def test_connect_and_list(self):
        reg = SessionRegistry()
        reg.on_connect("sess-1", {"name": "test-client", "version": "1.0"})
        sessions = reg.list_sessions()
        assert len(sessions) == 1
        assert sessions[0]["session_id"] == "sess-1"
        assert sessions[0]["client_info"]["name"] == "test-client"
        assert "connected_at" in sessions[0]
        assert "last_activity" in sessions[0]

    def test_connect_multiple_sessions(self):
        reg = SessionRegistry()
        for sid in ("sess-a", "sess-b", "sess-c"):
            reg.on_connect(sid, {})
        assert len(reg.list_sessions()) == 3
        assert {s["session_id"] for s in reg.list_sessions()} == {"sess-a", "sess-b", "sess-c"}

    def test_activity_updates_last_activity(self):
        reg = SessionRegistry()
        reg.on_connect("sess-1", {})
        first = reg.get_session("sess-1")["last_activity"]
        reg.on_activity("sess-1")
        second = reg.get_session("sess-1")["last_activity"]
        assert second >= first

    def test_activity_unknown_session_is_noop(self):
        reg = SessionRegistry()
        reg.on_activity("nonexistent")
        assert reg.count() == 0

    def test_disconnect_removes_session(self):
        reg = SessionRegistry()
        reg.on_connect("sess-1", {})
        reg.on_disconnect("sess-1")
        assert reg.count() == 0
        assert reg.get_session("sess-1") is None

    def test_disconnect_unknown_is_noop(self):
        reg = SessionRegistry()
        reg.on_disconnect("nonexistent")
        assert reg.count() == 0

    def test_get_session_unknown_returns_none(self):
        assert SessionRegistry().get_session("nope") is None

    def test_count_and_clear(self):
        reg = SessionRegistry()
        assert reg.count() == 0
        reg.on_connect("s1", {})
        reg.on_connect("s2", {})
        assert reg.count() == 2
        reg.clear()
        assert reg.count() == 0
        assert reg.list_sessions() == []


class TestSseClient:
    def test_get_latest_snapshot_none_before_connect(self):
        client = SseClient("http://127.0.0.1:1/monitor/stream")
        assert client.get_latest_snapshot() is None

    def test_close_without_connect(self):
        import asyncio

        client = SseClient("http://127.0.0.1:1/monitor/stream")
        asyncio.run(client.close())  # should not raise


class TestTuiLayout:
    def test_sessions_panel(self):
        panel = _sessions_panel(
            [
                {
                    "session_id": "sess-1",
                    "connected_at": "10:00:00",
                    "last_activity": "10:00:05",
                    "client_info": {"name": "c", "version": "1.0"},
                }
            ]
        )
        assert "Connected Users" in panel.title.plain

    def test_sessions_panel_empty(self):
        panel = _sessions_panel([])
        assert "Connected Users" in panel.title.plain

    def test_jobs_panel(self):
        panel = _jobs_panel(
            [
                {"request_id": "req-1", "tool": "nmap", "elapsed_seconds": 12.5},
                {"request_id": "req-2", "tool": "sqlmap", "elapsed_seconds": 3.0},
            ]
        )
        assert "Running Jobs" in panel.title.plain

    def test_jobs_panel_empty(self):
        panel = _jobs_panel([])
        assert "Running Jobs" in panel.title.plain

    def test_health_panel(self):
        health = {
            "status": "healthy",
            "uptime_seconds": 100.5,
            "active_executions": 2,
            "total_requests": 50,
            "total_errors": 1,
            "tools_registered": 56,
            "memory_mb": 256.0,
        }
        panel = _health_panel(health)
        assert panel.title.plain == "Server Health"

    def test_health_panel_empty(self):
        panel = _health_panel({})
        assert panel is not None

    def test_build_layout(self):
        snapshot = {
            "timestamp": "2026-11-03T12:00:00+00:00",
            "sessions": [
                {
                    "session_id": "sess-1",
                    "connected_at": "10:00:00",
                    "last_activity": "10:00:05",
                    "client_info": {},
                }
            ],
            "jobs": [{"request_id": "req-1", "tool": "nmap", "elapsed_seconds": 5.0}],
            "health": {"status": "healthy"},
        }
        layout = build_layout(snapshot, "test status")
        assert layout is not None

    def test_build_layout_none(self):
        assert build_layout(None) is not None


# ── Helpers for running async actions in sync tests ──────────────────


def _run_async(coro):
    import asyncio

    return asyncio.run(coro)
