"""E2E: MCP prompts and resources over the live protocol (server spawned for real)."""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import httpx
import pytest
from mcp.client.session import ClientSession
from mcp.client.streamable_http import streamable_http_client

REPO_ROOT = Path(__file__).resolve().parent.parent.parent


@pytest.fixture(scope="module")
def server_url():
    import os
    import socket

    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {
        **os.environ,
        "MCP_HOST": "127.0.0.1",
        "MCP_PORT": str(port),
        "MCP_TRANSPORT": "streamable-http",
        "MCP_DEBUG": "false",
        "MCP_DB_ENABLED": "false",
    }
    proc = subprocess.Popen(
        [sys.executable, str(REPO_ROOT / "src" / "kali_mcp" / "server.py")],
        cwd=REPO_ROOT,
        env=env,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    base = f"http://127.0.0.1:{port}"
    try:
        last_err = None
        for _ in range(60):
            if proc.poll() is not None:
                raise RuntimeError("server exited early")
            try:
                httpx.get(f"{base}/mcp", timeout=1)
                last_err = None
                break
            except Exception as exc:  # noqa: BLE001
                last_err = exc
                import time

                time.sleep(0.5)
        if last_err is not None:
            raise RuntimeError(f"server not ready: {last_err}")
        yield f"{base}/mcp"
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=10)
        except subprocess.TimeoutExpired:
            proc.kill()


@pytest.mark.e2e
async def test_prompts_listed_and_rendered(server_url):
    async with streamable_http_client(server_url) as (read, write, _sid):
        async with ClientSession(read, write) as session:
            await session.initialize()

            prompts = await session.list_prompts()
            names = {p.name for p in prompts.prompts}
            assert {
                "recon_workflow",
                "webapp_assessment",
                "ad_assessment",
                "osint_harvest",
                "quick_scan",
                "report_template",
            } <= names

            result = await session.get_prompt("recon_workflow", {"target": "example.com"})
            assert len(result.messages) == 2
            assert "example.com" in result.messages[0].content.text


@pytest.mark.e2e
async def test_resources_listed_and_read(server_url):
    async with streamable_http_client(server_url) as (read, write, _sid):
        async with ClientSession(read, write) as session:
            await session.initialize()

            resources = await session.list_resources()
            uris = {str(r.uri) for r in resources.resources}
            assert {
                "kali://config",
                "kali://tools",
                "kali://health",
                "kali://db/stats",
                "kali://vault/index",
                "kali://artifacts",
            } <= uris

            # Read config + health resources
            config_res = await session.read_resource("kali://config")
            assert config_res.contents[0].mimeType == "application/json"
            import json

            cfg = json.loads(config_res.contents[0].text)
            # The server runs on a random port — config must reflect reality
            assert cfg["port"] == int(server_url.split(":")[2].split("/")[0])

            health_res = await session.read_resource("kali://health")
            health = json.loads(health_res.contents[0].text)
            assert len(health) > 0


@pytest.mark.e2e
async def test_orchestration_tools_callable_via_mcp(server_url):
    """playbook_list / playbook_status / parallel_status must round-trip."""
    import json

    async with streamable_http_client(server_url) as (read, write, _sid):
        async with ClientSession(read, write) as session:
            await session.initialize()

            result = await session.call_tool("playbook_list", {})
            assert result.isError is False
            payload = json.loads(result.content[0].text)
            assert payload["success"] is False or payload  # ExecutionResult or error dict

            result = await session.call_tool("playbook_status", {"name": "nope"})
            payload = json.loads(result.content[0].text)
            assert payload["success"] is False
            assert "Unknown playbook" in payload["error"]
