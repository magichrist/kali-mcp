"""End-to-end tests: spawn the real MCP server and speak MCP over HTTP.

These tests launch server.py as a subprocess on a random port using the
streamable-http transport, then use the official `mcp` client to:
  1. perform the MCP handshake
  2. list tools and verify the full inventory is exposed
  3. call generic_command and verify a real round-trip execution
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
# 72 tools from ALL_TOOLS + force_cleanup + health_check (registered in server.py)
EXPECTED_MCP_TOOL_COUNT = 77


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
        [sys.executable, str(REPO_ROOT / "src" / "kmcp" / "server.py")],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        # Wait for the server to accept connections
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
async def test_mcp_handshake_and_tool_listing(server_url):
    async with (
        streamable_http_client(server_url) as (read, write, _get_session_id),
        ClientSession(read, write) as session,
    ):
        result = await session.initialize()
        assert result.serverInfo.name

        tools = await session.list_tools()
        names = {t.name for t in tools.tools}
        assert len(names) == EXPECTED_MCP_TOOL_COUNT, f"got {len(names)} tools"
        assert {
            "nmap",
            "generic_command",
            "hydra",
            "parallel_execute",
            "playbook_recon",
            "playbook_engine",
            "playbook_status",
            "health_check",
            "force_cleanup",
        } <= names

        resources = await session.list_resources()
        resource_uris = {str(r.uri) for r in resources.resources}
        assert "kali://config" in resource_uris
        assert "kali://db/stats" in resource_uris
        assert "kali://vault/index" in resource_uris


@pytest.mark.e2e
async def test_mcp_roundtrip_execution(server_url):
    async with (
        streamable_http_client(server_url) as (read, write, _get_session_id),
        ClientSession(read, write) as session,
    ):
        await session.initialize()
        result = await session.call_tool("generic_command", {"command": "echo e2e_roundtrip"})
        assert result.isError is False
        payload = json.loads(result.content[0].text)
        assert payload["success"] is True
        assert payload["stdout"].strip() == "e2e_roundtrip"
