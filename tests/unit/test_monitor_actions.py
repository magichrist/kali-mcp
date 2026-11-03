"""Unit tests for monitor actions (kill_job, force_cleanup)."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

from kali_mcp.monitor import Monitor


class TestMonitorActions:
    def test_kill_job_found(self) -> None:
        session_registry = MagicMock()
        engine = MagicMock()
        engine.kill_job = AsyncMock(return_value=True)
        health = MagicMock()
        health.get_status.return_value = {"status": "healthy"}

        monitor = Monitor(session_registry, engine, health)
        result = _run_async(monitor.kill_job("req-1"))

        assert result["action"] == "kill_job"
        assert result["request_id"] == "req-1"
        assert result["killed"] is True
        engine.kill_job.assert_called_once_with("req-1")

    def test_kill_job_not_found(self) -> None:
        session_registry = MagicMock()
        engine = MagicMock()
        engine.kill_job = AsyncMock(return_value=False)
        health = MagicMock()
        health.get_status.return_value = {"status": "healthy"}

        monitor = Monitor(session_registry, engine, health)
        result = _run_async(monitor.kill_job("req-unknown"))

        assert result["killed"] is False

    def test_force_cleanup(self) -> None:
        session_registry = MagicMock()
        engine = MagicMock()
        engine.force_cleanup = MagicMock(return_value=5)
        health = MagicMock()
        health.get_status.return_value = {"status": "healthy"}

        monitor = Monitor(session_registry, engine, health)
        result = _run_async(monitor.force_cleanup())

        assert result["action"] == "force_cleanup"
        assert result["cleaned"] == 5
        engine.force_cleanup.assert_called_once()


# ── Helpers for running async actions in sync tests ──────────────────


def _run_async(coro):
    import asyncio

    return asyncio.run(coro)
