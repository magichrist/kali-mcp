"""Extended unit tests for the MCP server (kali_mcp/server.py).

Covers HealthMonitor stuck-execution cleanup, TokenAuthMiddleware token
variants, health_check / force_cleanup output shapes, and the monitor_stream
/ monitor_action HTTP endpoints using mocked dependencies.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from kali_mcp.server import (
    HealthMonitor,
    TokenAuthMiddleware,
    force_cleanup,
    health_check,
    monitor_action,
    monitor_stream,
)


class TestHealthMonitorExtended:
    def test_check_triggers_force_cleanup_when_stuck_exceeds_max_concurrent(self) -> None:
        hm = HealthMonitor()
        stuck = [
            {"request_id": f"r{i}", "tool": "nmap", "elapsed_seconds": 10.0}
            for i in range(11)
        ]
        fake_config = MagicMock()
        fake_config.max_concurrent = 10
        with patch("kali_mcp.server.engine") as mock_engine, patch(
            "kali_mcp.server.config", fake_config
        ):
            mock_engine.get_stuck_executions.return_value = stuck
            mock_engine.force_cleanup.return_value = 5
            mock_engine.active_count = 0
            hm._check()
            mock_engine.force_cleanup.assert_called_once()

    def test_check_does_not_force_cleanup_when_stuck_below_threshold(self) -> None:
        hm = HealthMonitor()
        stuck = [
            {"request_id": "r1", "tool": "nmap", "elapsed_seconds": 10.0}
        ]
        fake_config = MagicMock()
        fake_config.max_concurrent = 10
        with patch("kali_mcp.server.engine") as mock_engine, patch(
            "kali_mcp.server.config", fake_config
        ):
            mock_engine.get_stuck_executions.return_value = stuck
            mock_engine.active_count = 0
            hm._check()
            mock_engine.force_cleanup.assert_not_called()


class TestTokenAuthMiddlewareExtended:
    @pytest.mark.asyncio
    async def test_empty_token_bypasses_auth(self) -> None:
        mw = TokenAuthMiddleware(app=AsyncMock(), token="")
        scope = {"type": "http", "headers": [], "query_string": b""}
        inner = AsyncMock()
        mw.app = inner

        async def receive():
            return {"type": "http.request"}

        async def send(message):
            pass

        await mw(scope, receive, send)
        inner.assert_awaited_once_with(scope, receive, send)

    @pytest.mark.asyncio
    async def test_valid_bearer_token_passes(self) -> None:
        mw = TokenAuthMiddleware(app=AsyncMock(), token="secret-token")
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer secret-token")],
            "query_string": b"",
        }
        inner = AsyncMock()
        mw.app = inner

        async def receive():
            return {"type": "http.request"}

        async def send(message):
            pass

        await mw(scope, receive, send)
        inner.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_query_token_is_accepted(self) -> None:
        mw = TokenAuthMiddleware(app=AsyncMock(), token="q", token_in_query=True)
        scope = {
            "type": "http",
            "headers": [],
            "query_string": b"token=q",
        }
        inner = AsyncMock()
        mw.app = inner

        async def receive():
            return {"type": "http.request"}

        async def send(message):
            pass

        await mw(scope, receive, send)
        inner.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_invalid_token_returns_401(self) -> None:
        mw = TokenAuthMiddleware(app=AsyncMock(), token="correct")
        scope = {
            "type": "http",
            "headers": [(b"authorization", b"Bearer wrong")],
            "query_string": b"",
        }
        messages: list = []

        async def receive():
            return {"type": "http.request"}

        async def send(message):
            messages.append(message)

        inner = AsyncMock()
        mw.app = inner
        await mw(scope, receive, send)
        inner.assert_not_awaited()
        assert messages
        assert messages[0]["type"] == "http.response.start"
        assert messages[0]["status"] == 401


class TestHealthCheckAndForceCleanupExtended:
    def test_health_check_includes_available_tools(self) -> None:
        data = json.loads(health_check())
        assert data["status"] == "healthy"
        assert isinstance(data["available_tools"], list)
        assert len(data["available_tools"]) > 0

    def test_health_check_includes_stuck_executions_when_present(self) -> None:
        with patch(
            "kali_mcp.server.engine.get_stuck_executions",
            return_value=[{"request_id": "r1"}],
        ):
            data = json.loads(health_check())
            assert "stuck_executions" in data
            assert data["stuck_executions"] == [{"request_id": "r1"}]

    def test_force_cleanup_shape(self) -> None:
        data = json.loads(force_cleanup())
        assert data["status"] == "cleaned"
        assert "requests_cleaned" in data
        assert "message" in data


class TestMonitorEndpoints:
    @pytest.mark.asyncio
    async def test_monitor_stream_returns_streaming_response(self) -> None:
        fake_request = MagicMock()
        response = await monitor_stream(fake_request)
        from starlette.responses import StreamingResponse

        assert isinstance(response, StreamingResponse)

    @pytest.mark.asyncio
    async def test_monitor_action_get_snapshot(self) -> None:
        body = json.dumps({"action": "get_snapshot"}).encode()
        scope = {"type": "http", "headers": [], "query_string": b"", "method": "POST"}

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        fake_request = MagicMock()
        fake_request.scope = scope
        fake_request.receive = receive
        with patch("kali_mcp.server.monitor") as mock_monitor:
            mock_monitor.build_snapshot.return_value = {"uptime_seconds": 1.0}
            response = await monitor_action(fake_request)
            assert response.status_code == 200
            data = json.loads(response.body)
            assert data == {"uptime_seconds": 1.0}

    @pytest.mark.asyncio
    async def test_monitor_action_unknown_action_returns_400(self) -> None:
        body = json.dumps({"action": "bogus"}).encode()
        scope = {"type": "http", "headers": [], "query_string": b"", "method": "POST"}

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        fake_request = MagicMock()
        fake_request.scope = scope
        fake_request.receive = receive
        response = await monitor_action(fake_request)
        assert response.status_code == 400

    @pytest.mark.asyncio
    async def test_monitor_action_invalid_json_returns_400(self) -> None:
        body = b"{not json"
        scope = {"type": "http", "headers": [], "query_string": b"", "method": "POST"}

        async def receive():
            return {"type": "http.request", "body": body, "more_body": False}

        fake_request = MagicMock()
        fake_request.scope = scope
        fake_request.receive = receive
        response = await monitor_action(fake_request)
        assert response.status_code == 400
