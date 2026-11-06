"""Unit tests for the MCP server (server.py).

Covers HealthMonitor, get_status, _get_memory_mb, TokenAuthMiddleware,
download_file, and the lifespan startup/shutdown sequence using monkeypatched
dependencies so no real server process or network is required.
"""

from __future__ import annotations

import asyncio
import json
import os
import threading
from typing import Any
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kali_mcp.server import (
    HealthMonitor,
    TokenAuthMiddleware,
    _get_memory_mb,
    download_file,
    force_cleanup,
    health,
    health_check,
    lifespan,
    main,
)


class TestHealthMonitor:
    """Tests for the background HealthMonitor thread."""

    def test_default_state(self) -> None:
        hm = HealthMonitor()
        assert hm._running is False
        assert hm._request_count == 0

    def test_start_and_stop(self) -> None:
        hm = HealthMonitor()
        hm.start()
        assert hm._running is True
        # The background thread should be alive
        assert any(t.name == "health-monitor" and t.is_alive() for t in threading.enumerate())
        hm.stop()
        assert hm._running is False

    def test_start_idempotent(self) -> None:
        hm = HealthMonitor()
        hm.start()
        first_thread_count = sum(1 for t in threading.enumerate() if t.name == "health-monitor")
        hm.start()  # should not spawn a second thread
        second_thread_count = sum(1 for t in threading.enumerate() if t.name == "health-monitor")
        assert first_thread_count == second_thread_count
        hm.stop()

    def test_record_request_and_error(self) -> None:
        hm = HealthMonitor()
        hm.record_request()
        hm.record_error()
        hm.record_request()
        assert hm._request_count == 2
        assert hm._error_count == 1

    def test_get_status_shape(self) -> None:
        hm = HealthMonitor()
        status = hm.get_status()
        assert "status" in status
        assert status["status"] == "healthy"
        assert "uptime_seconds" in status
        assert "active_executions" in status
        assert "total_requests" in status
        assert "total_errors" in status
        assert "tools_registered" in status
        assert "memory_mb" in status

    def test_get_stuck_executions_empty(self) -> None:
        from kali_mcp.execution import engine

        assert engine.get_stuck_executions() == []

    def test_force_cleanup(self) -> None:
        from kali_mcp.execution import engine

        count = engine.force_cleanup()
        assert isinstance(count, int)


class TestGetMemoryMb:
    def test_returns_float(self) -> None:
        result = _get_memory_mb()
        assert isinstance(result, float)
        assert result >= 0.0


class TestLifespan:
    """Tests for the server lifespan context manager (mocked deps)."""

    @pytest.mark.asyncio
    async def test_lifespan_startup_and_shutdown(self) -> None:
        fake_app = MagicMock()
        with (
            patch("kali_mcp.server.ensure_vault_dirs"),
            patch("kali_mcp.server.db_manager.get_db", return_value=MagicMock()),
            patch("shutil.which", side_effect=lambda b: b == "nmap"),
            patch.object(health, "start") as mock_start,
            patch.object(health, "stop") as mock_stop,
            patch("kali_mcp.server.engine") as mock_engine,
        ):
            mock_engine.force_cleanup = MagicMock()
            async with lifespan(fake_app):
                mock_start.assert_called_once()
            mock_stop.assert_called_once()
            mock_engine.force_cleanup.assert_called_once()

    @pytest.mark.asyncio
    async def test_lifespan_handles_vault_failure(self) -> None:
        fake_app = MagicMock()
        with (
            patch(
                "kali_mcp.server.ensure_vault_dirs",
                side_effect=RuntimeError("boom"),
            ),
            patch("kali_mcp.server.db_manager.get_db", return_value=None),
            patch("shutil.which", return_value=None),
            patch.object(health, "start"),
            patch.object(health, "stop"),
            patch("kali_mcp.server.engine") as mock_engine,
        ):
            mock_engine.force_cleanup = MagicMock()
            # Should not raise despite vault/init failures
            async with lifespan(fake_app):
                pass


class TestTokenAuthMiddleware:
    """Tests for the bearer-token auth middleware."""

    @pytest.mark.asyncio
    async def test_allows_request_with_valid_bearer_token(self) -> None:
        mw = TokenAuthMiddleware(app=AsyncMock(), token="secret-token")
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer secret-token")],
            "query_string": b"",
        }
        received = {}

        async def fake_receive():
            return {"type": "http.request"}

        async def fake_send(message):
            received["message"] = message

        inner_app = AsyncMock()
        mw.app = inner_app
        await mw(scope, fake_receive, fake_send)
        inner_app.assert_awaited_once_with(scope, fake_receive, fake_send)

    @pytest.mark.asyncio
    async def test_allows_request_with_query_token(self) -> None:
        mw = TokenAuthMiddleware(app=AsyncMock(), token="query-token", token_in_query=True)
        scope = {
            "type": "http",
            "headers": [],
            "query_string": b"token=query-token",
        }
        received: dict[str, Any] = {}

        async def fake_receive():
            return {"type": "http.request"}

        async def fake_send(message):
            received["message"] = message

        inner_app = AsyncMock()
        mw.app = inner_app
        await mw(scope, fake_receive, fake_send)
        inner_app.assert_awaited_once_with(scope, fake_receive, fake_send)

    @pytest.mark.asyncio
    async def test_rejects_invalid_token(self) -> None:
        mw = TokenAuthMiddleware(app=AsyncMock(), token="correct")
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer wrong")],
            "query_string": b"",
        }
        messages: list[dict[str, Any]] = []

        async def fake_receive():
            return {"type": "http.request"}

        async def fake_send(message):
            messages.append(message)

        inner_app = AsyncMock()
        mw.app = inner_app
        await mw(scope, fake_receive, fake_send)
        inner_app.assert_not_called()
        assert messages
        assert messages[0]["type"] == "http.response.start"
        assert messages[0]["status"] == 401

    @pytest.mark.asyncio
    async def test_non_http_scope_passes_through(self) -> None:
        mw = TokenAuthMiddleware(app=AsyncMock(), token="secret")
        scope = {"type": "lifespan"}
        inner_app = AsyncMock()
        mw.app = inner_app
        await mw(scope, MagicMock(), MagicMock())
        inner_app.assert_awaited_once()


class TestDownloadFile:
    def test_missing_path_returns_400(self) -> None:
        fake_request = MagicMock()
        fake_request.query_params.get.return_value = ""
        result = asyncio.run(download_file(fake_request))
        assert result.status_code == 400
        body = json.loads(result.body)
        assert "error" in body

    def test_nonexistent_file_returns_404(self, tmp_path) -> None:
        fake_request = MagicMock()
        fake_request.query_params.get.return_value = str(tmp_path / "does_not_exist.bin")
        result = asyncio.run(download_file(fake_request))
        assert result.status_code == 404

    def test_serves_existing_file(self, tmp_path) -> None:
        target = tmp_path / "artifact.bin"
        target.write_bytes(b"\x00\x01\x02\x03")
        fake_request = MagicMock()
        fake_request.query_params.get.return_value = str(target)
        result = asyncio.run(download_file(fake_request))
        assert result.status_code == 200
        assert result.media_type == "application/octet-stream"


class TestMCPHealthAndCleanupTools:
    """Tests for the health_check and force_cleanup MCP tools."""

    def test_health_check_returns_json(self) -> None:
        result = health_check()
        data = json.loads(result)
        assert "status" in data
        assert data["status"] == "healthy"
        assert "uptime_seconds" in data
        assert "available_tools" in data
        assert isinstance(data["available_tools"], list)
        assert "memory_mb" in data

    def test_force_cleanup_returns_json(self) -> None:
        result = force_cleanup()
        data = json.loads(result)
        assert data["status"] == "cleaned"
        assert "requests_cleaned" in data
        assert "message" in data


class TestMainEntry:
    """Tests for the server main() function."""

    def test_main_invokes_uvicorn(self) -> None:
        from kali_mcp.config import Config

        fake_config = Config.__new__(Config)
        # minimal: set insecure True via env won't work; patch server.config instead
        import kali_mcp.server as srv

        orig = srv.config
        srv.config = Config.__wrapped__ if hasattr(Config, "__wrapped__") else orig
        # Easiest: monkeypatch the insecure attribute via a simple object
        class _C:
            transport = "sse"
            allowed_origins = "*"
            host = "127.0.0.1"
            port = 8399
            insecure = True
            api_token = ""
            token_in_query = False
            debug = False
            db_enabled = False

        srv.config = _C()
        try:
            with patch("uvicorn.run") as mock_uvicorn_run, patch("kali_mcp.server.signal"):
                main()
                mock_uvicorn_run.assert_called_once()
        finally:
            srv.config = orig
