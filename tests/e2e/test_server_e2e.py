"""End-to-end tests: spawn the real MCP server and exercise health + tools over HTTP.

Spawns server.py as a subprocess on a free port using streamable-http transport,
then uses the official mcp client plus httpx to verify:
  1. health_check tool output over the MCP endpoint
  2. force_cleanup tool output over the MCP endpoint
  3. generic_command round-trip execution over HTTP
  4. monitor/action HTTP endpoint behaviors
"""

from __future__ import annotations

import json
import socket
import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


@pytest.fixture(scope="module")
def server_url():
    """Start the MCP server on a free port; yield its URL; shut it down."""
    port = _free_port()
    env = {
        **__import__("os").environ,
        "MCP_HOST": "127.0.0.1",
        "MCP_PORT": str(port),
        "MCP_TRANSPORT": "streamable-http",
        "MCP_DEBUG": "false",
        "MCP_DB_ENABLED": "false",
        "KALI_MCP_INSECURE": "1",
    }
    proc = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "src" / "kali_mcp" / "server.py")],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        last_err: Exception | None = None
        for _ in range(60):
            if proc.poll() is not None:
                out = proc.stdout.read().decode(errors="replace") if proc.stdout else ""
                raise RuntimeError(f"server exited early:\n{out[-2000:]}")
            try:
                httpx.get(f"{base}/mcp", timeout=1)
                last_err = None
                break
            except Exception as exc:  # noqa: BLE001 — connection refused until ready
                last_err = exc
                import time

                time.sleep(0.5)
        if last_err is not None:
            raise RuntimeError(f"server did not become ready: {last_err}")
        yield f"{base}/mcp"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.e2e
async def test_health_check_tool_over_http(server_url):
    async with (
        streamable_http_client(server_url) as (read, write, _sid),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("health_check", {})
        assert result.isError is False
        data = json.loads(result.content[0].text)
        assert data["status"] == "healthy"
        assert "uptime_seconds" in data
        assert isinstance(data["available_tools"], list)
        assert len(data["available_tools"]) > 0
        assert "memory_mb" in data


@pytest.mark.e2e
async def test_force_cleanup_tool_over_http(server_url):
    async with (
        streamable_http_client(server_url) as (read, write, _sid),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("force_cleanup", {})
        assert result.isError is False
        data = json.loads(result.content[0].text)
        assert data["status"] == "cleaned"
        assert "requests_cleaned" in data
        assert "message" in data


@pytest.mark.e2e
async def test_generic_command_roundtrip_over_http(server_url):
    async with (
        streamable_http_client(server_url) as (read, write, _sid),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("generic_command", {"command": "echo e2e-server-ok"})
        assert result.isError is False
        payload = json.loads(result.content[0].text)
        assert payload["success"] is True
        assert payload["stdout"].strip() == "e2e-server-ok"


@pytest.mark.e2e
async def test_monitor_action_http_endpoint(server_url):
    base = server_url.removesuffix("/mcp")

    # invalid JSON -> 400
    resp = httpx.post(f"{base}/monitor/action", content=b"{not json", timeout=2)
    assert resp.status_code == 400

    # unknown action -> 400
    resp = httpx.post(f"{base}/monitor/action", json={"action": "bogus"}, timeout=2)
    assert resp.status_code == 400

    # get_snapshot -> 200 with snapshot shape
    resp = httpx.post(f"{base}/monitor/action", json={"action": "get_snapshot"}, timeout=2)
    assert resp.status_code == 200
    data = resp.json()
    assert isinstance(data, dict)
    assert "health" in data
    assert "uptime_seconds" in data["health"]


@pytest.mark.e2e
async def test_monitor_stream_http_endpoint(server_url):
    base = server_url.removesuffix("/mcp")
    with httpx.Client() as client:
        with client.stream("GET", f"{base}/monitor/stream", timeout=3) as resp:
            assert resp.status_code == 200
            assert "text/event-stream" in resp.headers.get("content-type", "")
            for chunk in resp.iter_text():
                if chunk.strip():
                    break  # received the initial snapshot; close the stream
