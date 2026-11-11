"""Unit tests for the monitor snapshot builder (kmcp/monitor/__init__.py)."""

from __future__ import annotations

from unittest.mock import MagicMock

from kmcp.monitor import Monitor


class TestBuildSnapshot:
    def test_snapshot_shape(self) -> None:
        # Build fake dependencies
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
            {
                "request_id": "req-1",
                "tool": "nmap",
                "elapsed_seconds": 12.5,
            }
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
        assert "sessions" in snapshot
        assert "jobs" in snapshot
        assert "health" in snapshot

        assert len(snapshot["sessions"]) == 1
        assert snapshot["sessions"][0]["session_id"] == "sess-1"

        assert len(snapshot["jobs"]) == 1
        assert snapshot["jobs"][0]["request_id"] == "req-1"
        assert snapshot["jobs"][0]["tool"] == "nmap"
        assert snapshot["jobs"][0]["elapsed_seconds"] == 12.5

        assert snapshot["health"]["status"] == "healthy"
        assert snapshot["health"]["tools_registered"] == 56

    def test_snapshot_empty(self) -> None:
        session_registry = MagicMock()
        session_registry.list_sessions.return_value = []

        engine = MagicMock()
        engine.get_active_jobs.return_value = []

        health = MagicMock()
        health.get_status.return_value = {
            "status": "healthy",
            "uptime_seconds": 0.0,
            "active_executions": 0,
            "total_requests": 0,
            "total_errors": 0,
            "tools_registered": 0,
            "memory_mb": 0.0,
        }

        monitor = Monitor(session_registry, engine, health)
        snapshot = monitor.build_snapshot()
        assert snapshot["sessions"] == []
        assert snapshot["jobs"] == []
        assert snapshot["health"]["status"] == "healthy"

    def test_subscribe_unsubscribe(self) -> None:
        session_registry = MagicMock()
        engine = MagicMock()
        health = MagicMock()

        monitor = Monitor(session_registry, engine, health)
        assert len(monitor._clients) == 0

        q = monitor.subscribe()
        assert len(monitor._clients) == 1

        monitor.unsubscribe(q)
        assert len(monitor._clients) == 0

    def test_broadcast_drops_full_queues(self) -> None:
        import asyncio

        session_registry = MagicMock()
        engine = MagicMock()
        health = MagicMock()

        monitor = Monitor(session_registry, engine, health)

        # A full queue (maxsize=0 means unbounded, so use maxsize=1 and put something)
        full_q = asyncio.Queue(maxsize=1)
        full_q.put_nowait({"blocking": True})
        monitor._clients.add(full_q)

        normal_q = asyncio.Queue()
        monitor._clients.add(normal_q)

        async def _test():
            await monitor.broadcast({"test": True})
            # Full queue should be dropped
            assert full_q not in monitor._clients
            # Normal queue should have the snapshot
            snapshot = normal_q.get_nowait()
            assert snapshot == {"test": True}

        asyncio.run(_test())
