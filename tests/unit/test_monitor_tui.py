"""Unit tests for the monitor TUI layout builders (kali_mcp/monitor/tui.py)."""

from __future__ import annotations

from kali_mcp.monitor.tui import _health_panel, _jobs_panel, _sessions_panel, build_layout


class TestTuiLayout:
    def test_sessions_panel(self) -> None:
        sessions = [
            {
                "session_id": "sess-1",
                "connected_at": "10:00:00",
                "last_activity": "10:00:05",
                "client_info": {"name": "test-client", "version": "1.0"},
            }
        ]
        panel = _sessions_panel(sessions)
        assert panel is not None
        assert "Connected Users (1)" in panel.title

    def test_sessions_panel_empty(self) -> None:
        panel = _sessions_panel([])
        assert panel is not None
        assert "Connected Users (0)" in panel.title

    def test_jobs_panel(self) -> None:
        jobs = [
            {"request_id": "req-1", "tool": "nmap", "elapsed_seconds": 12.5},
            {"request_id": "req-2", "tool": "sqlmap", "elapsed_seconds": 3.0},
        ]
        panel = _jobs_panel(jobs)
        assert panel is not None
        assert "Running Jobs (2)" in panel.title

    def test_jobs_panel_empty(self) -> None:
        panel = _jobs_panel([])
        assert panel is not None
        assert "Running Jobs (0)" in panel.title

    def test_health_panel(self) -> None:
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
        assert panel is not None
        assert panel.title == "Server Health"

    def test_health_panel_empty(self) -> None:
        panel = _health_panel({})
        assert panel is not None

    def test_build_layout(self) -> None:
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

    def test_build_layout_none(self) -> None:
        layout = build_layout(None)
        assert layout is not None

    def test_build_layout_no_status_msg(self) -> None:
        snapshot = {
            "timestamp": "2026-11-03T12:00:00+00:00",
            "sessions": [],
            "jobs": [],
            "health": {"status": "healthy"},
        }
        layout = build_layout(snapshot)
        assert layout is not None
